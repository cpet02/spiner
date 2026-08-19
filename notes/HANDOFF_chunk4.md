SHELFIE HANDOFF — starting chunk 4 (Backend Wiring)

STATE: Chunks 1–3 committed, plus a chunk-3.5 VLM validation pass
(commit 55f0aec: "Improve VLM read step: rotation-aware prompt, crop
upscaling, concurrent calls"). Repo: https://github.com/cpet02/spiner

IMPORTANT — working directory note: this handoff was written from a git
worktree at C:\spiner\.claude\worktrees\shelfie-vlm-pipeline-test-12fcd9,
NOT the main checkout at C:\spiner. Point the new session at C:\spiner
(main checkout) unless you specifically want to keep working in that
worktree/branch. If pointing at C:\spiner, first pull/merge branch
claude/shelfie-vlm-pipeline-test-12fcd9 (or just check that commit 55f0aec
is present) so the chunk-3.5 changes aren't missed.

WHAT HAPPENED IN CHUNK 3.5 (full detail in DEV_LOG_chunk3.5_vlm_test.md,
kept as your personal log, not in git):

Ran the pipeline end-to-end for the first time on a real photo with a real
OpenRouter key. Initial result: only 2/8 known-good spot-check values came
back correct — VLM was confidently hallucinating plausible-but-wrong book
titles, not failing loudly. Dumped the actual crops to disk and visually
confirmed several were legible to a human eye even where the VLM misread
them — so the problem is VLM read reliability, not crop/detection quality.

Two fixes applied and committed:
- Crop upscaling (bicubic, floor of 200px short side) before sending to VLM
- Prompt now warns text may be rotated 90° on narrow spines, and explicitly
  forbids guessing a plausible-sounding title when unsure

Effect: hallucination dropped (fewer confident-wrong reads, more honest
"unreadable"), but recall on the known-good set didn't improve overall —
it's a precision/recall trade, not a net accuracy win. Tested on 3
additional real bookshelf photos (now in vision/test_photos/,
bookshelf_02/03/04.jpg) including a high-res reshoot of the original shelf.
Key finding: accuracy tracks spine typography, not resolution — an 8x
higher-resolution reshoot of the same shelf barely improved; a shelf with
bold sans-serif spines (fantasy novels) got multiple exact matches
including one perfect end-to-end catalog match. More pixels didn't fix it;
thin serif/gilt text is still hard for this VLM regardless of crop size.

Also fixed: VLM calls were fully sequential (one blocking HTTP request at
a time) — parallelized with an 8-worker thread pool since these are
independent I/O calls. Cut a 31-region photo from 107s to 32s, no accuracy
change. Demo-latency risk is basically resolved.

KNOWN OPEN ITEMS GOING IN:
- estimated_cost_usd is STILL a placeholder (EST_COST_PER_CALL_USD = 0.003
  in pipeline.py), now just multiplied by parallel call count instead of
  sequential — still not verified against real OpenRouter billing. Check
  the OpenRouter dashboard for actual spend before this goes in any README
  numbers section.
- Detection recall (~14/50 visible spines on typical shelves) — untouched,
  accepted limitation, not in scope.
- Read accuracy on dense/small-serif-text shelves is still weak (~50-55%
  "ok" rate, meaningfully lower exact-match rate). Not chased further this
  session — diminishing returns without a bigger lever (see options below).
  This is worth mentioning proactively at demo time rather than letting it
  surprise anyone live.
- No formal precision/recall measurement has been done yet, only visual
  spot-checks against known-good values. Worth doing if read-accuracy work
  resumes.

IF READ ACCURACY WORK RESUMES LATER (not now — see NEXT below), options
considered but not attempted, roughly cheapest first: retry pass on
unreadable crops at further zoom; A/B a different hosted VLM model via
OpenRouter against the same known-good spot check (typography-sensitivity
may be model-specific); batch 2-3 neighboring crops per VLM call (untested,
risk of cross-contamination); formal precision/recall harness before
further blind tuning.

NEXT — Chunk 4: Backend Wiring (~1h budgeted per original plan):
Django endpoint wiring detection -> VLM -> matcher -> JSON response, using
vision/pipeline.run_pipeline() as-is (no rebuild needed, just an endpoint
wrapper). pipeline.run_pipeline() already returns a clean dict with
"books" (each with status/box/detected_title/detected_author/match/
candidates) and "regions_found"/"latency_s"/"estimated_cost_usd" — the
endpoint should mostly just accept an uploaded image, call this, and
return the dict as JSON.

PACE CHECK: chunks 1-3 took ~3h real-world against a 6h budget. Chunk 3.5
(today's VLM validation + fixes) was not in the original budget breakdown
but was necessary groundwork — factor that in when judging remaining pace
for chunks 4-6.

RESPONSE STYLE: condensed replies, minimal restated context. Personal dev
log kept separately by user (DEV_LOG_chunk3.5_vlm_test.md pattern) — only
touch AI_USAGE.md/README when something falls out of scope and needs
demo-time explanation.
