
import logging
from typing import Any, Dict, List
from apps.core.tools.ai_client import get_ai_client, AIModel

logger = logging.getLogger("aria.experiment")

class ExperimentEngine:
    """
    Motor de Experimentación.
    Diseña y ejecuta pruebas A/B para validar hipótesis de venta.
    """

    def __init__(self):
        self.ai = get_ai_client()

    async def design_ab_test(self, hypothesis: str, context: Dict[str, Any]) -> Dict[str, Any]:
        """
        Diseña un test A/B para validar una hipótesis.
        
        Ejemplo:
        Hipótesis: "Si cambio el precio de $99 a $79, la conversión subirá 30%"
        """
        prompt = f"""
        HIPÓTESIS: {hypothesis}
        CONTEXTO: {context}
        
        Diseña un test A/B riguroso:
        
        1. VARIANTE A (Control): Describe el estado actual
        2. VARIANTE B (Test): Describe el cambio propuesto
        3. MÉTRICA PRINCIPAL: ¿Qué mediremos?
        4. DURACIÓN: ¿Cuánto tiempo debe durar?
        5. TAMAÑO DE MUESTRA: ¿Cuántas personas necesitamos?
        6. CRITERIO DE ÉXITO: ¿Cuándo consideramos que ganó?
        
        Responde en JSON con: variant_a, variant_b, metric, duration_days, sample_size, success_criteria
        """
        
        test_design = await self.ai.complete_json(
            system="Eres un experto en Experimentación y Estadística.",
            user=prompt,
            model=AIModel.STRATEGY
        )
        
        return test_design if test_design else {"error": "Diseño fallido"}

    async def run_experiment(self, test_id: str, results: Dict[str, Any]) -> Dict[str, Any]:
        """Analiza los resultados de un experimento."""
        prompt = f"""
        RESULTADOS DEL TEST {test_id}:
        {results}
        
        Analiza:
        1. ¿Ganó A o B?
        2. ¿Es estadísticamente significativo?
        3. ¿Cuál es el impacto esperado si lo escalamos?
        4. ¿Qué aprendimos?
        
        Responde en JSON con: winner, significance, impact_if_scaled, learnings
        """
        
        analysis = await self.ai.complete_json(
            system="Eres un experto en análisis de datos experimentales.",
            user=prompt,
            model=AIModel.STRATEGY
        )
        
        return analysis if analysis else {"error": "Análisis fallido"}
