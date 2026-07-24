"""
Unit tests for the autonomous content operator and its Zapier MCP bridge.

These cover the two pieces most likely to harbor bugs and that don't need network:
  - StreamableHttpMCPClient._parse_body (the shared transport ZapierMCPClient
    delegates to): JSON vs SSE (event-stream) response parsing
  - ZapierMCPClient graceful no-op when unconfigured
  - ContentOperator._build_args: schema-driven mapping of an asset onto a tool's
    unknown parameter names (array vs string image field, caption, required extras)
"""

from __future__ import annotations

import pytest


class _FakeResp:
    """Minimal stand-in for httpx.Response for _parse_body."""

    def __init__(self, content_type: str, text: str, json_obj=None):
        self.headers = {"content-type": content_type}
        self.text = text
        self._json = json_obj

    def json(self):
        if self._json is None:
            raise ValueError("no json")
        return self._json


class TestParseBody:
    def test_plain_json_response(self):
        from apps.core.tools.mcp_streamable_client import StreamableHttpMCPClient

        body = {"jsonrpc": "2.0", "id": 1, "result": {"tools": [{"name": "x"}]}}
        resp = _FakeResp("application/json", "{...}", json_obj=body)
        out = StreamableHttpMCPClient._parse_body(resp)
        assert out["result"]["tools"][0]["name"] == "x"

    def test_sse_response_returns_result_frame(self):
        from apps.core.tools.mcp_streamable_client import StreamableHttpMCPClient

        sse = (
            "event: message\n"
            'data: {"jsonrpc":"2.0","id":1,"result":{"content":[{"type":"text","text":"ok"}]}}\n'
            "\n"
        )
        resp = _FakeResp("text/event-stream", sse)
        out = StreamableHttpMCPClient._parse_body(resp)
        assert out["result"]["content"][0]["text"] == "ok"

    def test_sse_keeps_last_meaningful_frame(self):
        from apps.core.tools.mcp_streamable_client import StreamableHttpMCPClient

        sse = (
            'data: {"jsonrpc":"2.0","method":"ping"}\n'
            'data: {"jsonrpc":"2.0","id":2,"result":{"value":42}}\n'
            "data: [DONE]\n"
        )
        resp = _FakeResp("text/event-stream", sse)
        out = StreamableHttpMCPClient._parse_body(resp)
        assert out["result"]["value"] == 42


class TestZapierMCPUnconfigured:
    async def test_call_tool_noop_when_unconfigured(self):
        from apps.core.tools.zapier_mcp import ZapierMCPClient

        client = ZapierMCPClient(url="")
        assert client.configured is False
        out = await client.call_tool("anything", {"a": 1})
        assert out["success"] is False
        assert "not configured" in out["error"].lower()

    async def test_list_tools_empty_when_unconfigured(self):
        from apps.core.tools.zapier_mcp import ZapierMCPClient

        assert await ZapierMCPClient(url="").list_tools() == []


class TestChannelParams:
    def _params(self, channel, extra=None):
        from apps.core.tools.content_operator import ContentOperator

        return ContentOperator._channel_params(
            channel, "https://cdn/img.png", "Hook line\nrest of caption", extra or {}
        )

    def test_instagram_uses_media_list_and_caption(self):
        p = self._params("instagram")
        assert p["media"] == ["https://cdn/img.png"]
        assert p["caption"].startswith("Hook line")

    def test_pinterest_includes_board_and_source_when_given(self):
        p = self._params("pinterest", extra={"board_id": "999", "source_url": "https://x"})
        assert p["image_url"] == "https://cdn/img.png"
        assert p["board_id"] == "999"
        assert p["source_url"] == "https://x"
        # title derived from the first line of the caption, capped at 100 chars
        assert p["title"] == "Hook line"
        assert len(p["title"]) <= 100

    def test_pinterest_omits_board_when_absent(self):
        p = self._params("pinterest")
        assert "board_id" not in p
        assert p["description"].startswith("Hook line")

    def test_linkedin_is_text_first(self):
        p = self._params("linkedin")
        assert p["comment"].startswith("Hook line")
        assert p["visibility__code"] == "anyone"
        assert "media" not in p and "image_url" not in p

    def test_facebook_uses_photo_and_message(self):
        p = self._params("facebook")
        assert p["photo_url"] == "https://cdn/img.png"
        assert p["message"].startswith("Hook line")

    def test_unknown_channel_falls_back(self):
        p = self._params("mastodon")
        assert p == {"image_url": "https://cdn/img.png", "caption": "Hook line\nrest of caption"}
