import logging
from typing import Any

from apps.core.tools.ai_client import AIModel, get_ai_client
from apps.core.tools.web_tools import WebTools

logger = logging.getLogger("aria.viral")


class ViralAnalyzer:
    """
    Analizador de viralidad y mimetismo de contenido.
    Busca publicaciones exitosas y extrae sus patrones estructurales.
    """

    def __init__(self):
        self.web = WebTools()
        self.ai = get_ai_client()

    async def analyze_trending_formats(
        self, niche: str, platform: str = "linkedin"
    ) -> dict[str, Any]:
        """Busca publicaciones virales en un nicho y extrae su ADN estructural."""
        query = f"top viral {niche} posts on {platform} 2026 examples"
        search_results = await self.web.search_web(query, num_results=5)

        if not search_results.get("success"):
            return {"success": False, "error": "No se pudieron obtener resultados de búsqueda"}

        # Analizar los snippets y títulos para extraer patrones
        analysis_prompt = f"""
        Analiza estos resultados de búsqueda sobre publicaciones virales en {platform} para el nicho '{niche}':
        {search_results.get('results')}

        EXTRAE EL ADN VIRAL:
        1. Gancho (Hook): ¿Cómo empiezan las publicaciones más exitosas?
        2. Estructura: ¿Usan listas, storytelling, datos, o preguntas?
        3. Formato visual: ¿Mencionan imágenes, infografías o videos?
        4. Llamado a la acción (CTA): ¿Cómo cierran?

        Genera una PLANTILLA MAESTRA que ARIA pueda usar para replicar este éxito.
        Responde en JSON con: hook_style, body_structure, visual_recommendation, cta_style, example_template.
        """

        analysis = await self.ai.complete_json(
            system="Eres un experto en Growth Hacking y Viralidad Digital.",
            user=analysis_prompt,
            model=AIModel.STRATEGY,
        )

        return {"success": True, "platform": platform, "niche": niche, "viral_dna": analysis}

    async def find_high_value_digital_products(self, category: str) -> list[dict[str, Any]]:
        """Busca productos electrónicos de alto valor que estén siendo tendencia."""
        query = f"best selling high ticket digital products {category} shopify 2026"
        search_results = await self.web.search_web(query, num_results=5)
        return search_results.get("results", [])
