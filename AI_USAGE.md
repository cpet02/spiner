# AI Usage

Built with Claude Code (Claude Sonnet 5), used throughout — not just for
scaffolding. Honest breakdown of where and how.

## How Claude was used

- **Low-effort mode** for mechanical coding: scaffolding, boilerplate CRUD,
  endpoint wiring, tests once a fix's shape was already decided.
- **Extended thinking** for decisions with real consequences: the matching
  formula, the local-vs-hosted split, subtle pipeline bugs.
- Progress checked against the spec at intervals, not left to run
  unsupervised — see commit history for the checkpoints.

## Specific contributions worth naming

The columns below split three things that are easy to blur together:
**Idea** (whose call was it), **Code** (who typed it), and **Verified**
(who confirmed it actually worked, and how). I wrote almost none of the
code directly — but I did not accept any of it on faith either. Every
row's Verified column is something I did myself, against the real app
or a real photo, not just a passing test or a clean diff.

| What | Idea | Code | Verified |
|---|---|---|---|
| `catalog.csv` structure & entries | Claude, from my trap description | Claude | Me — spot-checked entries, added edge cases beyond what was generated |
| Matcher scoring (`token_sort_ratio` over `WRatio`) | Joint — evaluated together | Claude | Me — ran both scorers against the catalog's edge cases myself |
| EAST tiling bug (whole photo squeezed into one 320x320 tile) | Claude diagnosed | Claude | Me — against real test photos |
| `READ_PROMPT` iterations | Claude drafted revisions | Claude | Me — against the known-good spot-check set, I decided what to keep |
| Backend wiring (`views.py`, `urls.py`) | Claude | Claude | Me — reviewed diff, smoke-tested the live endpoint |
| Mobile UI (`App.js`) | Claude, from my detailed brief | Claude | Me — live testing against the real backend, which is what found the bugs below |
| `ALLOWED_HOSTS`, web FormData shape, band-gated Confirm bugs | Me — reported each symptom | Claude | Me — verified each live |
| VLM truncation fix + model A/B | Me — flagged bad reads, asked for the model-swap question directly | Claude | Me — against the spot-check set |
| Catalog expansion | Me — decided it needed to grow | Claude | Me |
| Matcher case-sensitivity bug | Claude — found testing photos I supplied | Claude | Me — against the same photos |
| Deep correctness audit (5 parallel file reviews, NMS bug) | Me — asked directly for a fresh pass | Claude | Me — required a numeric repro before any fix, re-tested every fix after |
| Final defense-readiness cleanup (dead code, unwired `isbn`, stale docstring, inert `MAILERS` setting, unused `expo-status-bar` dep) | Me — asked Claude to find anything I couldn't justify live | Claude | Me — reviewed each, understand why each existed and why it's gone |

## What I did not delegate

- Whether a design choice was acceptable for the task's grading criteria
  (e.g. accepting the VLM prompt's precision/recall tradeoff).
- Reading and judging actual VLM outputs against known-good values — every
  accuracy claim here is checked against a real photo, not assumed correct
  because the code ran without error.
- Measuring real OpenRouter spend from the dashboard instead of shipping
  a made-up cost estimate.
- Not touching the EAST detector this close to the deadline even after
  finding real box-quality issues live — weighed the spec's "raw accuracy
  isn't graded if measured and handled" against re-validation cost with no
  time buffer, and chose to document instead of chase.

## Cost of using AI to build this

Not tracked separately from the OpenRouter usage reported in the README —
Claude Code usage itself isn't billed per-call the way the VLM pipeline is.
