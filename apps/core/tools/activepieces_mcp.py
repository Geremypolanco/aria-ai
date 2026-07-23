"""
activepieces_mcp.py — Client for a self-hosted Activepieces MCP server.

Activepieces (Community Edition, MIT-licensed) exposes each connected piece as an
MCP tool, giving ARIA one more source of integrations (200+ pieces — Google, Slack,
HubSpot, Stripe, and more) without hand-building an OAuth flow per app. This is
deliberately NOT a vendored copy of Activepieces' code: Activepieces runs as its own
self-hosted service (see infra/activepieces/ for the docker-compose to stand it up),
and ARIA only talks to it over MCP — the same arrangement already used for Zapier.

Configuration: set ``ACTIVEPIECES_MCP_URL`` to your instance's MCP endpoint (from
Activepieces' MCP settings once a piece/flow is published with MCP enabled). Degrades
gracefully to a no-op when unconfigured.

Unlike Zapier, which exposes generic meta-tools (execute_zapier_write_action, ...),
Activepieces surfaces one MCP tool per connected piece/action, so there's no fixed
"CHANNELS"-style name mapping to hardcode here — callers should discover the actual
tool names via list_tools()/find_tool() against their own running instance, since
that naming depends on which pieces the instance owner has connected.
"""

from __future__ import annotations

from typing import Any

from apps.core.config import settings
from apps.core.tools.mcp_streamable_client import StreamableHttpMCPClient

_UNCONFIGURED = "ACTIVEPIECES_MCP_URL not configured"


class ActivepiecesMCPClient:
    """Tiny MCP client bound to the user's configured Activepieces MCP endpoint."""

    def __init__(self, url: str | None = None, timeout: float = 90.0) -> None:
        resolved = (url or getattr(settings, "ACTIVEPIECES_MCP_URL", None) or "").strip()
        self._transport = StreamableHttpMCPClient(
            resolved, client_name="aria-activepieces", timeout=timeout
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


_client: ActivepiecesMCPClient | None = None


def get_activepieces_mcp() -> ActivepiecesMCPClient:
    """Process-wide singleton."""
    global _client
    if _client is None:
        _client = ActivepiecesMCPClient()
    return _client
