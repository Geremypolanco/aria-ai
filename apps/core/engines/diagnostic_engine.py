
import logging
from typing import Any, Dict
from apps.core.tools.ai_client import get_ai_client, AIModel

logger = logging.getLogger("aria.diagnostic")

class DiagnosticEngine:
    """
    Motor de Diagnóstico.
    Analiza por qué algo no está funcionando (ventas, conversión, tráfico).
    """

    def __init__(self):
        self.ai = get_ai_client()

    async def diagnose_sales_failure(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """
        Diagnostica por qué una campaña de ventas está fallando.
        
        Recibe: producto, tráfico, conversión, precio, plataforma
        Retorna: causa raíz probable + hipótesis alternativas
        """
        prompt = f"""
        CONTEXTO DE VENTA:
        {context}
        
        PREGUNTA: ¿Por qué no está vendiendo?
        
        ANALIZA:
        1. Precio (¿está fuera de mercado?)
        2. Descripción (¿es poco convincente?)
        3. Imágenes (¿son de baja calidad?)
        4. Público (¿es el público correcto?)
        5. Timing (¿es el momento correcto?)
        6. Competencia (¿hay competidores más fuertes?)
        
        Responde en JSON con:
        - root_cause: causa más probable
        - hypothesis_a, hypothesis_b, hypothesis_c: hipótesis alternativas
        - confidence_score: 0-100
        - recommended_tests: lista de experimentos para validar
        """
        
        diagnosis = await self.ai.complete_json(
            system="Eres un experto en diagnóstico de fallos en e-commerce.",
            user=prompt,
            model=AIModel.STRATEGY
        )
        
        return diagnosis if diagnosis else {"error": "Diagnóstico fallido"}

    async def diagnose_low_engagement(self, content_data: Dict[str, Any]) -> Dict[str, Any]:
        """Diagnostica por qué el contenido tiene bajo engagement."""
        prompt = f"""
        DATOS DE CONTENIDO:
        {content_data}
        
        ¿Por qué este contenido tiene bajo engagement?
        
        Analiza:
        1. Formato (¿es el formato correcto para la plataforma?)
        2. Timing (¿se publicó en el horario correcto?)
        3. Copywriting (¿el mensaje es débil?)
        4. Visual (¿la imagen/video es atractiva?)
        5. Audiencia (¿es el público correcto?)
        
        Responde en JSON con: root_cause, hypotheses, confidence, next_tests
        """
        
        diagnosis = await self.ai.complete_json(
            system="Eres un experto en Social Media Analytics.",
            user=prompt,
            model=AIModel.STRATEGY
        )
        
        return diagnosis if diagnosis else {"error": "Diagnóstico fallido"}
