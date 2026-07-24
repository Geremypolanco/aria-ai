"""
mcp_demo_server.py — Basic example MCP server (in-RAM memory).

Used to test ARIA's MCP client (apps/core/integrations/mcp_agent.py) locally
without depending on external servers. Exposes 3 simple tools over an
in-memory dict, in the style of MCP's reference "memory server".

Run over STDIO:  python3 scripts/mcp_demo_server.py
"""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("aria-demo-memory")

_STORE: dict[str, str] = {}


@mcp.tool()
def store_memory(key: str, value: str) -> str:
    """Stores a value under a key to retrieve later."""
    _STORE[key] = value
    return f"Stored: {key!r} = {value!r}"


@mcp.tool()
def get_memory(key: str) -> str:
    """Retrieves the value stored under a key."""
    if key not in _STORE:
        return f"Nothing stored under {key!r}."
    return _STORE[key]


@mcp.tool()
def list_memories() -> str:
    """Lists all keys currently stored in memory."""
    if not _STORE:
        return "(empty memory)"
    return ", ".join(sorted(_STORE))


if __name__ == "__main__":
    mcp.run(transport="stdio")
