"""
Ties local detection -> hosted VLM read -> catalog matcher together.

Split we're defending at demo:
- LOCAL (free, CPU, detector.py): find *where* text is on the shelf photo.
  Cheap, runs on every pixel of every photo, doesn't need to understand
  anything -- just "is there a text blob here".
- HOSTED (paid, VLM, this file): read *what* the text says. This is the
  part that needs real language/vision understanding (font, angle, partial
  occlusion, multiple languages), so it's the only part we pay per-call for,
  and we only call it on the small crops the local stage already found.

Every VLM call is wrapped so a timeout, a non-JSON response, or a
malformed response never raises out of run_pipeline -- it becomes a
per-book result with status="error" that the frontend can show and the
user can retry, same as a low-confidence match.
"""
import json
import logging
import os
from concurrent.futures import ThreadPoolExecutor
import time

try:  # package import (Django runtime: `from vision import pipeline`)
    from . import detector, matcher
    from .ai_client import call_vision_model, AIClientError
except ImportError:  # flat import (tests run with cwd=vision/, matching test_matcher.py)
    import detector
    import matcher
    from ai_client import call_vision_model, AIClientError

logger = logging.getLogger("vision.pipeline")

_catalog = None


def _catalog_path():
    """Resolve catalog.csv whether we're run as the Django server (cwd=
    backend/) or as the test suite (cwd=repo root, matching test_matcher.py's
    convention). Repo-root-relative path (from this file) wins if present,
    otherwise fall back to a plain cwd-relative lookup."""
    from_file = os.path.join(os.path.dirname(__file__), "..", "..", "catalog.csv")
    if os.path.exists(from_file):
        return from_file
    return "catalog.csv"


def _get_catalog():
    global _catalog
    if _catalog is None:
        _catalog = matcher.load_catalog(_catalog_path())
    return _catalog

READ_PROMPT = (
    "This image is a cropped photo of one or more book spines. "
    "The text may be printed horizontally, or rotated 90 degrees "
    "(running top-to-bottom or bottom-to-top along a narrow spine) -- "
    "rotate the image mentally as needed to read it. "
    "Identify the book title and author printed on the spine(s). "
    "Titles are often two or more words, sometimes on separate lines or "
    "in different font sizes on the same spine -- read the COMPLETE "
    "title, not just the first word or line you're confident about. "
    "Respond with ONLY a JSON object, no prose, no markdown fences: "
    '{"title": <title as a string, or the JSON literal null>, '
    '"author": <author as a string, or the JSON literal null>}. '
    "If you cannot confidently read a title at all, set title to the "
    "JSON literal null (not the text \"null\") -- "
    "do not guess or invent a plausible-sounding title. But if you can "
    "read part of the title confidently, don't truncate it -- include "
    "every word you can actually read, in order."
)

# Measured from actual OpenRouter billing during pipeline development/testing:
# $0.21 spent over 163 VLM calls (anthropic/claude-sonnet-4.5) = ~$0.00129/call.
# Deliberately a constant here (not fetched live) -- re-measure from the
# OpenRouter dashboard if the model changes.
EST_COST_PER_CALL_USD = 0.00129

# VLM calls are one blocking HTTP request each; the reads are independent of
# each other, so we fire them concurrently instead of one-at-a-time. This is
# the single biggest lever on wall-clock latency per photo -- worth far more
# than any per-call optimization.
MAX_CONCURRENT_VLM_CALLS = 8


# Placeholder strings a VLM sometimes emits instead of a real null --
# READ_PROMPT's schema example shows the null placeholder INSIDE quotes
# ({"title": "<title or null>"}), which invites a literal string "null"
# back rather than JSON null. Treated as "didn't read a title", same as
# real null -- otherwise these silently look like confident matches and
# get fuzzy-matched against the whole catalog.
_NULL_TITLE_SENTINELS = {"null", "none", "n/a", "na", "unknown", ""}


def _parse_vlm_json(raw: str) -> dict:
    """VLMs occasionally wrap JSON in ```json fences or add stray prose
    even when told not to. Strip the common cases before parsing."""
    text = raw.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:]
    text = text.strip()
    start = text.find("{")
    if start == -1:
        raise ValueError(f"No JSON object found in VLM response: {raw[:200]!r}")
    # Decode from the first '{' and let the JSON decoder find its own
    # matching close brace, instead of text.rfind("}") -- rfind grabs the
    # LAST '}' in the string, so any trailing prose containing a stray
    # brace (e.g. a model apologizing "... {if unsure}") silently expands
    # the slice past the real object and corrupts an otherwise-good parse
    # into a malformed_json error.
    return json.JSONDecoder().raw_decode(text[start:])[0]


