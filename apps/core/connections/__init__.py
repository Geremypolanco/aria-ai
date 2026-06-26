"""
Connections — sistema MCP equivalente para ARIA AI.

Permite conectar servicios externos (Google, Indeed, Slack, y más)
con un simple comando /connect <servicio> desde Telegram.
Los tokens OAuth se guardan en Redis por usuario.
"""

from apps.core.connections.manager import ConnectionManager, get_connection_manager

__all__ = ["ConnectionManager", "get_connection_manager"]
