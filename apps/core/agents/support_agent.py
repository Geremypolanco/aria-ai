"""
support_agent.py — Multilingual Support Agent with Google Translate + HuggingFace.
Support in 133 languages, automatic detection, ticket sentiment analysis.
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
            name="support",
            description="Multilingual support — 133 languages, ticket analysis, automatic response",
            capabilities=[
                "customer_support",
                "multilingual_response",
                "ticket_analysis",
                "faq_generation",
                "sentiment_escalation",
                "knowledge_base",
            ],
        )

    async def _execute(self, context: dict[str, Any]) -> dict[str, Any]:
        message = context.get("message", "")
        user_id = context.get("user_id", "")
        channel = context.get("channel", "telegram")
        context.get("auto_mode", False)

        results: dict[str, Any] = {"success": True, "agent": "support_agent"}

        # Detect the message language
        detected_lang = await self._detect_language(message)
        results["detected_language"] = detected_lang

        # Ticket sentiment analysis
        sentiment = await self._analyze_ticket_sentiment(message)
        results["ticket_sentiment"] = sentiment

        # Classify support type
        ticket_type = await self._classify_ticket(message)
        results["ticket_type"] = ticket_type

        # Generate a response in the user's language
        response = await self._generate_multilingual_response(
            message, detected_lang, ticket_type, sentiment
        )
        results["response"] = response

        # Escalate if the sentiment is very negative
        # (value is real HF-model output data, not translatable prose — left as-is)
        if sentiment.get("sentiment") == "negativo" and sentiment.get("confidence", 0) > 0.8:
            results["escalated"] = True
            await self._escalate_ticket(user_id, message, sentiment)

        await self._log(
            "support_response", f"Channel: {channel} | Language: {detected_lang} | Type: {ticket_type}"
        )
        return results

    async def _detect_language(self, text: str) -> str:
        """Detects the message language using HuggingFace or Google."""
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
        """Analyzes ticket sentiment for prioritization."""
        try:
            from apps.core.tools.huggingface_suite import HuggingFaceSuite

            hf = HuggingFaceSuite()
            return await hf.analyze_sentiment(text[:512], multilingual=True)
        except Exception as exc:
            logger.warning("[SupportAgent] sentiment error: %s", exc)
            # "neutro" matches the real value the HF suite returns — not translatable prose
            return {"sentiment": "neutro", "confidence": 0.5}

    async def _classify_ticket(self, text: str) -> str:
        """Classifies the support ticket type."""
        try:
            from apps.core.tools.huggingface_suite import HuggingFaceSuite

            hf = HuggingFaceSuite()
            result = await hf.classify_zero_shot(
                text[:512],
                [
                    "billing question",
                    "technical issue",
                    "feature request",
                    "general inquiry",
                    "complaint",
                    "refund request",
                ],
            )
            return (
                result.get("best_label", "general inquiry")
                if isinstance(result, dict)
                else "general inquiry"
            )
        except Exception:
            return "general inquiry"

    async def _generate_multilingual_response(
        self, message: str, language: str, ticket_type: str, sentiment: dict
    ) -> dict[str, Any]:
        """Generates a response in the user's language, automatically translated."""
        # Generate the response in Spanish first
        response_es = await self.think(
            system=(
                "You are ARIA AI's support agent, an autonomous digital business system. "
                "Respond empathetically, clearly, and concisely. "
                f"The ticket type is: {ticket_type}. "
                f"User tone: {sentiment.get('sentiment','neutro')}."
            ),
            user=f"User asks: {message}\n\nRespond in Spanish, maximum 3 paragraphs.",
            model=AIModel.FAST,
        )

        if not response_es:
            return {
                "text": "Thank you for contacting us. An agent will review your message soon.",
                "language": "es",
            }

        # If the detected language is not Spanish, translate the response
        if language and language not in ("es", "spa", "es-ES", "es-MX"):
            try:
                from apps.core.tools.google_suite import GoogleSuite

                google = GoogleSuite()
                translated = await google.translate(response_es, target=language[:2], source="es")
                if translated.get("success"):
                    return {
                        "text": translated["translated"],
                        "original_es": response_es,
                        "language": language,
                    }
            except Exception as exc:
                logger.warning("[SupportAgent] translate error: %s", exc)

        return {"text": response_es, "language": "es"}

    async def _escalate_ticket(self, user_id: str, message: str, sentiment: dict) -> None:
        """Escalates a very negative ticket for human review."""
        try:
            from apps.core.memory.supabase_client import get_db

            db = get_db()
            await db.create_approval_request(
                agent="support_agent",
                action_type="escalated_ticket",
                description=f"Negative ticket from user {user_id}: {message[:200]}",
                data={"user_id": user_id, "message": message, "sentiment": sentiment},
            )
        except Exception as exc:
            logger.error("[SupportAgent] escalate error: %s", exc)
