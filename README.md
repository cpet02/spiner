# Shelfie — Bookshelf → Library

Take-home project: a photo of a bookshelf becomes a structured personal
library. Expo (React Native) mobile app → Django REST backend → local
CPU detector → hosted VLM → fuzzy catalog match → human review → SQLite.

## Setup and run (from a clean clone)

### Backend

```bash
cd backend
python -m venv .venv
.venv/Scripts/activate        # macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
python scripts/download_weights.py   # pulls EAST weights (~96MB), not committed
cp .env.example .env          # add OPENROUTER_API_KEY, keep AI_MODEL as-is or change it
python manage.py migrate
python manage.py runserver 0.0.0.0:8000
```

`catalog.csv` is loaded once and cached in memory (`vision/pipeline.py`'s
`_get_catalog()`). Django's autoreloader only watches `.py` files, so
editing the catalog alone will *not* pick up while the server is
running -- restart it after any catalog change.

### Mobile

```bash
cd mobile
npm install
```

Edit `API_BASE` at the top of `App.js` to your machine's LAN IP (a phone
running Expo Go can't reach `localhost` — that resolves to the phone
itself).

- **Browser, no phone needed:** `npx expo start --web` — opens all five
  screens in a normal browser tab.
- **Phone via Expo Go:** `npx expo start`, scan the QR code. Phone and
  dev machine must be on the same network.
- **Simulator:** `npx expo start`, press `i` (iOS) or `a` (Android).

## Tests

```bash
cd backend
python -m pytest -q
```

| File | What it covers |
|---|---|
| [`backend/vision/test_matcher.py`](backend/vision/test_matcher.py) | Matching logic against real catalog ambiguity: duplicate editions, regional title variants, homonym titles disambiguated by author, omnibus vs. individual volume, alternate author-name forms, substring vs. series titles, noisy-OCR digit confusion (`451` vs `45i`), title-only reads with no author, and the no-match case. |
| [`backend/vision/test_pipeline.py`](backend/vision/test_pipeline.py) | Every graceful-failure path: blank/empty input to detection, malformed VLM JSON (fenced and unfenced), a failed VLM call, an empty-but-well-formed VLM response, and a full good-input run through the whole pipeline. |

16 tests total, all pass from a clean clone. Not measuring coverage —
per the spec, these exist to prove the matching and failure-handling
logic actually does what the README claims, not to hit a percentage.

## Architecture

```
Expo app (mobile/App.js, 5-screen state machine, no router)
        │  multipart image upload
        ▼
POST /api/scan/  (Django, DRF)
        │
        ▼
detector.py — LOCAL, CPU, free
  OpenCV EAST text detector, pretrained, off-the-shelf weights.
  Finds *where* text blobs are on the shelf photo, tiled 320x320 with
  25% overlap, boxes merged across tile boundaries and unioned into
  spine-level regions by x/y proximity.
        │  crops of candidate spine regions
        ▼
ai_client.py / pipeline.py — HOSTED, paid, per-call
  OpenRouter → anthropic/claude-sonnet-4.5, temperature=0. Reads *what*
  the text says: title + author, as JSON. Only runs on the small crops
  the free local stage already found, not the whole photo.
        │  {title, author} per region
        ▼
matcher.py — LOCAL, free
  rapidfuzz token_sort_ratio against catalog.csv, title and author
  scored separately and weighted (65/35), banded into auto / review /
  none.
        │
        ▼
JSON response → app auto-adds "auto" band, queues everything else for
review → confirmed entries POST to /api/library/ → SQLite
```

**Why this split.** Detection doesn't need to understand anything —
just "is there a text blob here" — so it runs locally on every pixel of
every photo for free. Reading is the part that needs real
vision-language understanding, so that's the only part paid per-call
for, and it only ever sees the small crops the free stage already
isolated.

## Matching against a messy catalog

Exact string matching fails immediately against a catalog built to have
duplicate editions, US/UK title variants, homonym titles, an omnibus
next to its own volumes, substring titles, and author names in multiple
forms. The matcher (`vision/matcher.py`) instead:

- Flattens each entry's `title` + `alt_titles` and `author` +
  `author_alt_forms` into unordered pools — best match across any known
  form wins (so "Rowling, J. K." matches "J.K. Rowling").
- Scores title and author independently with `rapidfuzz.token_sort_ratio`,
  then combines them `0.65 * title_score + 0.35 * author_score` — title
  carries more weight since the VLM often can't read a spine's author
  line at all, but author still disambiguates same-title collisions.
- `WRatio` was tried first and rejected: its partial/substring blending
  produced false positives on short common words shared across
  unrelated titles. `token_sort_ratio` is stricter, at the cost of
  some recall — deliberate, toward fewer wrong auto-adds.
