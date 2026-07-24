"""
Connections — MCP-equivalent system for ARIA AI.

Allows connecting external services (Google, Indeed, Slack, and more)
with a simple /connect <service> command from Telegram.
OAuth tokens are stored in Redis per user.
"""

from apps.core.connections.manager import ConnectionManager, get_connection_manager

__all__ = ["ConnectionManager", "get_connection_manager"]
