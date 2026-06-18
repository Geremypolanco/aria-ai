
import logging
from typing import Any, Dict, List
from apps.core.tools.ai_client import get_ai_client, AIModel
from apps.core.engines.market_scanner import MarketScanner
from apps.core.engines.revenue_attribution import RevenueAttributionEngine

logger = logging.getLogger("aria.executive")

class ExecutiveDecisionEngine:
    """
    Motor de Decisión Ejecutiva (CEO Layer).
    
    Orquesta TODAS las acciones de Aria basándose en:
    1. Oportunidades de mercado (Market Scanner)
    2. Desempeño actual (Revenue Attribution)
    3. ROI esperado de cada acción
    
    Responde: "¿Qué debemos hacer HOY para maximizar ingresos?"
    """

    def __init__(self):
        self.ai = get_ai_client()
        self.market_scanner = MarketScanner()
        self.attribution = RevenueAttributionEngine()

    async def make_daily_decision(self) -> Dict[str, Any]:
        """
        Toma la decisión ejecutiva diaria.
        
        Responde: ¿Qué hacer hoy? ¿Crear contenido? ¿Optimizar Shopify? ¿Hacer experimentos?
        """
        
        # 1. Obtener oportunidades de mercado
        opportunities = await self.market_scanner.scan_opportunities()
        
        # 2. Obtener desempeño actual
        top_content = await self.attribution.get_top_performing_content(5)
        revenue_graph = await self.attribution.get_revenue_graph_json()
        
        # 3. Usar IA para decidir
        prompt = f"""
        ESTADO ACTUAL DE ARIA:
        - Ingresos totales: ${revenue_graph.get('total_revenue', 0)}
        - Contenido creado: {revenue_graph.get('total_content_pieces', 0)}
        - Top performers: {top_content}
        
        OPORTUNIDADES DISPONIBLES:
        {opportunities}
        
        PREGUNTA EJECUTIVA:
        ¿Qué debería hacer Aria HOY para maximizar ingresos?
        
        Opciones:
        A) Crear más contenido en el nicho de mejor desempeño
        B) Optimizar el precio/descripción de Shopify
        C) Hacer experimentos A/B en las campañas actuales
        D) Pivotar a una oportunidad completamente nueva
        E) Escalar lo que ya funciona
        
        Responde en JSON con:
        - decision: A, B, C, D o E
        - reasoning: por qué
        - expected_roi: ROI esperado si ejecutamos
        - action_plan: pasos específicos
        """
        
        decision = await self.ai.complete_json(
            system="Eres el CEO de ARIA. Tu único objetivo es maximizar ingresos.",
            user=prompt,
            model=AIModel.STRATEGY
        )
        
        return decision if decision else {"error": "Decisión fallida"}

    async def evaluate_action_roi(self, action: str, context: Dict[str, Any]) -> float:
        """Evalúa el ROI esperado de una acción."""
        prompt = f"""
        ACCIÓN PROPUESTA: {action}
        CONTEXTO: {context}
        
        Estima el ROI esperado (0-10 escala).
        Responde SOLO con un número entre 0 y 10.
        """
        
        try:
            response = await self.ai.complete(
                system="Eres un experto en evaluación de ROI.",
                user=prompt,
                model=AIModel.FAST
            )
            roi = float(response.content.strip())
            return min(10, max(0, roi))
        except:
            return 0.0

    async def prioritize_actions(self, actions: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Ordena acciones por ROI esperado."""
        for action in actions:
            action["expected_roi"] = await self.evaluate_action_roi(
                action.get("name", ""),
                action
            )
        
        return sorted(actions, key=lambda x: x["expected_roi"], reverse=True)
