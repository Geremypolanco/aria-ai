"""Regression test: WebTools._search_newsapi()'s snippet field did
a.get("description", "") or a.get("content", "")[:300] — but NewsAPI
frequently returns "description": null / "content": null explicitly
present (not absent). .get(key, default) only applies the default when
the key is ABSENT; when present with value None, .get returns None. So
a.get("content", "")[:300] could be None[:300], raising TypeError,
silently killing the whole NewsAPI source for that query (caught by the
outer bare except).
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from apps.core.tools.web_tools import WebTools

pytestmark = pytest.mark.asyncio


async def test_search_newsapi_handles_null_description_and_content(monkeypatch):
    wt = WebTools()
    monkeypatch.setattr("apps.core.tools.web_tools.settings.NEWS_API_KEY", "fake-key", raising=False)

    fake_resp = MagicMock()
    fake_resp.status_code = 200
    fake_resp.json.return_value = {
        "articles": [
            {
                "title": "Some headline",
                "url": "https://example.com/a",
                "description": None,
                "content": None,
                "publishedAt": "2026-01-01T00:00:00Z",
            }
        ]
    }
    wt._http.get = AsyncMock(return_value=fake_resp)

    result = await wt._search_newsapi("test query", num=5)

    assert result["success"] is True
    assert result["results"][0]["snippet"] == ""
