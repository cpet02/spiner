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

## What I did not delegate

- Whether a design choice was acceptable for the task's grading criteria
  (e.g., accepting the precision/recall trade-off in the VLM prompt
  rather than chasing a marginal accuracy gain — see README/dev log).
- Reading and judging the actual VLM outputs against known-good values —
  every accuracy claim in this repo is checked against a real photo, not
  assumed correct because the code ran without error.
- The decision to measure real OpenRouter spend (via the dashboard) rather
  than ship a made-up cost estimate.

## Cost of using AI to build this

Not tracked separately from the OpenRouter usage reported in the README —
Claude Code usage itself isn't billed per-call the way the VLM pipeline is.
