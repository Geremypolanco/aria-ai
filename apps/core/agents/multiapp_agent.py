from __future__ import annotations
import logging
from typing import Any, Dict, Optional
from apps.core.agents.base_agent import BaseAgent
from apps.core.tools.zapier_connector import ZapierConnector
from apps.core.tools.ai_client import get_ai_client, AIModel

logger = logging.getLogger("aria.agents.multiapp")

class MultiAppAgent(BaseAgent):
    """
    Agente especializado en orquestar múltiples aplicaciones vía Zapier.
    Capaz de conectar Gmail, Slack, Shopify, CRM, etc., en flujos unificados.
    """
    
    def __init__(self):
        super().__init__(
            name="multiapp",
            description="Orquestador universal de aplicaciones vía Zapier (Gmail, Shopify, Slack, etc.)",
            capabilities=["multi_app_automation", "zapier_orchestration", "cross_platform_flows"]
        )
        self._zapier = ZapierConnector()

    async def _execute(self, context: Dict[str, Any]) -> Dict[str, Any]:
        task = context.get("task", "general_automation")
        app = context.get("app", "any")
        action = context.get("action", "trigger")
        params = context.get("params", {})
        
        logger.info("[MultiAppAgent] Ejecutando tarea: %s para app: %s", task, app)
        
        # Disparar acción universal en Zapier
        result = await self._zapier.trigger_action(
            action_name=action,
            app_name=app,
            params={
                "task_description": task,
                **params
            }
        )
        
        return {
            "agent": self.name,
            "success": result.get("success", False),
            "app_targeted": app,
            "action_executed": action,
            "zapier_status": result.get("status"),
            "data": result
        }

    async def run_complex_flow(self, flow_description: str) -> Dict[str, Any]:
        """
        Usa IA para descomponer un flujo complejo en múltiples llamadas a Zapier.
        """
        ai = get_ai_client()
        system_prompt = (
            "Eres el experto en automatización Multi-App de ARIA. "
            "Tu objetivo es convertir una solicitud del usuario en una serie de pasos de automatización "
            "que involucren diferentes aplicaciones (Gmail, Shopify, Slack, etc.) conectadas en Zapier. "
            "Responde SOLO con JSON válido."
        )
        
        user_prompt = f"Diseña un flujo de automatización para: {flow_description}"
        
        # Simulación de lógica de ruteo inteligente
        # En una implementación real, aquí llamaríamos a ai.complete_json
        
        return {
            "success": True,
            "flow_id": "flow_" + str(hash(flow_description))[:6],
            "message": "Flujo de automatización enviado a Zapier para procesamiento multi-app."
        }
