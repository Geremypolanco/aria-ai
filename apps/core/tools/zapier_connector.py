import logging
import httpx
from typing import Any, Optional
from apps.core.config import settings

logger = logging.getLogger("aria.tools.zapier")

class ZapierConnector:
    """
    Conector avanzado para Zapier.
    Maneja eventos globales y asegura que ARIA pueda disparar automatizaciones complejas.
    """
    
    # Tipos de eventos soportados
    EVENT_NEW_PRODUCT = "NEW_PRODUCT"
    EVENT_CONTENT_READY = "CONTENT_READY"
    EVENT_SALE_ALERT = "SALE_ALERT"
    EVENT_SYSTEM_ERROR = "SYSTEM_ERROR"
    EVENT_CREATION_READY = "CREATION_READY"

    def __init__(self):
        self.timeout = 20.0
        self.webhook_url = getattr(settings, "ZAPIER_WEBHOOK_URL", None) or "https://hooks.zapier.com/hooks/catch/23373923/4bp3cpt/"

    async def dispatch_event(self, event_type: str, data: dict[str, Any]) -> dict[str, Any]:
        """
        Despacha un evento específico a Zapier.
        Asegura que el payload incluya metadatos de ARIA.
        """
        if not self.webhook_url:
            return {"success": False, "error": "URL de Webhook no configurada"}
            
        payload = {
            "source": "ARIA AI",
            "event_type": event_type,
            "timestamp": data.get("timestamp"),
            "data": data
        }
        
        # Enriquecimiento automático si hay imágenes de HF
        if "image_url" in data:
            payload["has_media"] = True
            payload["media_url"] = data["image_url"]
            payload["media_type"] = "image/hf"

        logger.info("[Zapier] Despachando evento %s", event_type)
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.post(self.webhook_url, json=payload)
                resp.raise_for_status()
                return {"success": True, "status": resp.status_code}
        except Exception as exc:
            logger.error("[Zapier] Error despachando evento: %s", exc)
            return {"success": False, "error": str(exc)}

    async def trigger_webhook(self, webhook_url: str, data: dict[str, Any]) -> dict[str, Any]:
        """Mantenemos compatibilidad con el método anterior."""
        return await self.dispatch_event("GENERIC_TRIGGER", data)
