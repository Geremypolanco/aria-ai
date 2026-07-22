"""Regression tests for bugs found auditing google_suite.py:

1. full_market_research() hardcoded "success": True regardless of whether
   any of its 5 parallel sub-calls (web/youtube/books/knowledge_graph/trends)
   actually succeeded — asyncio.gather(..., return_exceptions=True) means
   every single one could come back as an Exception and it would still
   report success. Consumed directly by pm_agent.py's market research step.
2. youtube_trending() defaulted category_id="0" and always sent it as
   videoCategoryId — but YouTube category IDs start at "1"; "0" isn't valid
   and the API rejects it with HTTP 400. Every caller using the default
   (e.g. pm_agent.py's `google.youtube_trending("US")`) always failed.
3. vision_analyze()/translate()/detect_language() relied on
   dict.get(key, default)[0] to guard against a missing key — but that
   default only applies when the key is absent, not when it's present with
   an empty list, so a partial/degenerate API response still raised
   IndexError (inconsistent with youtube_channel_details, which already
   guards this correctly elsewhere in the same file).
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from apps.core.tools.google_suite import GoogleSuite

pytestmark = pytest.mark.asyncio


async def test_full_market_research_reports_failure_when_everything_fails(monkeypatch):
    monkeypatch.setattr("apps.core.tools.google_suite.settings.GOOGLE_API_KEY", "fake-key")
    suite = GoogleSuite()

    async def always_fail(*a, **k):
        raise RuntimeError("network down")

    with patch.object(GoogleSuite, "web_search", always_fail), patch.object(
        GoogleSuite, "youtube_search", always_fail
    ), patch.object(GoogleSuite, "books_search", always_fail), patch.object(
        GoogleSuite, "knowledge_graph_search", always_fail
    ), patch.object(GoogleSuite, "trends_daily", always_fail):
        result = await suite.full_market_research("fitness")

    assert result["success"] is False


async def test_full_market_research_reports_success_when_one_source_works(monkeypatch):
    monkeypatch.setattr("apps.core.tools.google_suite.settings.GOOGLE_API_KEY", "fake-key")
    suite = GoogleSuite()

    async def always_fail(*a, **k):
        raise RuntimeError("network down")

    async def web_ok(*a, **k):
        return {"success": True, "results": [{"snippet": "some result"}]}

    with patch.object(GoogleSuite, "web_search", web_ok), patch.object(
        GoogleSuite, "youtube_search", always_fail
    ), patch.object(GoogleSuite, "books_search", always_fail), patch.object(
        GoogleSuite, "knowledge_graph_search", always_fail
    ), patch.object(GoogleSuite, "trends_daily", always_fail), patch.object(
        GoogleSuite, "nlp_analyze", AsyncMock(return_value={"success": True})
    ):
        result = await suite.full_market_research("fitness")

    assert result["success"] is True


async def test_youtube_trending_default_omits_invalid_category_id(monkeypatch):
    monkeypatch.setattr("apps.core.tools.google_suite.settings.GOOGLE_API_KEY", "fake-key")
    suite = GoogleSuite()

    fake_resp = MagicMock()
    fake_resp.status_code = 200
    fake_resp.json.return_value = {"items": []}
    captured = {}

    async def fake_get(url, params=None, **kwargs):
        captured["params"] = params
        return fake_resp

    with patch.object(suite._http, "get", fake_get):
        result = await suite.youtube_trending("US")

    assert result["success"] is True
    assert "videoCategoryId" not in captured["params"]


async def test_vision_analyze_handles_empty_responses_list(monkeypatch):
    monkeypatch.setattr("apps.core.tools.google_suite.settings.GOOGLE_API_KEY", "fake-key")
    suite = GoogleSuite()

    fake_resp = MagicMock()
    fake_resp.status_code = 200
    fake_resp.json.return_value = {"responses": []}

    async def fake_post(url, params=None, json=None, **kwargs):
        return fake_resp

    with patch.object(suite._http, "post", fake_post):
        result = await suite.vision_analyze(b"fake image bytes")

    assert result["success"] is True
