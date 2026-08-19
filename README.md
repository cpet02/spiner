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

Run the tests (matcher + pipeline failure-mode coverage):

```bash
python -m pytest -q
```

### Mobile

```bash
cd mobile
npm install
```

Edit `API_BASE` at the top of `App.js` to your machine's LAN IP (a phone
running Expo Go can't reach `localhost` — that resolves to the phone
itself). Find your IP with `ipconfig` (Windows) or `ifconfig`/`ip addr`
(macOS/Linux).

Then either:

- **Browser, no phone needed:** `npx expo start --web` — opens all four
  screens in a normal browser tab. This is the easiest way to run it on
  a machine that isn't yours.
- **Phone via Expo Go:** `npx expo start`, scan the QR code. Phone and
  dev machine must be on the same network.
- **Simulator:** `npx expo start`, press `i` (iOS, needs Xcode) or `a`
  (Android, needs Android Studio).

## Architecture

```
Expo app (capture/processing/results/review/library)
        │  multipart image upload
        ▼
POST /api/scan/  (Django, DRF)
        │
        ▼
detector.py — LOCAL, CPU, free
  OpenCV EAST text detector, pretrained, off-the-shelf weights.
  Finds *where* text blobs are on the shelf photo, tiled 320x320 with
  25% overlap (EAST's fixed input size would shrink spine letters to
  1-2px on a full-resolution photo otherwise), boxes merged across
  tile and shelf-row boundaries.
        │  crops of candidate spine regions
        ▼
ai_client.py / pipeline.py — HOSTED, paid, per-call
  OpenRouter → anthropic/claude-sonnet-4.5 (VLM). Reads *what* the
  text says: title + author, as JSON. Only runs on the small crops
  the free local stage already found, not the whole photo.
        │  {title, author} per region
        ▼
matcher.py — LOCAL, free
  rapidfuzz token_sort_ratio against catalog.csv, title and author
  scored separately and weighted (65/35), banded into auto / review /
  none. See "Matching" below.
        │
        ▼
JSON response → app auto-adds "auto" band, queues everything else for
review → confirmed entries POST to /api/library/ → SQLite
```

**Why this split.** Detection doesn't need to understand anything —
just "is there a text blob here" — so it runs locally on every pixel of
every photo for free. Reading is the part that needs real
vision-language understanding (font, angle, partial occlusion), so
that's the only part paid per-call for, and it only ever sees the small
crops the free stage already isolated.

## Matching against a messy catalog

Exact string matching fails immediately against a catalog built to have
duplicate editions, US/UK title variants, homonym titles, an omnibus
next to its own volumes, substring titles, and author names in multiple
forms. The matcher (`vision/matcher.py`) instead:

- Flattens each entry's `title` + `alt_titles` and `author` +
  `author_alt_forms` into unordered pools — no primary-vs-alt priority,
  best match across any known form wins (so "Rowling, J. K." matches
  "J.K. Rowling").
- Scores title and author independently with `rapidfuzz.token_sort_ratio`
  (word-order-insensitive, typo-tolerant), then combines them
  `0.65 * title_score + 0.35 * author_score` — title carries more
  weight since the VLM often can't read a spine's author line at all,
  but author still disambiguates same-title collisions.
- `WRatio` was tried first and rejected: its partial/substring blending
  produced false positives on short common words shared across
  unrelated titles. `token_sort_ratio` is stricter, at the cost of
  some recall — a deliberate trade toward fewer wrong auto-adds.
- Bands the combined score: **≥90 auto-confirm**, **60–89 human
  review**, **<60 no match** (`vision/matcher.py:17-18`).

## Local vs. hosted routing, measured

| Stage | Where | Cost |
|---|---|---|
| Region detection (EAST) | Local, CPU | $0 |
| Spine read | Hosted (OpenRouter, `anthropic/claude-sonnet-4.5`) | ~$0.00129/call |
| Catalog match | Local, CPU | $0 |

- **Cost**, measured from actual OpenRouter billing during development:
  $0.21 spent over 163 VLM calls = **~$0.00129/call**. A typical
  20-30-region photo costs roughly **$0.03-0.04** end to end.
- **Latency**, measured on real test photos (`backend/vision/test_photos/`):
  a 31-region photo went from **107s sequential → 32s** after
  parallelizing VLM calls with an 8-worker thread pool (independent
  I/O-bound HTTP calls have no reason to be sequential). A typical
  photo in the 12-15 region range lands in the **4-10s** range end to
  end (detect + N/8 concurrent VLM round-trips + match).

## Catalog

`catalog.csv`, 122 entries, generated with an LLM from a list of
required messiness traps and then spot-checked and extended by hand
(see `AI_USAGE.md` for the exact split). It deliberately contains:

- two editions of the same book as separate rows (e.g. `1984` ×2, `Pride
  and Prejudice` ×2)
- the same book under two titles — `Harry Potter and the Philosopher's
  Stone` (UK) / `...Sorcerer's Stone` (US), `And Then There Were None` /
  `Ten Little Indians`
