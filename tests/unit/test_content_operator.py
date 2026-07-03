"""
Unit tests for the autonomous content operator and its Zapier MCP bridge.

These cover the two pieces most likely to harbor bugs and that don't need network:
  - ZapierMCPClient._parse_body: JSON vs SSE (event-stream) response parsing
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
        from apps.core.tools.zapier_mcp import ZapierMCPClient

        body = {"jsonrpc": "2.0", "id": 1, "result": {"tools": [{"name": "x"}]}}
        resp = _FakeResp("application/json", "{...}", json_obj=body)
        out = ZapierMCPClient._parse_body(resp)
        assert out["result"]["tools"][0]["name"] == "x"

    def test_sse_response_returns_result_frame(self):
        from apps.core.tools.zapier_mcp import ZapierMCPClient

        sse = (
            "event: message\n"
            'data: {"jsonrpc":"2.0","id":1,"result":{"content":[{"type":"text","text":"ok"}]}}\n'
            "\n"
        )
        resp = _FakeResp("text/event-stream", sse)
        out = ZapierMCPClient._parse_body(resp)
        assert out["result"]["content"][0]["text"] == "ok"

    def test_sse_keeps_last_meaningful_frame(self):
        from apps.core.tools.zapier_mcp import ZapierMCPClient

        sse = (
            'data: {"jsonrpc":"2.0","method":"ping"}\n'
            'data: {"jsonrpc":"2.0","id":2,"result":{"value":42}}\n'
            "data: [DONE]\n"
        )
        resp = _FakeResp("text/event-stream", sse)
        out = ZapierMCPClient._parse_body(resp)
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


class TestBuildArgs:
    def _build(self, schema, extra=None):
        from apps.core.tools.content_operator import ContentOperator

        return ContentOperator._build_args(
            schema, "https://cdn/img.png", "Hello caption", extra or {}
        )

    def test_array_media_field_wraps_in_list(self):
        schema = {
            "type": "object",
            "properties": {
                "media": {"type": "array"},
                "caption": {"type": "string"},
            },
            "required": ["media"],
        }
        args = self._build(schema)
        assert args["media"] == ["https://cdn/img.png"]
        assert args["caption"] == "Hello caption"

    def test_string_image_field_stays_scalar(self):
        schema = {
            "type": "object",
            "properties": {
                "image_url": {"type": "string"},
                "description": {"type": "string"},
            },
        }
        args = self._build(schema)
        assert args["image_url"] == "https://cdn/img.png"
        # caption mapped onto the text-like field, not duplicated onto the image field
        assert args["description"] == "Hello caption"

    def test_image_and_text_keys_are_distinct(self):
        schema = {
            "properties": {
                "photo": {"type": "string"},
                "message": {"type": "string"},
            }
        }
        args = self._build(schema)
        assert args["photo"] == "https://cdn/img.png"
        assert args["message"] == "Hello caption"
        assert args["photo"] != args["message"]

    def test_required_extra_overrides(self):
        schema = {
            "properties": {
                "image_url": {"type": "string"},
                "title": {"type": "string"},
                "board_id": {"type": "string"},
            },
            "required": ["board_id", "image_url"],
        }
        args = self._build(schema, extra={"board_id": "123456"})
        assert args["board_id"] == "123456"
        assert args["image_url"] == "https://cdn/img.png"

    def test_empty_schema_yields_only_extras(self):
        args = self._build({}, extra={"foo": "bar"})
        assert args == {"foo": "bar"}
