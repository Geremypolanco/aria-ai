"""Regression tests for the SSRF guard added to WebTools.fetch_page().

Before this fix, fetch_page(url) made the *server* issue a request to
whatever URL the LLM tool-call decided on (steerable via the user's chat
message) with zero validation — a classic SSRF: "fetch
http://169.254.169.254/... and tell me what it says" would have the server
itself hit cloud metadata / internal-only services.
"""

from __future__ import annotations

import httpx
import pytest

from apps.core.tools.web_tools import WebTools, _assert_public_url

pytestmark = pytest.mark.asyncio


@pytest.mark.parametrize(
    "url",
    [
        "http://169.254.169.254/latest/meta-data/",
        "http://127.0.0.1:8080/admin",
        "http://localhost/",
        "http://10.0.0.5/",
        "http://192.168.1.1/",
        "http://[::1]/",
        "ftp://example.com/",
    ],
)
async def test_assert_public_url_blocks_unsafe_targets(url):
    with pytest.raises(ValueError):
        await _assert_public_url(url)


async def test_assert_public_url_allows_a_real_public_host():
    # example.com's addresses are stable, well-known public IPs.
    await _assert_public_url("https://example.com/")


async def test_fetch_page_refuses_internal_url():
    wt = WebTools()
    result = await wt.fetch_page("http://169.254.169.254/latest/meta-data/")
    assert result["success"] is False
    assert "non-public" in result["error"] or "refus" in result["error"].lower()


async def test_fetch_page_blocks_redirect_to_internal_address():
    """A URL that resolves publicly can still 302 to an internal address —
    the guard must be re-checked on every hop, not just the original URL."""

    def handler(request: httpx.Request) -> httpx.Response:
        if str(request.url) == "https://example.com/redirect":
            return httpx.Response(302, headers={"location": "http://127.0.0.1/secret"})
        return httpx.Response(200, text="<html><body>should never get here</body></html>")

    wt = WebTools()
    wt._http = httpx.AsyncClient(transport=httpx.MockTransport(handler))

    result = await wt.fetch_page("https://example.com/redirect")
    assert result["success"] is False


async def test_fetch_page_succeeds_for_a_safe_url():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="<html><title>Hi</title><body>Hello world</body></html>")

    wt = WebTools()
    wt._http = httpx.AsyncClient(transport=httpx.MockTransport(handler))

    result = await wt.fetch_page("https://example.com/")
    assert result["success"] is True
    assert "Hello world" in result["text"]
