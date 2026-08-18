"""
Pipeline tests focus on the "graceful failure" requirement: a timeout,
malformed JSON, zero detections, or an unreadable spine must resolve to
a normal book entry with a status, never an exception.
"""
import io
from unittest.mock import patch

import pytest
from PIL import Image, ImageDraw

import pipeline
from ai_client import AIClientError


def _synthetic_shelf_bytes():
    img = Image.new("RGB", (400, 300), "white")
    d = ImageDraw.Draw(img)
    d.rectangle([50, 50, 150, 250], fill="navy")
    d.text((60, 140), "DUNE", fill="white")
    buf = io.BytesIO()
    img.save(buf, format="JPEG")
    return buf.getvalue()


def _blank_bytes():
    buf = io.BytesIO()
    Image.new("RGB", (200, 200), "white").save(buf, format="JPEG")
    return buf.getvalue()


def test_zero_detections_returns_empty_books_not_error():
    result = pipeline.run_pipeline(_blank_bytes())
    assert result["books"] == []
    assert result["regions_found"] == 0


def test_malformed_vlm_json_becomes_error_status_not_exception():
    with patch("pipeline.call_vision_model", return_value="not json at all"):
        result = pipeline.run_pipeline(_synthetic_shelf_bytes())
    assert len(result["books"]) >= 1
    for book in result["books"]:
        assert book["status"] == "error"
        assert book["reason"] == "malformed_json"


def test_vlm_call_failure_becomes_error_status_not_exception():
    with patch("pipeline.call_vision_model", side_effect=AIClientError("timeout")):
        result = pipeline.run_pipeline(_synthetic_shelf_bytes())
    assert len(result["books"]) >= 1
    for book in result["books"]:
        assert book["status"] == "error"
        assert book["reason"] == "vlm_call_failed"


def test_unreadable_spine_null_title_does_not_crash():
    with patch("pipeline.call_vision_model", return_value='{"title": null, "author": null}'):
        result = pipeline.run_pipeline(_synthetic_shelf_bytes())
    assert any(b["status"] == "unreadable" for b in result["books"])


def test_good_read_matches_catalog_and_reports_latency_and_cost():
    with patch("pipeline.call_vision_model",
               return_value='{"title": "Dune", "author": "Frank Herbert"}'):
        result = pipeline.run_pipeline(_synthetic_shelf_bytes())
    ok = [b for b in result["books"] if b["status"] == "ok"]
    assert ok
    assert ok[0]["match"]["title"] == "Dune"
    assert ok[0]["band"] == "auto"
    assert "latency_s" in result
    assert "estimated_cost_usd" in result


def test_parse_vlm_json_strips_markdown_fences():
    parsed = pipeline._parse_vlm_json('```json\n{"title": "Dune", "author": "Herbert"}\n```')
    assert parsed["title"] == "Dune"


def test_parse_vlm_json_raises_on_no_json_for_caller_to_handle():
    with pytest.raises(ValueError):
        pipeline._parse_vlm_json("just some prose, no object here")
