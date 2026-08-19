SHELFIE HANDOFF — starting chunk 5 (Mobile UI)

STATE: Chunks 1–4 committed on `main` (commit `a682315`). Point this
session at `C:\spiner` directly, no worktree needed — everything is on
main, nothing to merge. Repo: https://github.com/cpet02/spiner

Backend is fully wired and live-tested:
- `POST /api/scan/` — multipart `image` upload -> runs the full
  detect (EAST) -> read (VLM via OpenRouter) -> match (rapidfuzz)
  pipeline -> returns `pipeline.run_pipeline()`'s dict as JSON.
- `GET/POST /api/library/` — list / create confirmed `LibraryEntry`
  rows (`title`, `author`, `isbn`, `match_score`, `added_at`).

Both endpoints were curl-tested against real photos/data this session —
trust the shape below, it's not speculative.

## Response shape from POST /api/scan/

```json
{
  "books": [
    {
      "status": "ok" | "unreadable" | "error",
      "box": [x1, y1, x2, y2],
      "detected_title": "...",       // only if status == "ok"
      "detected_author": "..." | null,
      "band": "auto" | "review" | "none",   // only if status == "ok"
      "match": {"title": "...", "author": "...", "score": 91.2} | null,
      "candidates": [ {"title", "author", "score"}, ... up to 3 ],
      "reason": "vlm_call_failed" | "malformed_json"  // only if status == "error"
    }
  ],
  "regions_found": 12,
  "latency_s": 4.31,
  "estimated_cost_usd": 0.0155,
  "detection_error": "..."   // only present if EAST itself failed
}
```

`band` bands: `auto` (score >= 90, confident), `review` (60–89,
plausible but needs a human), `none` (< 60, effectively no match).
`AUTO_THRESHOLD`/`REVIEW_THRESHOLD` live in `backend/vision/matcher.py`.

## Decisions already made — do not re-litigate these, just build

1. **No navigation library.** Single `App.js` (or a few plain component
   files) with local React state driving which screen renders:
   `capture -> processing -> results -> library`. The existing
   `mobile/App.js` scaffold has no react-navigation dependency and
   should stay that way — this is a small enough app that a state
   machine is genuinely simpler than a router, and "minimalistically
   functional" is the explicit brief. Don't install react-navigation.

2. **Auto vs. review split.** `band: "auto"` results get added to the
   library automatically when the scan completes (still show them in
   the results screen so the user sees what happened, just don't block
   on them). Everything else — `band: "review"`, `band: "none"`,
   `status: "unreadable"`, `status: "error"` — goes into a review list
   the user must act on one-by-one: **Confirm** (accept the top match
   or a picked candidate), **Correct** (pick one of the up-to-3
   `candidates` instead of the top match — do NOT build free-text
   search against the full catalog, the candidates list already is
   the correction UI), or **Discard** (drop it, never POSTed to
   `/api/library/`). This satisfies the spec's "must not be silently
   accepted, must not be silently dropped" requirement directly.

3. **Persistence is backend-side**, not AsyncStorage. Confirming an
   item POSTs to `/api/library/`; the library screen is just a GET
   against that endpoint. Single implicit user, no auth — matches the
   take-home's "not graded" list (auth is explicitly out of scope).

4. **Graceful failure in the UI is part of the grading rubric.**
   Handle explicitly, don't let any of these crash or blank-screen:
   - `regions_found: 0` (nothing detected) — show a clear empty state,
     not a silently empty list.
   - `status: "error"` books — show them with the `reason`, offer
     Discard (retry is out of scope, don't build it).
   - `status: "unreadable"` — same review flow as low-confidence, title
     shown as "couldn't read this one" with candidates likely absent
     (matcher won't have run without a title guess — check `pipeline.py`
     for how `unreadable` books flow into `books[]`, they won't have
     `match`/`candidates` keys populated the same way `ok` ones do).
   - Network/timeout failure calling `/api/scan/` itself (not a
     pipeline-internal error, an actual fetch failure) — show a retry
     button, don't hang on a spinner forever.

5. **API_BASE** in `mobile/App.js` needs to point at the dev machine's
   LAN IP (Expo on a physical device can't reach `localhost`). Leave
   it as an easily-editable constant at the top of the file, same as
   the current scaffold — don't over-engineer env config for this.

## What "minimalistically functional" means here

Four screens, plain `StyleSheet`, no design system, no animations
beyond what `expo-image-picker`/`ActivityIndicator` give for free.
Visual polish is explicitly not graded beyond "clean and usable." Do
not add a component library, do not add state management beyond
`useState`/`useReducer`, do not add navigation. If you find yourself
installing a new npm package, stop and ask first — the acceptable
list, if you need anything at all beyond what's already in
`mobile/package.json`, is `expo-image-picker` for capture/pick (check
if it's already installed before adding).

## Suggested flow to build

1. **Capture screen** (home): "Take Photo" / "Choose from Library"
   buttons (expo-image-picker), plus a "My Library" link to the
   library screen. On pick, immediately upload.
2. **Processing state**: spinner + "Scanning shelf..." while the
   `POST /api/scan/` request is in flight. This can legitimately take
   several seconds (real latency was ~30s+ for a 30-region photo even
   parallelized) — don't let the UI look frozen or timeout too
   aggressively.
3. **Results screen**: show what happened — auto-added count, how many
   need review, how many were unreadable/errored. Button into the
   review queue if anything needs it.
4. **Review screen**: one book at a time or a scrollable list, each
   with its detected text, top candidate(s), and Confirm/Correct/
   Discard actions per the rules above.
5. **Library screen**: `GET /api/library/`, render as a simple list
   (title, author, added date). Pull-to-refresh is a nice-to-have, not
   required.

## Before you start

Run the backend (`cd backend && .venv\Scripts\python manage.py
runserver 0.0.0.0:8000` — venv already exists and has deps installed,
weights already downloaded, `.env` already has the OpenRouter key) and
confirm `/api/scan/` and `/api/library/` respond before touching any
mobile code, so you're not debugging two layers at once.

## Not in scope for this chunk

- Retry-on-network-failure beyond a manual retry button.
- Any catalog/matcher/detector changes — those are done and out of
  scope unless you find an actual bug while building the UI (if so,
  stop and report it rather than silently patching pipeline code from
  the mobile chunk).
- README/AI_USAGE.md updates — that's chunk 6.

Budget: ~1.5h per the original chunk plan. Chunks 1–4 combined took
roughly 4h real time against a ~7h cumulative budget (chunk 3.5 VLM
validation was necessary unplanned work, already absorbed). Some slack
remains but don't pad this chunk — ship the four screens and stop.
