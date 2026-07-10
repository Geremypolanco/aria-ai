"""
mcp_client_demo.py — Prueba local del Cliente MCP de ARIA.

Levanta el servidor MCP de ejemplo (scripts/mcp_demo_server.py) por STDIO,
se conecta con MCPAgent, ejecuta el handshake, lista las herramientas, muestra
el mapeo al formato de function calling de Claude, y ejecuta una llamada real
a una herramienta. Si ANTHROPIC_API_KEY está configurada, corre además el
bucle agéntico completo (Claude ↔ herramientas MCP).

Uso:  python3 scripts/mcp_client_demo.py
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

# Permite importar apps.* al ejecutar el script directamente.
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
    print("1) Conectando al servidor MCP por STDIO + Protocol Initialization")
    print("=" * 64)
    async with agent:
        conn = agent._connections[0]

        print("\n2) Herramientas descubiertas dinámicamente (tools/list):")
        for t in conn.tools:
            print(f"   - {t.name}: {t.description}")

        print("\n3) Mapeo MCP → formato de function calling de Claude:")
        for t in conn.tools:
            mapped = mcp_tool_to_anthropic(t)
            print(json.dumps(mapped, indent=2, ensure_ascii=False))

        print("\n4) Ejecución directa de una herramienta MCP (sin LLM):")
        out, err = await agent._dispatch_tool(
            "memory__store_memory", {"key": "nombre", "value": "Geremy"}
        )
        print(f"   store_memory -> {out} (error={err})")
        out, err = await agent._dispatch_tool("memory__get_memory", {"key": "nombre"})
        print(f"   get_memory   -> {out} (error={err})")

        if os.getenv("ANTHROPIC_API_KEY"):
            print("\n5) Bucle agéntico completo con Claude (function calling):")
            result = await agent.run(
                "Guarda que mi color favorito es el verde y luego dime cuál es."
            )
            print(f"   Respuesta final: {result.text}")
            print(f"   Herramientas usadas: {[c.tool for c in result.tool_calls]}")
            print(f"   stop_reason={result.stop_reason} turnos={result.turns}")
        else:
            print("\n5) [omitido] Define ANTHROPIC_API_KEY para probar el loop con Claude.")

    print("\nOK — cliente MCP funcional.")


if __name__ == "__main__":
    asyncio.run(main())
