"""Regression test: BrowserSession.navigate() had the same unguarded-URL SSRF
gap as WebTools.fetch_page — worse, since it's a real browser (executes JS,
follows redirects) rather than a plain text fetch."""

from __future__ import annotations

import pytest

from apps.core.tools.browser_sandbox import BrowserSession

pytestmark = pytest.mark.asyncio


async def test_navigate_refuses_internal_url():
    session = BrowserSession()
    result = await session.navigate("http://169.254.169.254/latest/meta-data/")
    assert result["success"] is False
    assert "non-public" in result["error"] or "refus" in result["error"].lower()


async def test_navigate_refuses_localhost():
    session = BrowserSession()
    result = await session.navigate("http://127.0.0.1:8080/admin")
    assert result["success"] is False