- Bands the combined score: **≥90 auto-confirm**, **60–89 human
  review**, **<60 no match**.
- Real near-miss from live testing: a spine read as "The Powder Mage
  Trilogy" (a real book, not in the catalog) fuzzy-matched "The Power
  of Habit" at 63.4% — landed in review, not auto-added, and not
  silently dropped either. Exactly the kind of ambiguity the bands
  exist to catch.

## Local vs. hosted routing, measured

| Stage | Where | Cost |
|---|---|---|
| Region detection (EAST) | Local, CPU | $0 |
| Spine read | Hosted (OpenRouter, `anthropic/claude-sonnet-4.5`) | ~$0.00129/call |
| Catalog match | Local, CPU | $0 |

- **Cost**, measured from actual OpenRouter billing during development:
  $0.21 over 163 calls = **~$0.00129/call**. A 27-region photo (real
  measurement, `bookshelf_04.jpg`) cost **$0.0348** end to end.
- **Latency**: parallelizing VLM calls (8-worker thread pool — these
  are independent I/O-bound HTTP calls, no reason to run sequentially)
  took the slowest tested photo from **107s → 32s**. A fresh timed run
  of the same 27-region photo: **33.4s** end to end.
- **VLM model choice was tested, not assumed.** A/B'd
  `anthropic/claude-sonnet-4.5` against `google/gemini-2.5-flash` on
  the same 27 crops from one photo: Claude returned a usable title on
  23/27, Gemini on 14/27, and Gemini repeatedly misplaced text into the
  wrong JSON field (author fragments in `title`, title fragments in
  `author`) — a schema-reliability problem, not just a raw-OCR one,
  and worse for a matcher that trusts `title` specifically. Kept Claude.

## Catalog

`catalog.csv`, 189 entries. Started from 122 LLM-generated entries
covering every required messiness trap, then expanded live: real test
photos this session kept producing correct VLM reads with zero catalog
match (Wheel of Time volumes, Joe Abercrombie, Murakami's `1Q84`, more
Sanderson) — the spec sets "at least 100" as a floor, not a ceiling,
and explicitly asks for a catalog "weighted towards books people
actually own." The added batch kept adding trap variety, not just
clean entries:

- duplicate editions as separate rows (`1984` ×2, `Pride and Prejudice` ×2)
- same book under two titles — UK/US Harry Potter and Christie, plus
  `Northern Lights` / `The Golden Compass` (Pullman)
- two different, both-real books sharing a title — `Emma` (Austen vs.
  McCall Smith), `The Circle` (Eggers vs. Minier), `The Passenger`
  (McCarthy vs. Lutz)
- an omnibus (`The Lord of the Rings`, `The Wheel of Time`, `Mistborn
  Trilogy`, `The First Law Trilogy`) beside its individual volumes
- substring title: `Life` (Keith Richards) is a literal substring of
  the existing `Life of Pi`
- noisy-OCR near-duplicate: `1Q84` beside `1984` — Q/9 is an easy
  misread on a serif spine font
- author names in multiple forms via `author_alt_forms`
  (`J.R.R. Tolkien` / `Tolkien, J. R. R.`, `Ishiguro, Kazuo`, etc.)

## Human in the loop

Only `band: "auto"` (≥90) is added without a human touching it, and
it's still shown on the results screen so the user sees what happened —
silent to the *matcher*, not to the *interface*. Everything else lands
in a review queue, one book at a time, each with a cropped thumbnail of
the actual spine (cut from the original photo client-side using the
`box` coordinates already in the response — no backend change needed)
so the user has something to visually check the read against, not just
text. Per item:

- **Confirm** — only offered when `band === "review"` (60–89). A
  `"none"`-band top match is largely noise; offering a one-tap Confirm
  for it invited accidental false-accepts during testing (traced a run
  of near-duplicate library entries directly to this before the fix).
- **Correct** — pick one of the up-to-3 returned candidates instead.
- **Discard** — drop it, never POSTed to `/api/library/`.

Nothing in the queue reaches the library without one of those three
explicit actions.

## Graceful failure

- **Zero detections** (`regions_found: 0`) — explicit empty state, not
  a blank list.
- **Detector failure** (`detection_error` present) — shown to the user.
- **VLM call failure / malformed JSON** — wrapped so these become a
  `status: "error"` book with a `reason`, never an uncaught exception.
- **Unreadable spine** — VLM is explicitly prompted not to guess; comes
  back as `status: "unreadable"`, shown as "couldn't read this one."
- **Network/timeout failure calling `/api/scan/` itself** — Retry
  button, not a frozen spinner.

## Key decisions and tradeoffs

