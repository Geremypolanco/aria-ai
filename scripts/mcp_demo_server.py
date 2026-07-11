"""
mcp_demo_server.py — Servidor MCP básico de ejemplo (memoria en RAM).

Sirve para probar localmente el Cliente MCP de ARIA (apps/core/integrations/
mcp_agent.py) sin depender de servidores externos. Expone 3 herramientas
sencillas sobre un diccionario en memoria, al estilo del "memory server" de
referencia de MCP.

Se ejecuta por STDIO:  python3 scripts/mcp_demo_server.py
"""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("aria-demo-memory")

_STORE: dict[str, str] = {}


@mcp.tool()
def store_memory(key: str, value: str) -> str:
    """Guarda un valor bajo una clave para recuperarlo más tarde."""
    _STORE[key] = value
    return f"Guardado: {key!r} = {value!r}"


@mcp.tool()
def get_memory(key: str) -> str:
    """Recupera el valor guardado bajo una clave."""
    if key not in _STORE:
        return f"No hay nada guardado bajo {key!r}."
    return _STORE[key]


@mcp.tool()
def list_memories() -> str:
    """Lista todas las claves guardadas en memoria."""
    if not _STORE:
        return "(memoria vacía)"
    return ", ".join(sorted(_STORE))


if __name__ == "__main__":
    mcp.run(transport="stdio")
