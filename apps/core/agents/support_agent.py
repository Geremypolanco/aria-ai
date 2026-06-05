"""
support_agent.py — Support Agent multilingüe con Google Translate + HuggingFace.
Soporte en 133 idiomas, detección automática, sentiment analysis de tickets.
"""
from __future__ import annotations
import logging
from typing import Any
from apps.core.agents.base_agent import BaseAgent
from apps.core.tools.ai_client import AIModel

logger = logging.getLogger("aria.support_agent")


class SupportAgent(BaseAgent):
    def __init__(self) -> None:
        super().__init__(
            name="support_agent",
            description="Soporte multilingüe — 133 idiomas, análisis de tickets, respuesta automática",
            capabilities=[
                "customer_support", "multilingual_response", "ticket_analysis",
                "faq_generation", "sentiment_escalation", "knowledge_base",
            ],
        )

    async def _execute(self, context: dict[str, Any]) -> dict[str, Any]:
        message   = context.get("message", "")
        user_id   = context.get("user_id", "")
        channel   = context.get("channel", "telegram")
        auto_mode = context.get("auto_mode", False)

        results: dict[str, Any] = {"success": True, "agent": "support_agent"}

        # Detectar idioma del mensaje
        detected_lang = await self._detect_language(message)
        results["detected_language"] = detected_lang

        # Análisis de sentimiento del ticket
        sentiment = await self._analyze_ticket_sentiment(message)
        results["ticket_sentiment"] = sentiment

        # Clasificar tipo de soporte
        ticket_type = await self._classify_ticket(message)
        results["ticket_type"] = ticket_type

        # Generar respuesta en el idioma del usuario
        response = await self._generate_multilingual_response(
            message, detected_lang, ticket_type, sentiment
        )
        results["response"] = response

        # Escalar si el sentimiento es muy negativo
        if sentiment.get("sentiment") == "negativo" and sentiment.get("confidence", 0) > 0.8:
            results["escalated"] = True
            await self._escalate_ticket(user_id, message, sentiment)

        await self._log("support_response", f"Canal: {channel} | Idioma: {detected_lang} | Tipo: {ticket_type}")
        return results

    async def _detect_language(self, text: str) -> str:
        """Detecta el idioma del mensaje usando HuggingFace o Google."""
        import asyncio
        try:
            from apps.core.tools.huggingface_suite import HuggingFaceSuite
            hf = HuggingFaceSuite()
            result = await hf.detect_language(text[:200])
            if result.get("success"):
                return result.get("language", "es")
        except Exception:
            pass
        try:
            from apps.core.tools.google_suite import GoogleSuite
            google = GoogleSuite()
            result = await google.detect_language(text[:200])
            if result.get("success"):
                return result.get("language", "es")
        except Exception:
            pass
        return "es"

    async def _analyze_ticket_sentiment(self, text: str) -> dict[str, Any]:
        """Analiza sentimiento del ticket para priorización."""
        try:
            from apps.core.tools.huggingface_suite import HuggingFaceSuite
            hf = HuggingFaceSuite()
            return await hf.analyze_sentiment(text[:512], multilingual=True)
        except Exception as exc:
            logger.warning("[SupportAgent] sentiment error: %s", exc)
            return {"sentiment": "neutro", "confidence": 0.5}

    async def _classify_ticket(self, text: str) -> str:
        """Clasifica el tipo de ticket de soporte."""
        try:
            from apps.core.tools.huggingface_suite import HuggingFaceSuite
            hf = HuggingFaceSuite()
            result = await hf.classify_zero_shot(
                text[:512],
                ["billing question", "technical issue", "feature request", "general inquiry", "complaint", "refund request"],
            )
            return result.get("best_label", "general inquiry") if isinstance(result, dict) else "general inquiry"
        except Exception:
            return "general inquiry"

    async def _generate_multilingual_response(
        self, message: str, language: str, ticket_type: str, sentiment: dict
    ) -> dict[str, Any]:
        """Genera respuesta en el idioma del usuario, traducida automáticamente."""
        # Generar respuesta en español primero
        response_es = await self.think(
            system=(
                "Eres el agente de soporte de ARIA AI, un sistema de negocio digital autónomo. "
                "Responde de forma empática, clara y concisa. "
                f"El ticket es de tipo: {ticket_type}. "
                f"Tono del usuario: {sentiment.get('sentiment','neutro')}."
            ),
            user=f"Usuario pregunta: {message}\n\nResponde en español, máximo 3 párrafos.",
            model=AIModel.FAST,
        )

        if not response_es:
            return {"text": "Gracias por contactarnos. Un agente revisará tu mensaje pronto.", "language": "es"}

        # Si el idioma detectado no es español, traducir la respuesta
        if language and language not in ("es", "spa", "es-ES", "es-MX"):
            try:
                from apps.core.tools.google_suite import GoogleSuite
                google = GoogleSuite()
                translated = await google.translate(response_es, target=language[:2], source="es")
                if translated.get("success"):
                    return {"text": translated["translated"], "original_es": response_es, "language": language}
            except Exception as exc:
                logger.warning("[SupportAgent] translate error: %s", exc)

        return {"text": response_es, "language": "es"}

    async def _escalate_ticket(self, user_id: str, message: str, sentiment: dict) -> None:
        """Escala ticket muy negativo para revisión humana."""
        try:
            from apps.core.memory.supabase_client import get_db
            db = get_db()
            await db.create_approval_request(
                agent="support_agent",
                action_type="escalated_ticket",
                description=f"Ticket negativo de usuario {user_id}: {message[:200]}",
                data={"user_id": user_id, "message": message, "sentiment": sentiment},
            )
        except Exception as exc:
            logger.error("[SupportAgent] escalate error: %s", exc)
