# AI Usage

Built with Claude Code (Claude Sonnet 5), used throughout — not just for
scaffolding. Honest breakdown of where and how.

## How Claude was used

- **No-thinking / low-effort mode** for mechanical coding: scaffolding
  (Django, Expo, OpenRouter client), boilerplate CRUD, wiring endpoints,
  writing tests once the shape of a fix was decided.
- **Extended thinking** for decisions with real downstream consequences:
  the confidence-scoring formula for catalog matching, the local-vs-hosted
  compute split, and debugging subtle pipeline bugs (see below). These are
  the calls that could cascade into hard-to-defend architecture if gotten
  wrong, so more reasoning budget went here deliberately.
- Progress was checked against the take-home spec at intervals rather than
  letting Claude run unsupervised for hours — see commit history for the
  resulting checkpoints.

## Specific contributions worth naming

- **Catalog generation**: Claude drafted the initial `catalog.csv` column
  structure and entries from a description of the required messiness
  traps (duplicate editions, US/UK title variants, homonym titles,
  omnibus vs. individual volumes, substring titles, author name-format
  variants). I own the catalog's content and correctness — spot-checked
  entries and added edge cases (noisy-OCR digit confusion, title-only/no-author
  cases) beyond what was generated, listed in the dev log.
- **Matcher design discussion**: Claude and I evaluated `rapidfuzz`
  scoring functions together. `WRatio` was tried first and rejected —
  its partial/substring blending produced false positives on short common
  words ("book", "great") shared across unrelated titles. Switched to
  `token_sort_ratio`, which is stricter and normalizes word order, at the
  cost of some recall. This was a joint decision, not a delegated one —
  I ran both against the catalog's edge cases before choosing.
- **EAST detector bug**: Claude helped diagnose that EAST was squeezing
  the whole input image into one 320x320 tile rather than tiling the
  original resolution into multiple 320x320 chunks, which was silently
  destroying detection accuracy on any non-square photo. Fix (tile the
  source image, run detection per tile, merge overlapping boxes) was
  Claude-authored, verified by me against real test photos.
- **VLM prompt engineering**: the rotation-aware, upscaled-crop,
  no-guessing prompt in `pipeline.py` (`READ_PROMPT`) went through several
  iterations against real OpenRouter calls on real bookshelf photos —
  Claude drafted revisions, I evaluated them against the known-good
  spot-check set and decided which to keep.
- **Backend endpoint wiring** (`vision/views.py`, `vision/urls.py`):
  mechanical — Claude wrote it, I reviewed the diff and smoke-tested the
  live endpoint against a real photo before accepting it.
- **Mobile UI** (`mobile/App.js`, all five screens): Claude-authored from
  a detailed brief (screen flow, band-gating rules, graceful-failure
  cases). I drove live testing against the real backend afterward,
  which is what actually found the bugs below — the code compiling and
  the app looking right were not treated as "working."
- **Bugs found only by running the app, not by review**: `ALLOWED_HOSTS`
  rejecting every non-localhost request (400 on first real device/browser
  test), the web image-upload FormData shape being wrong for
  `expo-image-picker`'s `blob:` URIs on web (immediate 400, before the
  pipeline ever ran), and the review screen offering a one-tap Confirm
  for `"none"`-band (near-noise) matches, which I traced directly to a
  run of duplicate library entries during my own testing. Claude
  diagnosed and fixed each once I reported the symptom; I verified each
  fix against the live app/API before accepting it, not just the diff.
- **VLM read-quality tuning, round 2**: I flagged specific bad reads
  from real photos ("Greek Plays" → "Greek", a clearly-legible spine
  marked unreadable). Claude's read: the "don't guess" prompt from the
  first round was suppressing partial-confidence words, not just
  invented ones. I asked for the model-swap question directly rather
  than assuming a fix — Claude ran a real A/B (`claude-sonnet-4.5` vs.
  `gemini-2.5-flash`) against the same 27 crops before recommending
  keeping the current model, with numbers, not a guess.
- **Catalog expansion**: I decided the catalog needed to grow after
  seeing real test-photo reads with no match; Claude drafted the new
  entries (real titles, plausible ISBNs) and wove in additional
  messiness traps per my instruction to match the original batch's
  intent, not just add clean titles.

## What I did not delegate

- Whether a design choice was acceptable for the task's grading criteria
  (e.g., accepting the precision/recall trade-off in the VLM prompt
  rather than chasing a marginal accuracy gain — see README/dev log).
- Reading and judging the actual VLM outputs against known-good values —
  every accuracy claim in this repo is checked against a real photo, not
  assumed correct because the code ran without error.
- The decision to measure real OpenRouter spend (via the dashboard) rather
  than ship a made-up cost estimate.
- The decision *not* to touch the EAST detector or its merge logic this
  close to the deadline, even after finding real box-quality issues live
  — weighed the spec's explicit "raw accuracy isn't graded if you
  measured and handled it" against the cost of re-validating a detector
  swap with no time buffer, and chose to document the limitation instead.

## Cost of using AI to build this

Not tracked separately from the OpenRouter usage reported in the README —
Claude Code usage itself isn't billed per-call the way the VLM pipeline is.
