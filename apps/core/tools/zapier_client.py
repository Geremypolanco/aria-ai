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
import logging
import time
import uuid
from typing import Any

import httpx

from apps.core.config import settings

logger = logging.getLogger("aria.zapier")

# Prefijo de clave Redis para almacenar callbacks pendientes
CALLBACK_KEY_PREFIX = "zapier:callback:"


class ZapierEvents:
    """Constantes de eventos que ARIA puede disparar en Zapier."""

    # Genericos
    SEARCH_PRODUCTS = "search_products"
    SEND_EMAIL = "send_email"
    CREATE_TASK = "create_task"
    POST_SOCIAL = "post_social"
    ADD_CONTACT = "add_contact"
    CREATE_INVOICE = "create_invoice"
    SEND_NOTIFICATION = "send_notification"
    CUSTOM = "custom"
    PING = "aria.ping"
    # Shopify
    SHOPIFY_GET_PRODUCTS = "shopify.get_products"
    SHOPIFY_GET_ORDERS = "shopify.get_orders"
    SHOPIFY_GET_INVENTORY = "shopify.get_inventory"
    SHOPIFY_GET_REVENUE = "shopify.get_revenue"
    # Gmail
    GMAIL_GET_INBOX = "gmail.get_inbox"
    GMAIL_SEND = "gmail.send"
    # Sheets
    SHEETS_READ = "sheets.read"
    SHEETS_WRITE = "sheets.write"


class ZapierClient:
    """
    Cliente asincronico para enviar eventos a Zapier via webhook.
    Soporta fire-and-forget y espera de respuesta via callback.
    """

    def __init__(self) -> None:
        self.webhook_url: str | None = getattr(settings, "ZAPIER_WEBHOOK_URL", None)
        self._pending: dict[str, asyncio.Future] = {}

    def is_configured(self) -> bool:
        """Retorna True si el webhook de Zapier esta configurado."""
        return bool(self.webhook_url)

    def _check_configured(self) -> None:
        if not self.webhook_url:
            raise RuntimeError(
                "ZAPIER_WEBHOOK_URL no configurado. "
                'Ejecuta: fly secrets set ZAPIER_WEBHOOK_URL="https://hooks.zapier.com/..."',
            )

    async def trigger(
        self,
        event: str,
        data: dict[str, Any] | None = None,
        chat_id: str | None = None,
        timeout: float = 10.0,
    ) -> dict[str, Any]:
        """
        Envia un evento a Zapier y devuelve la respuesta HTTP inmediata.
        Para esperar el resultado del Zap usa trigger_and_wait().
        """
        if not self.webhook_url:
            return {"success": False, "error": "ZAPIER_WEBHOOK_URL no configurado"}
        payload = {
            "request_id": str(uuid.uuid4()),
            "event": event,
            "data": data or {},
            "chat_id": chat_id,
            "timestamp": time.time(),
            "aria_callback_url": f"{getattr(settings, 'ARIA_BASE_URL', 'https://aria-ai.fly.dev')}/zapier/callback",
        }
        logger.info("Zapier trigger: event=%s request_id=%s", event, payload["request_id"])
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                resp = await client.post(self.webhook_url, json=payload)
                resp.raise_for_status()
                try:
                    result = resp.json()
                except Exception:
                    result = {"raw": resp.text, "status": resp.status_code}
            logger.info("Zapier response: %s", result)
            return {"success": True, "request_id": payload["request_id"], "response": result}
        except Exception as exc:
            logger.error("Zapier trigger error: %s", exc)
            return {"success": False, "error": str(exc)}

    async def trigger_and_wait(
        self,
        event: str,
        data: dict[str, Any] | None = None,
        chat_id: str | None = None,
        trigger_timeout: float = 10.0,
        callback_timeout: float = 30.0,
    ) -> dict[str, Any]:
        """
        Envia el evento y espera hasta callback_timeout segundos
        por la respuesta del Zap via /zapier/callback.
        """
        if not self.webhook_url:
            return {"success": False, "error": "ZAPIER_WEBHOOK_URL no configurado"}
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
        except TimeoutError:
            self._pending.pop(payload["request_id"], None)
            return {
                "request_id": payload["request_id"],
                "status": "timeout",
                "message": f"Zapier no respondio en {callback_timeout}s",
            }
        except Exception as exc:
            self._pending.pop(payload["request_id"], None)
            return {"success": False, "error": str(exc)}
        finally:
            self._pending.pop(payload["request_id"], None)
        return {"success": True, "request_id": payload["request_id"], "result": result}

    def resolve_callback(self, request_id: str, result: Any) -> bool:
        """Llamado por /zapier/callback cuando Zapier responde."""
        future = self._pending.get(request_id)
        if future and not future.done():
            future.set_result(result)
            return True
        return False


# Singleton global
_zapier_client: ZapierClient | None = None


def get_zapier_client() -> ZapierClient:
    """Retorna el singleton de ZapierClient."""
    global _zapier_client
    if _zapier_client is None:
        _zapier_client = ZapierClient()
    return _zapier_client


# Alias de compatibilidad
zapier_client = get_zapier_client()
