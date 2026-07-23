"""
zapier_mcp.py — Client for the user's Zapier MCP server.

This is the bridge that lets ARIA publish to every account the owner has already
connected in Zapier (Instagram, YouTube, Pinterest, LinkedIn, Buffer, ...) using a
SINGLE credential — the Zapier MCP endpoint URL (which embeds its own key) — instead
of provisioning OAuth apps for each platform.

Configuration: set the ``ZAPIER_MCP_URL`` secret to the full MCP endpoint URL copied
from https://mcp.zapier.com (it looks like ``https://mcp.zapier.com/api/mcp/s/<token>/mcp``).
Degrades gracefully to a no-op when unconfigured.

The wire protocol (JSON-RPC 2.0 over "streamable HTTP") is shared with any other
MCP server ARIA talks to — see mcp_streamable_client.py for that transport. This
module only owns the Zapier-specific bits: which env var configures it and the
error message callers see when it's missing.
"""

from __future__ import annotations

from typing import Any

from apps.core.config import settings
from apps.core.tools.mcp_streamable_client import StreamableHttpMCPClient

_UNCONFIGURED = "ZAPIER_MCP_URL not configured"


class ZapierMCPClient:
    """Tiny MCP client bound to the user's configured Zapier MCP endpoint."""

    def __init__(self, url: str | None = None, timeout: float = 90.0) -> None:
        # 90s: Zapier publish actions (video transcode, etc.) can be slow.
        resolved = (url or getattr(settings, "ZAPIER_MCP_URL", None) or "").strip()
        self._transport = StreamableHttpMCPClient(
            resolved, client_name="aria-content-operator", timeout=timeout
        )

    @property
    def configured(self) -> bool:
        return self._transport.configured

    @property
    def url(self) -> str:
        return self._transport.url

    async def list_tools(self) -> list[dict[str, Any]]:
        return await self._transport.list_tools()

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        return await self._transport.call_tool(name, arguments, unconfigured_error=_UNCONFIGURED)

    async def find_tool(self, *keywords: str) -> str | None:
        return await self._transport.find_tool(*keywords)

    async def self_test(self) -> dict[str, Any]:
        return await self._transport.self_test(unconfigured_error=_UNCONFIGURED)


_client: ZapierMCPClient | None = None


def get_zapier_mcp() -> ZapierMCPClient:
    """Process-wide singleton."""
    global _client
    if _client is None:
        _client = ZapierMCPClient()
    return _client
