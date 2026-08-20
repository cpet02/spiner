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

**Why this split.** Detection needs no understanding — just "is there
text here" — so it's free and runs on every pixel of every photo.
Reading needs real vision-language understanding, so it's the only
paid stage, and it only ever sees the small crops detection already
found.

## Matching against a messy catalog

Exact string matching fails against a catalog built with duplicate
editions, US/UK title variants, homonym titles, an omnibus next to its
own volumes, substring titles, and author names in multiple forms.
`vision/matcher.py`:

- Flattens each entry's `title`+`alt_titles` and `author`+
  `author_alt_forms` into pools — best match across any known form wins
  (so "Rowling, J. K." matches "J.K. Rowling").
- Scores title and author independently (`rapidfuzz.token_sort_ratio`),
  combines `0.65 * title_score + 0.35 * author_score` — title weighted
  higher since the VLM often can't read the author line at all, but
  author still breaks same-title ties.
- Chose `token_sort_ratio` over `WRatio`: WRatio's partial/substring
  blending false-positived on short common words across unrelated
  titles. Stricter, at some recall cost — deliberate, favors fewer
  wrong auto-adds.
- Bands the combined score: **≥90 auto**, **60–89 review**, **<60 none**.
- Real near-miss from live testing: "The Powder Mage Trilogy" (a real
  book, not in the catalog) matched "The Power of Habit" at 63.4% —
  review, not auto-added, not dropped either.

## Local vs. hosted routing, measured

| Stage | Where | Cost |
|---|---|---|
| Region detection (EAST) | Local, CPU | $0 |
| Spine read | Hosted (OpenRouter, `anthropic/claude-sonnet-4.5`) | ~$0.00142/call |
| Catalog match | Local, CPU | $0 |

- **Cost**, measured from actual OpenRouter billing: $0.94 over 664
  calls across development and testing = **~$0.00142/call**. A
  27-region photo (`bookshelf_04.jpg`) cost **$0.0348** end to end.
- **Latency**: parallelizing VLM calls (8-worker thread pool — these
  are independent I/O-bound HTTP calls, no reason to run sequentially)
  took the slowest tested photo (27 regions) from **107s → 33.4s**
  end to end — the whole shelf, not per book.
- **VLM model choice was tested, not assumed.** A/B'd
  `anthropic/claude-sonnet-4.5` against `google/gemini-2.5-flash` on
  the same 27 crops from one photo: Claude returned a usable title on
  23/27, Gemini on 14/27, and Gemini repeatedly misplaced text into the
  wrong JSON field (author fragments in `title`, title fragments in
  `author`) — a schema-reliability problem, not just a raw-OCR one,
  and worse for a matcher that trusts `title` specifically. Kept Claude.

## Catalog

`catalog.csv`, 189 entries, LLM-generated then expanded from real test
photos that produced correct VLM reads with zero catalog match. Traps
included:

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

## Bugs found by a targeted code-review pass

After the app was working end-to-end, a deep correctness audit (5
parallel reviews, one per major file) found real bugs invisible from
the diffs or the passing test suite — all fixed and verified live:

- **Matcher was case-sensitive.** ALL-CAPS spine reads scored near-zero
  against correctly-cased catalog entries. Fixed with `default_process`.
- **`NMSBoxes` fed the wrong box format.** Expects `(x,y,w,h)`, got
  corners — inflated phantom rects silently dropped real detections,
  worse deeper into the photo. Likely explains most of the recall gap.
- **Missing author scored *higher* than a correct one.** No author was
  a scoring no-op, so any exact title auto-confirmed with no tiebreak.
  Now unscored honestly, plus a tie-check before auto-confirming.
- **Three exception-escape paths in "never raises."** Null content,
  list-typed title, and stray-brace JSON parsing could each crash the
  whole request instead of failing one book. All guarded now.
- **Literal string `"null"` accepted as a real title.** The prompt's
  own schema example showed it in quotes, inviting exactly that. Sentinel-checked now.
- **Mobile swallowed library-save failures.** `postToLibrary()` never
  checked `res.ok`, so a failed save looked identical to a successful one.

A final defense-readiness cleanup then removed what that audit turned
up but didn't rise to "bug": a dead `call_text_model()` function with
no callers, a catalog `isbn` field that was parsed but never wired
through the pipeline into the app, a docstring still describing a
scoring function (`WRatio`) the code no longer used, an inert
`MAILERS` setting (not a real Django key, `EMAIL_BACKEND` is), and an
unused `expo-status-bar` dependency.

## Key decisions and tradeoffs

- **Precision over recall on VLM reads, revisited twice.** "Don't
  guess" cut hallucinations but caused truncated titles (`"Greek
  Plays"` → `"Greek"`); added "don't truncate" plus `temperature=0`.
  Unreadable rate dropped ~50%→~15%.
- **Confidence bands gate UI actions, not just matcher output.**
  Confirm was showable on any band, including `"none"` — caused
  duplicate library entries live. Now band-gated.
- **`ALLOWED_HOSTS = ['*']`, deliberately.** Default rejected every
  non-localhost request with a 400 before the pipeline ever ran;
  widened since deployment is out of scope.
- **Web upload needs a real `Blob`.** `expo-image-picker`'s `blob:`
  URI doesn't work with native Expo's FormData object shape; fetch it
  into a real `Blob` on web.
- **Persistence is backend-side, not on-device.** Matches the spec's
  explicit non-scope on auth/multi-user.
- **VLM model choice A/B-tested, not assumed** — see routing section above.

## Scope cuts

Deliberate, not accidental — each traded against the ~8-hour budget:

- **No auth, no multi-user.** Excluded from grading per spec; buys
  nothing toward the four things actually checked.
- **No free-text catalog search.** The candidates list already
  demonstrates fuzzy matching; a search box duplicates that without
  adding signal.
- **No navigation library.** One linear five-screen flow; a router is
  pure overhead at this scale.
- **Left EAST's box-precision issue unfixed.** Re-validating a detector
  change on deadline day risked more than an unproven accuracy gain.
- **No formal precision/recall harness.** Real spot-checks ground the
  claims; a scored eval set doesn't move any of the four grading items.
- **No automatic retry.** Manual Retry button; this runs on one dev
  machine for a demo, not real traffic.
- **Deployment not attempted** — explicitly out of scope per spec.

## What's unfinished, and what I'd do with another day

Extends the scope cuts above. Detection recall (~14/50 visible spines
on a dense shelf) hasn't been re-measured since the NMS fix, so that's
the honest first step, cheapest-first from there: retry `unreadable`
crops at further zoom, build a real precision/recall harness, loosen
the merge heuristic's y-gap tolerance, and only reach for a different
local detector (CRAFT, PaddleOCR's DB) if none of that closes the gap.

## AI usage

See `AI_USAGE.md` for a detailed, honest breakdown of what was
delegated to Claude Code vs. decided by hand.
