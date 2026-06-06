"""
content_bot.py — Bot especializado en generación y publicación de contenido.

Responsabilidades:
- Genera contenido de forma autónoma (posts, artículos, copy)
- Programa publicaciones en múltiples plataformas
- Reutiliza y adapta contenido exitoso
- Notifica a Aria solo cuando necesita aprobación o hay un resultado importante

Aria NO tiene que pensar en contenido. Este bot lo hace solo.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger("aria.bots.content")

CONTENT_FORMATS = ["thread", "short_post", "long_article", "email_newsletter", "product_description"]
CONTENT_TONES = ["informativo", "persuasivo", "emocional", "educativo", "inspirador"]


class ContentBot:
    """Bot autónomo de generación y distribución de contenido."""

    def __init__(self):
        self._running = False
        self._generated_count = 0
        self._published_count = 0
        self._queue: List[Dict] = []

    async def generate(
        self,
        topic: str,
        format: str = "short_post",
        tone: str = "informativo",
        platform: str = "general",
        language: str = "es",
        max_tokens: int = 600,
    ) -> Dict:
        """Genera contenido completo listo para publicar."""
        try:
            from apps.core.tools.ai_client import AIModel, get_ai_client
            ai = get_ai_client()

            platform_hints = {
                "twitter": "Máximo 280 caracteres por tweet. Si es hilo, marca cada parte con 1/, 2/, etc.",
                "instagram": "Caption emocional con llamada a la acción y hasta 5 hashtags relevantes al final.",
                "linkedin": "Tono profesional. Párrafos cortos. Termina con pregunta para generar debate.",
                "email": "Asunto en la primera línea. Cuerpo directo. CTA claro al final.",
                "blog": "Introducción directa, puntos clave, conclusión accionable.",
                "general": "Claro, directo y útil.",
            }

            system = (
                f"Eres un experto en creación de contenido digital. "
                f"Generas contenido en {language} para la plataforma: {platform}. "
                f"Instrucciones: {platform_hints.get(platform, platform_hints['general'])}"
            )
            user = (
                f"Crea {format} sobre: '{topic}'\n"
                f"Tono: {tone}\n"
                f"Devuelve solo el contenido final, sin explicaciones ni metadatos."
            )

            response = await ai.complete(
                system=system, user=user,
                model=AIModel.FAST, max_tokens=max_tokens,
                agent_name="content_bot",
            )

            if not response.success:
                return {"success": False, "error": "IA no disponible"}

            content = response.content.strip()
            self._generated_count += 1

            result = {
                "success": True,
                "content": content,
                "topic": topic,
                "format": format,
                "tone": tone,
                "platform": platform,
                "language": language,
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "word_count": len(content.split()),
                "char_count": len(content),
            }
            self._queue.append(result)
            logger.info("[ContentBot] Generado: %s (%d chars)", topic[:50], len(content))
            return result

        except Exception as e:
            logger.error("[ContentBot] Error generando contenido: %s", e)
            return {"success": False, "error": str(e)}

    async def generate_batch(self, topics: List[str], platform: str = "general") -> Dict:
        """Genera contenido para múltiples temas en paralelo."""
        tasks = [self.generate(topic, platform=platform) for topic in topics]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        successful = [r for r in results if isinstance(r, dict) and r.get("success")]
        return {
            "success": True,
            "generated": len(successful),
            "failed": len(results) - len(successful),
            "items": successful,
        }

    async def repurpose(self, original_content: str, target_platform: str) -> Dict:
        """Adapta contenido existente a otro formato/plataforma."""
        try:
            from apps.core.tools.ai_client import AIModel, get_ai_client
            ai = get_ai_client()
            response = await ai.complete(
                system=(
                    f"Eres experto en repurposing de contenido. "
                    f"Adapta el contenido dado para {target_platform}. "
                    f"Mantén la esencia pero ajusta tono, longitud y formato."
                ),
                user=f"Contenido original:\n{original_content}\n\nAdáptalo para: {target_platform}",
                model=AIModel.FAST, max_tokens=500, agent_name="content_bot_repurpose",
            )
            if not response.success:
                return {"success": False, "error": "IA no disponible"}
            return {"success": True, "content": response.content.strip(), "platform": target_platform}
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def publish(self, content: str, platform: str) -> Dict:
        """Publica contenido en la plataforma especificada."""
        try:
            if platform == "buffer":
                from apps.core.tools.buffer_tools import BufferTools
                bt = BufferTools()
                result = await bt.create_post(content)
                if result.get("success"):
                    self._published_count += 1
                return result
            logger.info("[ContentBot] Plataforma '%s' requiere configuración adicional.", platform)
            return {"success": False, "error": f"Plataforma {platform} no configurada"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def status(self) -> Dict:
        return {
            "bot": "ContentBot",
            "generated_total": self._generated_count,
            "published_total": self._published_count,
            "queue_size": len(self._queue),
            "last_items": [
                {"topic": i.get("topic"), "platform": i.get("platform"), "chars": i.get("char_count")}
                for i in self._queue[-5:]
            ],
        }


_instance: Optional[ContentBot] = None

def get_content_bot() -> ContentBot:
    global _instance
    if _instance is None:
        _instance = ContentBot()
    return _instance