- two genuinely different books sharing a title (`Emma` — Austen vs.
  McCall Smith; `The Circle` — Eggers vs. Minier)
- an omnibus (`The Lord of the Rings`) alongside its individual volumes
  (`The Fellowship of the Ring`, etc.)
- author names in more than one form via `author_alt_forms`
  (`J.R.R. Tolkien` / `Tolkien, J. R. R.`)
- weighted toward books people actually own (mainstream fiction/fantasy
  classics), not obscure titles, per the spec — the point is that a
  demo shelf should actually produce matches.

## Human in the loop

Only `band: "auto"` (score ≥90) is added without a human touching it,
and it's still shown on the results screen so the user sees what
happened — it's silent to the *matcher*, not to the *interface*.
Everything else — `review` band, `none` band, `unreadable` reads, and
pipeline `error`s — lands in a review queue the user must act on one
book at a time: **Confirm** (accept the top match), **Correct** (pick
one of the up-to-3 returned candidates instead), or **Discard** (drop
it, never persisted). Nothing in that queue reaches `/api/library/`
without one of those three explicit actions.

## Graceful failure

Handled explicitly, verified against real inputs, not assumed:

- **Zero detections** (`regions_found: 0`) — explicit empty state in
  the results screen, not a blank list.
- **Detector failure** (`detection_error` present) — shown to the user
  instead of crashing.
- **VLM call failure / malformed JSON** — `pipeline.py` wraps every VLM
  call so these become a `status: "error"` book entry with a `reason`,
  never an uncaught exception; the review screen surfaces the reason
  and offers Discard.
- **Unreadable spine** — VLM is explicitly prompted not to guess a
  plausible-sounding title when unsure; comes back as
  `status: "unreadable"` and goes to the same review queue, shown as
  "couldn't read this one."
- **Network/timeout failure calling `/api/scan/` itself** (not a
  pipeline-internal error — an actual failed fetch) — results screen
  shows the error with a Retry button instead of hanging on a spinner.

## Key decisions and tradeoffs

- **Precision over recall on the VLM read step.** After the first
  real end-to-end run came back with the VLM confidently inventing
  plausible-but-wrong titles (2/8 correct against a known-good
  spot-check set), the prompt was rewritten to explicitly forbid
  guessing, and crops under 200px on the short side are upscaled
  before sending. Result: confident-wrong reads dropped, honest
  `unreadable` results went up, and *measured accuracy on the
  known-good set stayed the same* — this is a precision/recall trade,
  not a net accuracy win. I judged fewer wrong auto-adds worth more
  than fewer answers for a catalog-matching product, since a wrong
  auto-add is a silent failure and an `unreadable` is not (full
  writeup: `DEV_LOG_chunk3.5_vlm_test.md`).
- **Accuracy tracks spine typography, not photo resolution.** An 8x
  higher-resolution reshoot of the same shelf barely improved read
  accuracy on thin serif/gilt-lettered spines; a shelf with bold
  sans-serif spines did clearly better, including one perfect
  end-to-end catalog match. This means the read step's accuracy
  ceiling isn't fixable by asking users for better photos — it needs a
  different model or a retry strategy, neither attempted this round.
- **No navigation library.** Four screens, one `App.js`, plain
  `useState` driving which screen renders. A router is unnecessary
  complexity for a linear capture → review → library flow at this
  scale.
- **Persistence is backend-side**, not on-device storage. Confirming
  an item POSTs to `/api/library/`; the library screen is a GET
  against the same endpoint. No auth, single implicit user — matches
  the spec's explicit non-scope.
- **Cost/latency constants are measured, not estimated**, and
  documented in-line in `pipeline.py` with the exact numbers and how
  they were obtained, so they're falsifiable if the model changes.

## What's unfinished, and what I'd do with another day

- **Detection recall is the biggest open gap.** EAST finds roughly
  14 of ~50 visible spines on a typical dense shelf photo (word-level
  text detection merged into spine-level boxes loses recall on tightly
  packed shelves). Untouched this round — accepted as a known
  limitation rather than chased, since it's a detector-swap problem,
  not a tuning one. With another day: try a denser tiling stride, or a
  spine-segmentation-specific model if one exists off-the-shelf.
- **Read accuracy on small/serif spine text (~50-55% "ok" rate)** is
  the second gap — see tradeoffs above. Next cheapest lever untried: a
  retry pass at further zoom specifically on `unreadable` crops before
  giving up, since detection already located the region for free.
- **No formal precision/recall harness** — accuracy claims here come
  from visual spot-checks against a known-good set on 4 real test
  photos, not a scored eval set. Worth building before doing any more
  blind prompt/crop tuning.
- **Web export was added late** (react-dom + react-native-web) purely
  so this can be graded without owning a specific phone — not
  exercised as thoroughly as the Expo Go path.
- Pull-to-refresh on the library screen exists; nothing else beyond
  the spec's four screens was attempted (no search, no delete, no
  edit) — explicitly out of scope for an 8-hour budget.

## AI usage

See `AI_USAGE.md` for a detailed, honest breakdown of what was
delegated to Claude Code vs. decided by hand.