def read_spine(crop_bytes: bytes) -> dict:
    """Call the VLM on one crop. Never raises -- always returns a dict with
    a "status" key so the caller can handle every outcome uniformly."""
    t0 = time.monotonic()
    try:
        raw = call_vision_model(READ_PROMPT, crop_bytes, mime_type="image/jpeg")
    except AIClientError as e:
        logger.warning("VLM call failed: %s", e)
        return {"status": "error", "reason": "vlm_call_failed", "detail": str(e)}
    except Exception as e:  # network/timeout/etc from requests
        logger.warning("VLM call raised unexpectedly: %s", e)
        return {"status": "error", "reason": "vlm_call_failed", "detail": str(e)}
    finally:
        elapsed = time.monotonic() - t0
        logger.info("vlm_call_latency_s=%.2f", elapsed)

    if not isinstance(raw, str):
        # OpenRouter can legitimately return content: null (e.g. a
        # finish_reason of "length" with no completion) -- a valid HTTP
        # 200, not an AIClientError, but not text either. Without this
        # guard the .strip() inside _parse_vlm_json raises AttributeError,
        # which escapes read_spine's except clauses below (they only
        # catch parse errors) and crashes the whole /api/scan/ request.
        logger.warning("VLM returned non-string content: %r", raw)
        return {"status": "error", "reason": "malformed_json", "detail": "empty/non-text VLM response"}

    try:
        parsed = _parse_vlm_json(raw)
    except Exception as e:
        logger.warning("VLM returned unparsable JSON: %s", e)
        return {"status": "error", "reason": "malformed_json", "detail": str(e), "raw": raw}

    title = parsed.get("title")
    author = parsed.get("author")
    # A VLM answering a multi-spine crop can plausibly return a list
    # instead of a string (READ_PROMPT itself says "one or more book
    # spines"); matcher.py's rapidfuzz calls raise TypeError on anything
    # but a string, which would otherwise escape run_pipeline entirely.
    if not isinstance(title, str):
        title = None
    if not isinstance(author, str):
        author = None
    if title is not None and title.strip().lower() in _NULL_TITLE_SENTINELS:
        title = None
    if title is not None:
        title = title.strip()
    if author is not None:
        author = author.strip() or None

    if not title:
        return {"status": "unreadable", "title": None, "author": author}

    return {"status": "ok", "title": title, "author": author, "latency_s": elapsed}


def run_pipeline(image_bytes: bytes) -> dict:
    """Full flow for one uploaded shelf photo. Returns a dict that always
    has a "books" list -- zero detections, all-unreadable spines, and VLM
    failures all resolve to entries in that list rather than an exception,
    so a single bad crop never take down the whole request."""
    t0 = time.monotonic()
    try:
        regions = detector.detect_regions(image_bytes)
    except Exception as e:
        # detector.DetectorError covers the cases detector.py raises
        # deliberately (missing weights, bad image bytes), but OpenCV
        # itself can raise cv2.error from a corrupt/partial weights file
        # or a malformed frame during NMS/encode -- catch broadly here so
        # a detector-internal failure degrades to the same graceful
        # "detection_error" response instead of a raw 500.
        logger.error("Detection failed: %s", e)
        return {"books": [], "detection_error": str(e), "regions_found": 0}

    if not regions:
        return {"books": [], "regions_found": 0}

    with ThreadPoolExecutor(max_workers=MAX_CONCURRENT_VLM_CALLS) as pool:
        reads = list(pool.map(lambda r: read_spine(r["crop"]), regions))

    books = []
    vlm_calls = 0
    for region, read in zip(regions, reads):
        if read["status"] == "error":
            books.append({
                "status": "error",
                "reason": read["reason"],
                "box": region["box"],
                "match": None,
            })
            vlm_calls += 1
            continue

        vlm_calls += 1

        if read["status"] == "unreadable":
            books.append({
                "status": "unreadable",
                "box": region["box"],
                "match": None,
            })
            continue

        candidates = matcher.match(read["title"], read.get("author"), _get_catalog(), top_n=3)
        top = candidates[0] if candidates else None
        books.append({
            "status": "ok",
            "box": region["box"],
            "detected_title": read["title"],
            "detected_author": read.get("author"),
            "band": top.band if top else "none",
            "match": {
                "title": top.entry.title, "author": top.entry.author,
                "isbn": top.entry.isbn, "score": top.score,
            } if top and top.band != "none" else None,
            "candidates": [
                {"title": c.entry.title, "author": c.entry.author,
                 "isbn": c.entry.isbn, "score": round(c.score, 1)}
                for c in candidates
            ],
        })

    elapsed = time.monotonic() - t0
    est_cost = vlm_calls * EST_COST_PER_CALL_USD
    logger.info(
        "pipeline_total_latency_s=%.2f regions=%d vlm_calls=%d est_cost_usd=%.4f",
        elapsed, len(regions), vlm_calls, est_cost,
    )

    return {
        "books": books,
        "regions_found": len(regions),
        "latency_s": round(elapsed, 2),
        "estimated_cost_usd": round(est_cost, 4),
    }
