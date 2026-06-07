import logging
import httpx
import time
from typing import Any, Optional, Dict
from apps.core.config import settings

logger = logging.getLogger("aria.tools.zapier")

class ZapierConnector:
    """
    Conector Universal para Zapier.
    Permite a ARIA interactuar con +6000 aplicaciones conectadas en Zapier.
    """
    
    def __init__(self):
        self.timeout = 30.0
        # Priorizamos la URL de settings, si no, usamos el fallback del usuario
        self.webhook_url = getattr(settings, "ZAPIER_WEBHOOK_URL", None)  # Requiere ZAPIER_WEBHOOK_URL configurado explícitamente en Fly.io

    async def trigger_action(self, action_name: str, app_name: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        Dispara una acción específica en una app de Zapier.
        """
        payload = {
            "source": "ARIA AI Universal Connector",
            "target_app": app_name,
            "action": action_name,
            "timestamp": time.time(),
            "params": params,
            "context": {
                "environment": getattr(settings, "ENVIRONMENT", "production"),
                "aria_version": "2.5.0"
            }
        }
        
        logger.info("[Zapier] Disparando acción universal: %s en %s", action_name, app_name)
        return await self._send_to_zapier(payload)

    async def dispatch_event(self, event_type: str, data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Despacha un evento genérico para que Zapier lo rutee a cualquier app.
        """
        payload = {
            "source": "ARIA AI",
            "event_type": event_type,
            "timestamp": time.time(),
            "data": data
        }
        
        # Soporte para medios (imágenes/videos generados por ARIA)
        if "image_url" in data:
            payload["media"] = {"url": data["image_url"], "type": "image"}
        
        logger.info("[Zapier] Despachando evento: %s", event_type)
        return await self._send_to_zapier(payload)

    async def _send_to_zapier(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        # Desactivado por petición del usuario para priorizar APIs directas
        return {"success": False, "error": "Zapier desactivado. Aria ahora utiliza APIs directas."}
        
        if not self.webhook_url:
            return {"success": False, "error": "ZAPIER_WEBHOOK_URL no configurada en Fly.io secrets"}
            
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.post(self.webhook_url, json=payload)
                resp.raise_for_status()
                return {
                    "success": True, 
                    "status": resp.status_code,
                    "zapier_response": resp.text[:200]
                }
        except Exception as exc:
            logger.error("[Zapier] Error de conexión: %s", exc)
            return {"success": False, "error": str(exc)}

    async def trigger_webhook(self, webhook_url: str, data: Dict[str, Any]) -> Dict[str, Any]:
        """Mantenemos compatibilidad con el método anterior."""
        return await self.dispatch_event("GENERIC_TRIGGER", data)
