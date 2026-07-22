"""Regression test: KnowledgeBase.ingest_url() had zero SSRF protection.

It is reachable straight from chat via aria_mind's "learn" tool — which is
NOT in _OWNER_ONLY_TOOLS, so any authenticated user could ask ARIA to
"aprende de http://169.254.169.254/latest/meta-data/" (or any internal
address) and the server itself would fetch it. Same class of bug already
fixed in web_tools.py/browser_sandbox.py/multimodal.py/huggingface_suite.py
via _assert_public_url(), applied here identically (including re-validating
every redirect hop, since a publicly-resolving URL can still 302 to an
internal address).
"""

from __future__ import annotations

import httpx
import pytest

from apps.core.tools.knowledge_base import KnowledgeBase

pytestmark = pytest.mark.asyncio


async def test_ingest_url_refuses_internal_address():
    kb = KnowledgeBase()
    result = await kb.ingest_url("http://169.254.169.254/latest/meta-data/")
    assert result["success"] is False
    assert "non-public" in result["error"] or "refus" in result["error"].lower()


async def test_ingest_url_blocks_redirect_to_internal_address():
    def handler(request: httpx.Request) -> httpx.Response:
        if str(request.url) == "https://example.com/redirect":
            return httpx.Response(302, headers={"location": "http://127.0.0.1/secret"})
        return httpx.Response(200, text="<html><body>should never get here</body></html>")

    kb = KnowledgeBase()
    kb._http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    result = await kb.ingest_url("https://example.com/redirect")
    assert result["success"] is False
