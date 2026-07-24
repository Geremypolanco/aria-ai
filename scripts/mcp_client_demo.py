"""
mcp_client_demo.py — Local test of ARIA's MCP client.

Spins up the example MCP server (scripts/mcp_demo_server.py) over STDIO,
connects with MCPAgent, runs the handshake, lists the tools, shows the
mapping to Claude's function-calling format, and makes a real tool call.
If ANTHROPIC_API_KEY is configured, it also runs the full agentic loop
(Claude ↔ MCP tools).

Usage:  python3 scripts/mcp_client_demo.py
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

# Lets apps.* be imported when running this script directly.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from apps.core.integrations.mcp_agent import (  # noqa: E402
    MCPAgent,
    MCPServerConfig,
    mcp_tool_to_anthropic,
)

SERVER = Path(__file__).resolve().parent / "mcp_demo_server.py"


async def main() -> None:
    config = MCPServerConfig(
        name="memory",
        transport="stdio",
        command=sys.executable,
        args=[str(SERVER)],
    )
    agent = MCPAgent([config])

    print("=" * 64)
    print("1) Connecting to the MCP server over STDIO + Protocol Initialization")
    print("=" * 64)
    async with agent:
        conn = agent._connections[0]

        print("\n2) Tools discovered dynamically (tools/list):")
        for t in conn.tools:
            print(f"   - {t.name}: {t.description}")

        print("\n3) MCP → Claude function-calling format mapping:")
        for t in conn.tools:
            mapped = mcp_tool_to_anthropic(t)
            print(json.dumps(mapped, indent=2, ensure_ascii=False))

        print("\n4) Direct MCP tool call (no LLM):")
        out, err = await agent._dispatch_tool(
            "memory__store_memory", {"key": "name", "value": "Geremy"}
        )
        print(f"   store_memory -> {out} (error={err})")
        out, err = await agent._dispatch_tool("memory__get_memory", {"key": "name"})
        print(f"   get_memory   -> {out} (error={err})")

        if os.getenv("ANTHROPIC_API_KEY"):
            print("\n5) Full agentic loop with Claude (function calling):")
            result = await agent.run(
                "Save that my favorite color is green, then tell me what it is."
            )
            print(f"   Final reply: {result.text}")
            print(f"   Tools used: {[c.tool for c in result.tool_calls]}")
            print(f"   stop_reason={result.stop_reason} turns={result.turns}")
        else:
            print("\n5) [skipped] Set ANTHROPIC_API_KEY to test the loop with Claude.")

    print("\nOK — MCP client working.")


if __name__ == "__main__":
    asyncio.run(main())
