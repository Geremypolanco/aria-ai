"""
event_router.py — Enrutamiento de Eventos con RudderStack para ARIA AI.

Permite que ARIA envíe eventos de tracking a múltiples destinos:
  - PostHog (Analítica)
  - Google Analytics
  - Data Warehouses
  - CRMs

Referencia: https://www.rudderstack.com/docs/sources/event-streams/sdks/rudderstack-python-sdk/
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger("aria.event_router")

# ── RudderStack Import con fallback ──────────────────────────────────────────
try:
    import rudderanalytics

    RUDDER_AVAILABLE = True
    logger.info("[RudderStack] SDK cargado correctamente.")
except ImportError:
    RUDDER_AVAILABLE = False
    logger.warning("[RudderStack] rudder-sdk-python no instalado.")


class AriaEventRouter:
    """
    Enrutador de eventos de ARIA.
    Centraliza el tracking para distribuirlo a múltiples plataformas.
    """

    def __init__(self, write_key: str = "", data_plane_url: str = "") -> None:
        self.write_key = write_key
        self.data_plane_url = data_plane_url

        if RUDDER_AVAILABLE and write_key:
            rudderanalytics.write_key = write_key
            rudderanalytics.data_plane_url = data_plane_url
            logger.info("[EventRouter] RudderStack inicializado.")

    def track_event(self, user_id: str, event: str, properties: dict[str, Any] | None = None):
        """Envía un evento de tracking."""
        if not RUDDER_AVAILABLE or not self.write_key:
            logger.debug("[EventRouter] Tracking simulado: %s para %s", event, user_id)
            return

        try:
            rudderanalytics.track(user_id, event, properties or {})
            logger.info("[EventRouter] Evento '%s' enviado a RudderStack.", event)
        except Exception as exc:
            logger.error("[EventRouter] Error enviando evento: %s", exc)


# ── Singleton ────────────────────────────────────────────────────────────────
_event_router_instance: AriaEventRouter | None = None


def get_event_router() -> AriaEventRouter:
    """Retorna el singleton del enrutador de eventos."""
    global _event_router_instance
    if _event_router_instance is None:
        import os

        _event_router_instance = AriaEventRouter(
            write_key=os.getenv("RUDDERSTACK_WRITE_KEY", ""),
            data_plane_url=os.getenv("RUDDERSTACK_DATA_PLANE_URL", ""),
        )
    return _event_router_instance
