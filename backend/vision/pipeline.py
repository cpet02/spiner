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
    "Identify the book title and author printed on the spine(s). "
    "Respond with ONLY a JSON object, no prose, no markdown fences: "
    '{"title": "<title or null>", "author": "<author or null>"}. '
    "If you cannot confidently read a title, set title to null."
)

# Rough per-1K-token pricing for a mid-tier hosted VLM via OpenRouter, used
# for the estimated-cost-per-image number in the README. Deliberately a
# constant here (not fetched live) -- see README for the exact model/rate
# used at measurement time.
EST_COST_PER_CALL_USD = 0.003


def _parse_vlm_json(raw: str) -> dict:
    """VLMs occasionally wrap JSON in ```json fences or add stray prose
    even when told not to. Strip the common cases before parsing."""
    text = raw.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:]
    text = text.strip()
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1 or end < start:
        raise ValueError(f"No JSON object found in VLM response: {raw[:200]!r}")
    return json.loads(text[start:end + 1])


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

    try:
        parsed = _parse_vlm_json(raw)
    except (ValueError, json.JSONDecodeError) as e:
        logger.warning("VLM returned unparsable JSON: %s", e)
        return {"status": "error", "reason": "malformed_json", "detail": str(e), "raw": raw}

    title = parsed.get("title") or None
    author = parsed.get("author") or None
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
    except detector.DetectorError as e:
        logger.error("Detection failed: %s", e)
        return {"books": [], "detection_error": str(e), "regions_found": 0}

    if not regions:
        return {"books": [], "regions_found": 0}

    books = []
    vlm_calls = 0
    for region in regions:
        read = read_spine(region["crop"])

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
                "score": round(top.score, 1),
            } if top else None,
            "candidates": [
                {"title": c.entry.title, "author": c.entry.author, "score": round(c.score, 1)}
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
