import logging
import httpx
from typing import Any, Optional
from apps.core.config import settings

logger = logging.getLogger("aria.tools.zapier")

class ZapierConnector:
    """
    Permite a ARIA comunicarse con Zapier mediante Webhooks.
    Esto abre la puerta a +6000 integraciones automáticas.
    """
    
    def __init__(self):
        self.timeout = 15.0

    async def trigger_webhook(self, webhook_url: str, data: dict[str, Any]) -> dict[str, Any]:
        """Envía datos a un webhook de Zapier."""
        if not webhook_url:
            return {"success": False, "error": "URL de Webhook no proporcionada"}
            
        logger.info("[Zapier] Enviando trigger a: %s", webhook_url)
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.post(webhook_url, json=data)
                resp.raise_for_status()
                return {
                    "success": True, 
                    "status_code": resp.status_code,
                    "response": resp.text
                }
        except Exception as exc:
            logger.error("[Zapier] Error en trigger: %s", exc)
            return {"success": False, "error": str(exc)}

    async def test_connection(self, webhook_url: str) -> dict[str, Any]:
        """Prueba la conexión enviando un ping de ARIA."""
        test_data = {
            "source": "ARIA AI",
            "event": "connection_test",
            "message": "¡Hola Zapier! ARIA está conectada y lista para trabajar.",
            "status": "online"
        }
        return await self.trigger_webhook(webhook_url, test_data)
