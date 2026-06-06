"""
  zapier_client.py — Cliente de Zapier para ARIA.

  ARIA puede llamar a Zapier para delegar acciones a servicios externos
  (Shopify, Gmail, Google Sheets, Slack, cualquier app conectada en Zapier).

  Flujo:
    1. Usuario pide algo que requiere un servicio externo
    2. ARIA llama a trigger(event, data) → POST al webhook de Zapier
    3. Zapier ejecuta el Zap configurado (ej: buscar productos en Shopify)
    4. Si el Zap tiene respuesta, llama al callback de ARIA (/zapier/callback)
    5. ARIA recibe el resultado y lo reporta al usuario

  Configuración requerida en Fly.io:
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

  # Tiempo máximo de espera para respuesta de callback (segundos)
  CALLBACK_TIMEOUT = 45
  # Clave Redis donde Zapier deposita callbacks
  CALLBACK_KEY_PREFIX = "aria:zapier:callback:"


  class ZapierClient:
      """
      Cliente para llamar a Zapier desde ARIA.

      Uso básico (fire-and-forget):
          zapier = get_zapier_client()
          result = await zapier.trigger("shopify.get_products", {"limit": 10})

      Uso con espera de respuesta:
          result = await zapier.trigger_and_wait("shopify.get_products", {"limit": 10})
          # result["data"] contiene lo que Zapier devolvió
      """

      def __init__(self) -> None:
          self._webhook_url = settings.ZAPIER_WEBHOOK_URL or ""
          self._base_url = settings.ARIA_BASE_URL or "https://aria-ai.fly.dev"
          self._http = httpx.AsyncClient(timeout=30.0)

      def is_configured(self) -> bool:
          return bool(self._webhook_url and self._webhook_url.startswith("http"))

      async def trigger(
          self,
          event: str,
          data: Optional[dict] = None,
          include_callback: bool = False,
      ) -> dict[str, Any]:
          """
          Dispara un evento en Zapier (fire-and-forget).

          Args:
              event: Nombre del evento, ej: "shopify.get_products", "gmail.send_email"
              data: Datos adicionales para el Zap
              include_callback: Si True, incluye URL de callback para que Zapier responda

          Returns:
              dict con success, status_code, request_id
          """
          if not self.is_configured():
              return {
                  "success": False,
                  "error": "ZAPIER_WEBHOOK_URL no está configurado en Fly.io secrets",
                  "hint": "Ejecuta: fly secrets set ZAPIER_WEBHOOK_URL='https://hooks.zapier.com/...'",
              }

          request_id = str(uuid.uuid4())[:8]
          payload = {
              "event": event,
              "data": data or {},
              "request_id": request_id,
              "source": "aria-ai",
              "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
          }

          if include_callback:
              payload["callback_url"] = f"{self._base_url}/zapier/callback"

          try:
              res = await self._http.post(
                  self._webhook_url,
                  json=payload,
                  headers={"Content-Type": "application/json"},
                  timeout=15.0,
              )
              success = res.status_code in (200, 201, 204)
              logger.info(
                  "[Zapier] trigger '%s' → HTTP %d (id: %s)",
                  event, res.status_code, request_id,
              )
              return {
                  "success": success,
                  "status_code": res.status_code,
                  "request_id": request_id,
                  "event": event,
                  "zapier_response": res.text[:200] if res.text else "",
              }
          except httpx.TimeoutException:
              return {"success": False, "error": "Timeout conectando con Zapier (>15s)", "event": event}
          except Exception as exc:
              logger.error("[Zapier] Error en trigger '%s': %s", event, exc)
              return {"success": False, "error": str(exc), "event": event}

      async def trigger_and_wait(
          self,
          event: str,
          data: Optional[dict] = None,
          timeout: int = CALLBACK_TIMEOUT,
      ) -> dict[str, Any]:
          """
          Dispara un evento en Zapier y espera la respuesta via callback.

          Requiere que el Zap esté configurado para llamar a:
          POST https://aria-ai.fly.dev/zapier/callback
          con body: {"request_id": "...", "result": {...}}
          """
          if not self.is_configured():
              return {"success": False, "error": "ZAPIER_WEBHOOK_URL no configurado"}

          request_id = str(uuid.uuid4())[:8]

          # 1. Disparar con callback
          trigger_result = await self.trigger(event, data, include_callback=True)
          if not trigger_result.get("success"):
              return trigger_result

          # 2. Esperar respuesta en Redis
          try:
              from apps.core.memory.redis_client import get_cache
              cache = get_cache()
              callback_key = CALLBACK_KEY_PREFIX + request_id

              deadline = time.time() + timeout
              while time.time() < deadline:
                  raw = await cache.get(callback_key)
                  if raw:
                      await cache.delete(callback_key)
                      result_data = json.loads(raw) if isinstance(raw, str) else raw
                      logger.info("[Zapier] Callback recibido para '%s' (id: %s)", event, request_id)
                      return {
                          "success": True,
                          "event": event,
                          "request_id": request_id,
                          "data": result_data,
                          "source": "zapier_callback",
                      }
                  await asyncio.sleep(1.5)

              return {
                  "success": False,
                  "error": f"Zapier no respondió en {timeout}s. El Zap puede estar ejecutándose aún.",
                  "event": event,
                  "request_id": request_id,
                  "tip": "Verifica en Zapier que el Zap tenga un paso 'Webhooks: POST' apuntando al callback_url.",
              }
          except Exception as exc:
              return {"success": False, "error": f"Error esperando callback: {exc}", "event": event}

      async def ping(self) -> dict[str, Any]:
          """Verifica que el webhook esté activo enviando un ping."""
          return await self.trigger("aria.ping", {"message": "Test de conectividad de ARIA"})


  # ── EVENTOS ESTÁNDAR ─────────────────────────────────────────
  # Convenios de nombres para los Zaps más comunes.
  # En Zapier, filtrar por el campo "event" para rutar a la acción correcta.

  class ZapierEvents:
      # Shopify
      SHOPIFY_GET_PRODUCTS    = "shopify.get_products"
      SHOPIFY_GET_ORDERS      = "shopify.get_orders"
      SHOPIFY_GET_INVENTORY   = "shopify.get_inventory"
      SHOPIFY_GET_REVENUE     = "shopify.get_revenue"
      SHOPIFY_CREATE_PRODUCT  = "shopify.create_product"

      # Gmail / Email
      GMAIL_SEND              = "gmail.send_email"
      GMAIL_GET_INBOX         = "gmail.get_inbox"

      # Google Sheets
      SHEETS_APPEND_ROW       = "sheets.append_row"
      SHEETS_GET_DATA         = "sheets.get_data"

      # Notificaciones
      NOTIFY_SLACK            = "notify.slack"
      NOTIFY_WHATSAPP         = "notify.whatsapp"

      # General
      PING                    = "aria.ping"
      REPORT                  = "aria.daily_report"


  # ── SINGLETON ────────────────────────────────────────────────
  _zapier_client: Optional[ZapierClient] = None


  def get_zapier_client() -> ZapierClient:
      global _zapier_client
      if _zapier_client is None:
          _zapier_client = ZapierClient()
      return _zapier_client
  