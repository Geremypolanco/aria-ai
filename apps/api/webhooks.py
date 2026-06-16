"""
webhooks.py — Manejador de Webhooks para ARIA.

Permite recibir eventos de Zapier, GitHub y otras aplicaciones externas para
disparar tareas automáticamente en el orquestador.
"""

import logging
from typing import Any, Dict, Optional

from fastapi import APIRouter, Header, HTTPException, Request
from pydantic import BaseModel

from apps.core.agents.orchestrator import Orchestrator as AriaOrchestrator

logger = logging.getLogger("aria.webhooks")
router = APIRouter(prefix="/api/webhooks", tags=["webhooks"])

# Instancia global del orquestador (debería ser inyectada o compartida)
orchestrator = AriaOrchestrator()


class ZapierPayload(BaseModel):
    """Estructura del payload enviado por Zapier."""
    action: str
    task: str
    data: Optional[Dict[str, Any]] = None
    user_id: Optional[str] = "default"


@router.post("/zapier")
async def handle_zapier_webhook(
    payload: ZapierPayload,
    x_zapier_signature: Optional[str] = Header(None)
):
    """
    Recibe un webhook de Zapier para ejecutar una tarea en Aria.
    
    Ejemplo de flujo:
    1. Un correo llega a Gmail.
    2. Zapier captura el evento.
    3. Zapier envía un POST a este endpoint con la tarea: "Analiza este correo y crea un resumen".
    """
    logger.info(f"[Webhook] Recibida petición de Zapier: {payload.action}")
    
    # Validar firma (opcional pero recomendado)
    # if not validate_signature(payload, x_zapier_signature):
    #     raise HTTPException(status_code=401, detail="Invalid signature")

    # Ejecutar tarea en el orquestador de forma asíncrona
    # En una implementación real, esto se enviaría a una cola de tareas (Redis/Celery)
    context = {
        "task": payload.task,
        "user_context": {
            "source": "zapier",
            "action": payload.action,
            "data": payload.data
        }
    }
    
    # Por ahora, ejecutamos y devolvemos el resultado inicial
    try:
        # En producción, esto debería ser asíncrono y devolver un ID de tarea
        result = await orchestrator.execute_task(payload.task, context["user_context"])
        return {
            "success": True,
            "message": "Tarea recibida y procesada",
            "task_id": "zap_" + str(hash(payload.task))[:8],
            "result": result
        }
    except Exception as exc:
        logger.error(f"[Webhook] Error procesando tarea de Zapier: {exc}")
        return {"success": False, "error": str(exc)}


@router.post("/generic")
async def handle_generic_webhook(request: Request):
    """Manejador genérico para cualquier otra integración."""
    data = await request.json()
    logger.info(f"[Webhook] Recibido evento genérico: {data}")
    return {"status": "received"}


def validate_signature(payload: Any, signature: str) -> bool:
    """Valida que la petición venga realmente de Zapier."""
    # Implementación real usando una clave compartida guardada en SecretsManager
    return True
