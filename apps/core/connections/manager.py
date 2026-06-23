"""
ConnectionManager — gestión central de conexiones OAuth para ARIA AI.

Equivalente al sistema MCP de Claude: cada servicio es una conexión que
expone herramientas. Los tokens se guardan en Redis por chat_id.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

logger = logging.getLogger("aria.connections")


class ConnectionManager:
    """
    Gestiona conexiones OAuth a servicios externos.
    Cada conexión: {access_token, refresh_token, expires_at, scope, service_user}
    """

    K_CONN = "aria:conn:{chat_id}:{service}"   # Redis key por usuario y servicio
    TTL = 86400 * 90                            # 90 días

    AVAILABLE: dict[str, str] = {
        "google":  "Google (Gmail, Calendar, Drive)",
        "slack":   "Slack (mensajes, canales)",
        "indeed":  "Indeed (búsqueda de empleo)",
        "discord": "Discord (webhooks)",
        "notion":  "Notion (páginas, bases de datos)",
        "airtable": "Airtable (bases, registros)",
    }

    def _cache(self):
        from apps.core.memory.redis_client import get_cache
        return get_cache()

    async def store(self, chat_id: str, service: str, tokens: dict) -> None:
        cache = self._cache()
        if cache:
            key = self.K_CONN.format(chat_id=chat_id, service=service)
            await cache.set(key, tokens, ttl_seconds=self.TTL)
            logger.info("[Connections] %s conectado para chat %s", service, chat_id)

    async def get(self, chat_id: str, service: str) -> Optional[dict]:
        cache = self._cache()
        if not cache:
            return None
        key = self.K_CONN.format(chat_id=chat_id, service=service)
        data = await cache.get(key)
        return data if isinstance(data, dict) else None

    async def remove(self, chat_id: str, service: str) -> None:
        cache = self._cache()
        if cache:
            key = self.K_CONN.format(chat_id=chat_id, service=service)
            await cache.delete(key)
            logger.info("[Connections] %s desconectado para chat %s", service, chat_id)

    async def is_connected(self, chat_id: str, service: str) -> bool:
        tokens = await self.get(chat_id, service)
        return bool(tokens and tokens.get("access_token"))

    async def list_connected(self, chat_id: str) -> list[str]:
        cache = self._cache()
        if not cache:
            return []
        connected = []
        for service in self.AVAILABLE:
            if await self.is_connected(chat_id, service):
                connected.append(service)
        return connected

    def get_auth_url(self, service: str, chat_id: str) -> Optional[str]:
        """Genera URL de autenticación OAuth para el servicio."""
        from apps.core.config import settings
        if service == "google":
            from apps.core.connections.google_connection import GoogleConnection
            return GoogleConnection().get_auth_url(chat_id)
        if service == "slack":
            from apps.core.connections.slack_connection import SlackConnection
            return SlackConnection().get_auth_url(chat_id)
        return None

    async def handle_callback(self, service: str, code: str, chat_id: str) -> bool:
        """Exchange authorization code for tokens and store them."""
        try:
            if service == "google":
                from apps.core.connections.google_connection import GoogleConnection
                tokens = await GoogleConnection().exchange_code(code, chat_id)
            elif service == "slack":
                from apps.core.connections.slack_connection import SlackConnection
                tokens = await SlackConnection().exchange_code(code, chat_id)
            else:
                logger.warning("[Connections] Servicio desconocido: %s", service)
                return False
            if tokens:
                await self.store(chat_id, service, tokens)
                return True
        except Exception as exc:
            logger.error("[Connections] Callback error %s: %s", service, exc)
        return False


_mgr: Optional[ConnectionManager] = None


def get_connection_manager() -> ConnectionManager:
    global _mgr
    if _mgr is None:
        _mgr = ConnectionManager()
    return _mgr