- **Precision over recall on the VLM read step, revisited twice.**
  First pass (chunk 3.5): the prompt was rewritten to forbid guessing
  after the VLM confidently invented plausible-but-wrong titles —
  fewer wrong auto-adds, more honest `unreadable`s, flat accuracy on
  the known-good set. Second pass (this session, live-tested): that
  same "don't guess" instruction had a side effect of *truncating*
  multi-word titles the model was only partially confident about
  (`"Greek Plays"` → `"Greek"`). Fixed by adding an explicit
  "don't truncate a partial-confidence read" instruction alongside the
  original "don't invent text you can't read at all" guardrail, plus
  `temperature=0` for determinism (the same photo previously gave a
  different auto-add count on repeat runs). Re-tested: unreadable rate
  dropped from ~50% to ~15% on the same photo, no cost change.
- **Confidence bands gate UI actions, not just matcher output.** Found
  live: the review screen originally showed a Confirm button for *any*
  match regardless of band, including `"none"`-band matches under 60%
  — a demo-visible bug that produced repeated near-duplicate library
  entries. Confirm is now band-gated; `"none"`-band items only offer
  Correct or Discard.
- **`ALLOWED_HOSTS = ['*']`, deliberately.** Caught live: the default
  (`[]`, which only permits `localhost` under `DEBUG=True`) rejected
  every request from a phone's LAN IP or a browser preview with a 400,
  before the request ever reached the pipeline. Widened since this
  never deploys anywhere (spec: deployment not required).
- **Web image upload needs a real `Blob`, not React Native's native
  file-object shape.** `expo-image-picker` returns a `blob:` URI on
  web; the `{uri, name, type}` object FormData shape that works for
  native Expo Go produces no actual file part in a browser's
  `FormData`. Branch on `Platform.OS === 'web'` and fetch the blob URI
  into a real `Blob` first.
- **No navigation library.** Five screens, one `App.js`, plain
  `useState`. A router is unneeded complexity for a linear flow at
  this scale.
- **Persistence is backend-side**, not on-device storage — matches the
  spec's explicit non-scope on auth/multi-user.
- **VLM model choice was A/B-tested, not just assumed** — see
  "Local vs. hosted routing" above.

## Scope cuts

Deliberate, not accidental — each one traded against the ~8-hour budget:

- **No auth, no multi-user.** Single implicit user, backend-persisted
  library. Spec explicitly excludes auth from grading; building it
  would've bought nothing toward the four things actually being checked.
- **No free-text catalog search for corrections.** The review screen's
  Correct action only offers the matcher's own top-3 candidates, not a
  search box. A free-text search is a second, unrelated matching UI —
  the candidates list already demonstrates the fuzzy-matching logic
  the spec asks for; a search box would duplicate that without adding
  signal.
- **No navigation library.** Five screens, one `useState` state
  machine. A router earns its cost on branching or deep-linked flows;
  this is one linear path, so `react-navigation` would be pure overhead.
- **Left the EAST detector untouched despite a known box-precision
  issue**, found live during testing. Fixing it meant redoing the
  chunk-3.5 validation pass from scratch on deadline day for an
  unproven gain — and the spec explicitly doesn't grade raw accuracy
  as long as it's measured and handled, which it is. Documented instead
  of chased (see "What's unfinished" below).
- **No formal precision/recall harness.** Accuracy claims are grounded
  in real spot-checks against real test photos (not vibes), but not a
  scored eval set — building one is real engineering time that doesn't
  change any of the four things being checked.
- **No automatic retry on network failure**, manual Retry button only.
  Automatic retry/backoff is a reliability feature for a service under
  real traffic; this runs on one dev machine for one demo.
- **Deployment not attempted** — explicitly out of scope per spec
  ("we must be able to run it on our own machine by following your
  README").

## What's unfinished, and what I'd do with another day

The single biggest open gap is **detection recall and box precision**:
EAST finds roughly 14 of ~50 visible spines on a dense shelf, and the
merge heuristic sometimes stitches only a fragment of a spine's text
into one region — visible directly now via the review screen's crop
thumbnails (see "Scope cuts" above for why this was documented rather
than chased). With another day, in cheapest-first order:

1. Retry pass on `unreadable` crops at further zoom before giving up —
   detection already found the region, so this is a few extra VLM
   calls, not new detector work.
2. A real precision/recall harness against a labeled photo set, to
   replace live spot-checks with numbers that survive scrutiny.
3. Loosen the merge heuristic's y-gap tolerance to catch more
   full-spine regions, re-validated against the existing test photos
   before trusting it.
4. A different local detector (CRAFT, PaddleOCR's DB) if (1)-(3) hit a
   ceiling — the biggest lever, also the most expensive to validate.

## AI usage

See `AI_USAGE.md` for a detailed, honest breakdown of what was
delegated to Claude Code vs. decided by hand.
