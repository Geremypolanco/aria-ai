"""
zapier_client.py — Cliente de Zapier para ARIA.

ARIA puede llamar a Zapier para delegar acciones a servicios externos
(Shopify, Gmail, Google Sheets, Slack, cualquier app conectada en Zapier).

Flujo:
  1. Usuario pide algo que requiere un servicio externo
  2. ARIA llama a trigger(event, data) -> POST al webhook de Zapier
  3. Zapier ejecuta el Zap configurado (ej: buscar productos en Shopify)
  4. Si el Zap tiene respuesta, llama al callback de ARIA (/zapier/callback)
  5. ARIA recibe el resultado y lo reporta al usuario

Configuracion requerida en Fly.io:
  fly secrets set ZAPIER_WEBHOOK_URL="https://hooks.zapier.com/hooks/catch/..."
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from typing import Any, Optional

import httpx

from apps.core.config import settings

logger = logging.getLogger("aria.zapier")


class ZapierEvents:
    """Constantes de eventos que ARIA puede disparar en Zapier."""
    SEARCH_PRODUCTS = "search_products"
    SEND_EMAIL = "send_email"
    CREATE_TASK = "create_task"
    POST_SOCIAL = "post_social"
    ADD_CONTACT = "add_contact"
    CREATE_INVOICE = "create_invoice"
    SEND_NOTIFICATION = "send_notification"
    CUSTOM = "custom"


class ZapierClient:
    """
    Cliente asincronico para enviar eventos a Zapier via webhook.
    Soporta fire-and-forget y espera de respuesta via callback.
    """

    def __init__(self) -> None:
        self.webhook_url: Optional[str] = getattr(settings, "ZAPIER_WEBHOOK_URL", None)
        self._pending: dict[str, asyncio.Future] = {}

    def _check_configured(self) -> None:
        if not self.webhook_url:
            raise RuntimeError(
                "ZAPIER_WEBHOOK_URL no configurado. "
                "Ejecuta: fly secrets set ZAPIER_WEBHOOK_URL=\"https://hooks.zapier.com/...\"",
            )

    async def trigger(self, event: str, data: dict[str, Any] | None = None,
                      chat_id: str | None = None, timeout: float = 10.0) -> dict[str, Any]:
        """
        Envia un evento a Zapier y devuelve la respuesta HTTP inmediata.
        Para esperar el resultado del Zap usa trigger_and_wait().
        """
        self._check_configured()
        payload = {
            "request_id": str(uuid.uuid4()),
            "event": event,
            "data": data or {},
            "chat_id": chat_id,
            "timestamp": time.time(),
            "aria_callback_url": f"{getattr(settings, 'ARIA_BASE_URL', 'https://aria-ai.fly.dev')}/zapier/callback",
        }
        logger.info("Zapier trigger: event=%s request_id=%s", event, payload["request_id"])
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(self.webhook_url, json=payload)
            resp.raise_for_status()
            try:
                result = resp.json()
            except Exception:
                result = {"raw": resp.text, "status": resp.status_code}
        logger.info("Zapier response: %s", result)
        return {"request_id": payload["request_id"], "response": result}

    async def trigger_and_wait(self, event: str, data: dict[str, Any] | None = None,
                               chat_id: str | None = None,
                               trigger_timeout: float = 10.0,
                               callback_timeout: float = 30.0) -> dict[str, Any]:
        """
        Envia el evento y espera hasta callback_timeout segundos
        por la respuesta del Zap via /zapier/callback.
        """
        self._check_configured()
        payload = {
            "request_id": str(uuid.uuid4()),
            "event": event,
            "data": data or {},
            "chat_id": chat_id,
            "timestamp": time.time(),
            "aria_callback_url": f"{getattr(settings, 'ARIA_BASE_URL', 'https://aria-ai.fly.dev')}/zapier/callback",
        }
        loop = asyncio.get_event_loop()
        future: asyncio.Future = loop.create_future()
        self._pending[payload["request_id"]] = future
        try:
            async with httpx.AsyncClient(timeout=trigger_timeout) as client:
                resp = await client.post(self.webhook_url, json=payload)
                resp.raise_for_status()
            result = await asyncio.wait_for(future, timeout=callback_timeout)
        except asyncio.TimeoutError:
            self._pending.pop(payload["request_id"], None)
            return {
                "request_id": payload["request_id"],
                "status": "timeout",
                "message": f"Zapier no respondio en {callback_timeout}s",
            }
        finally:
            self._pending.pop(payload["request_id"], None)
        return {"request_id": payload["request_id"], "result": result}

    def resolve_callback(self, request_id: str, result: Any) -> bool:
        """Llamado por /zapier/callback cuando Zapier responde."""
        future = self._pending.get(request_id)
        if future and not future.done():
            future.set_result(result)
            return True
        return False


# Singleton global
zapier_client = ZapierClient()
