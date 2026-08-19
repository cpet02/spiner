# Dev log — Chunk 3.5: first real VLM end-to-end test (2026-08-19)

## Starting point

Chunks 1–3 were done and committed: local EAST-based detection, a fuzzy
catalog matcher, and a mocked VLM pipeline wired together. Nothing had
been tested end-to-end against a real hosted VLM on a real photo — chunk 1–3
work validated detection and matching *separately*, with the VLM step
mocked out. The handoff going into today explicitly called this out as
"the single load-bearing unknown" before touching chunk 4 (backend wiring).

Known open items going in: detection recall was ~14/50 visible spines on
the original test photo (accepted, not a bug — EAST finds words, spines
need multiple words merged, dense shelves lose recall); `EST_COST_PER_CALL_USD`
in the pipeline was a hardcoded, never-verified placeholder ($0.003/call).

## What we tried, and why

**1. Ran the real pipeline for the first time** (detection → VLM read →
match) on `bookshelf_01.jpg` with a real (7-day, $1-capped) OpenRouter key.
Setup needed: EAST weights download (gitignored, ~96MB), a fresh `.venv`
(none existed), `.env` with the real key.

**Result:** only 2 of 8 known-good spot-check values came back correct
(INFIDEL, Shakespeare). The rest were plausible-but-wrong book titles —
not garbage, not empty, just confidently incorrect. Cost estimate
($0.042 for 14 calls) turned out to be circular — it's just
`calls * placeholder_constant`, not anything OpenRouter actually billed.
Still don't have a real per-call cost number; would need to check the
OpenRouter dashboard directly.

**2. Dumped the actual crops sent to the VLM to disk and looked at them
by eye**, rather than guessing at the cause. This was the single most
useful step — it falsified my first hypothesis. I expected the crops to
be illegible garbage (16–111px on a side, tiny). Several of them turned
out to be clearly legible to a human at 1:1 zoom — e.g. one crop plainly
read "...ANE AUSTEN" and the pipeline had reported "Lantern" with no
author for that exact box. So the bottleneck wasn't crop quality/framing,
it was the VLM confidently misreading (or outright inventing) text it
could have read correctly. Also saw the opposite failure: some legible
crops were marked "unreadable" even though a human could read them —
inconsistent in both directions, not just an over-confidence problem.

**3. Two fixes based on that finding:**
   - Upscaled any crop under 200px on the short side (bicubic) before
     sending to the VLM, in case resolution was silently costing accuracy
     even where crops looked legible to a human eye.
   - Rewrote the read prompt to (a) tell the model spine text may be
     rotated 90° on narrow crops, since several crops were tall-and-narrow
     with sideways text, and (b) explicitly forbid guessing a
     plausible-sounding title when unsure, instead of just asking for
     confidence.

   **Result on re-run:** hallucination dropped meaningfully — confident
   "ok" reads went from 12/14 to 7/14, with the difference moving to
   honest `unreadable` instead of invented titles. But it also cost some
   real recall: two crops that were correctly read before ("Shakespeare",
   the Austen spine) came back `unreadable` this time. Net measured
   accuracy against the known-good set stayed the same (2/8), just a
   different pair. My read: this is a legitimate trade (fewer false
   positives is worth more than fewer answers for a catalog-matching use
   case) but it didn't fix the underlying reliability problem, it just
   moved where the model fails.

**4. Tested on 3 more real bookshelf photos** (not staged — different
lighting, different shelf styles, different spine typography) to see if
`bookshelf_01`'s low resolution was itself a confound. One of the three
was the exact same shelf as `bookshelf_01` re-shot at ~8x the pixel count.

**Result — this was the most informative finding of the day:** accuracy
tracked *spine typography*, not resolution. The high-res reshoot of the
same English-lit shelf barely improved (10/19 ok, still garbled on most
non-bold-sans-serif titles — thin gilt/serif text like "Stevenson" read
as "Nevenson"). A different shelf with bold sans-serif spines (fantasy
novels, Robert Jordan/Sanderson/Bardugo) did clearly better — several
exact title+author matches, including one perfect end-to-end catalog
match ("Mistborn" / Brandon Sanderson, 100% score). So: **more pixels
doesn't fix small-serif-text recall; typography/contrast is the real
variable**, and that's a much harder thing to fix with prompt or crop
tweaks alone.

**5. Latency concern, raised directly:** a demo where someone hands over
a photo and waits 30–150 seconds is a bad look, independent of accuracy.
Looked at `ai_client.py` and found every VLM call was a blocking
`requests.post`, called strictly one-at-a-time in a `for` loop in
`run_pipeline`. Since these are independent I/O-bound HTTP calls (no
shared state between reads), there was no reason for them to be
sequential. Parallelized with a `ThreadPoolExecutor` (8 workers).

**Result:** the slowest tested photo (31 regions) went from 107s to 32s
— about 3.3x, not the theoretical 8x (detection + rate limits + overhead
eat into it), for zero accuracy change and a genuinely low-risk change
(same calls, same logic, just fanned out).

## Where this leaves things

- **Precision improved, recall on hard shelves didn't.** The rotation +
  "don't guess" prompt change is a net win and should stay. It does not
  fix the core issue: this VLM's OCR reliability drops hard on dense,
  small, serif/gilt spine text, and no amount of crop/prompt tuning so
  far has closed that gap.
- **Real cost per call is still unverified** — `estimated_cost_usd` is
  still a hardcoded constant, just multiplied by (now-parallel) call
  count. Needs a real look at the OpenRouter billing dashboard before it
  goes in any README numbers section.
- **Latency is no longer a demo risk** on the tested photos (low tens of
  seconds, not low hundreds).
- **Detection recall** (~14/50 visible spines on typical shelves) is
  still an open, accepted limitation — untouched today, not back in scope.

## Moving forward — options considered, not yet acted on

Ranked roughly cheapest/safest first, for a future session if there's
appetite to keep improving read accuracy rather than ship as-is:

1. Retry pass on `unreadable` crops only, at a further zoom/crop, before
   giving up — cheap in dollars (few extra calls) since detection already
   found the region.
2. Try a different hosted VLM model via OpenRouter and A/B against the
   same known-good spot check — typography-sensitivity may be
   model-specific, not universal to all VLMs.
3. Batch 2–3 neighboring crops into one VLM call with instructions to
   distinguish them — untested, could help or could cause cross-
   contamination between adjacent titles.
4. Formal precision/recall measurement instead of visual spot-checks —
   worth doing before making any more prompt/crop changes blind.

**Decision made today:** don't chase this further right now. Document it
honestly (this file + real numbers, once cost is verified, in the README)
and move to chunk 4 (Django endpoint wiring: detection → VLM → matcher →
JSON response) using `pipeline.run_pipeline()` as-is. Chunks 1–3 took
~3h against a 6h budget, so there's room, but the accuracy ceiling here
looks like it needs a different lever (model choice, retry logic) than
more tuning inside today's session — better spent building the working
end-to-end wired app and being upfront about this limitation at demo
time than polishing a read step that's hitting diminishing returns.
