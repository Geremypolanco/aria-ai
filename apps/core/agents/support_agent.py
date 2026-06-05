"""
SupportAgent — Gestiona consultas de clientes, disputas y reviews.
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
            description="Soporte al cliente — consultas, disputas y reviews",
            capabilities=["inquiry_handling", "dispute_resolution", "review_monitoring"],
        )

    async def _execute(self, context: dict[str, Any]) -> dict[str, Any]:
        task = context.get("task", "monitor")
        if "dispute" in task.lower():
            return await self.process_dispute(context)
        if "review" in task.lower():
            return await self.monitor_reviews(context.get("platform", "gumroad"))
        return await self.handle_inquiry(context.get("message", ""), context.get("language", "en"))

    async def handle_inquiry(self, message: str, language: str = "en") -> dict[str, Any]:
        """Responde automáticamente a preguntas frecuentes."""
        if not message:
            return {"success": True, "response": "No message provided"}

        response = await self.think(
            system=(
                "Eres un agente de soporte al cliente amable, profesional y eficiente. "
                "Representas a Aria AI, un sistema de productos digitales autónomo. "
                "Responde de forma concisa, útil y empática. "
                "Si no puedes resolver el problema, escala al supervisor humano."
            ),
            user=(
                f"Idioma: {language}\n"
                f"Mensaje del cliente: {message}\n\n"
                "Responde al cliente de forma profesional y resuelve su consulta."
            ),
            model=AIModel.FAST,
        )

        should_escalate = any(kw in message.lower() for kw in [
            "refund", "reembolso", "fraud", "fraude", "legal", "lawsuit",
            "demanda", "estafa", "scam",
        ])

        result: dict[str, Any] = {
            "success": True,
            "agent": "support_agent",
            "response": response or "Gracias por contactarnos. Un agente revisará tu caso pronto.",
            "escalated": should_escalate,
        }

        if should_escalate:
            await self._send_telegram(
                f"🚨 <b>ESCALACIÓN SOPORTE</b>\n\n"
                f"<b>Mensaje:</b> {message[:300]}\n\n"
                f"<b>Respuesta automática:</b> {(response or '')[:200]}"
            )

        await self._log("inquiry_handled", f"Escalado: {should_escalate}")
        return result

    async def process_dispute(self, context: dict[str, Any]) -> dict[str, Any]:
        """Gestiona disputas de pago."""
        customer = context.get("customer", "Cliente")
        amount = context.get("amount", 0.0)
        reason = context.get("reason", "No especificado")
        platform = context.get("platform", "stripe")

        resolution = await self.think(
            system="Eres un especialista en resolución de disputas y pagos digitales.",
            user=(
                f"Cliente: {customer}\n"
                f"Monto en disputa: ${amount:.2f} USD\n"
                f"Razón: {reason}\n"
                f"Plataforma: {platform}\n\n"
                "Propón la mejor resolución para proteger la reputación del negocio y resolver el caso."
            ),
            model=AIModel.STRATEGY,
        )

        # Notificar al supervisor para disputas > $10
        if amount > 10.0:
            await self.request_approval(
                action=f"Resolver disputa ${amount:.2f} de {customer}",
                details=f"Razón: {reason} | Resolución propuesta: {(resolution or '')[:200]}",
                amount_usd=amount,
            )

        await self._log("dispute_processed", f"Cliente: {customer} | Monto: ${amount:.2f}")
        return {
            "success": True,
            "agent": "support_agent",
            "customer": customer,
            "amount": amount,
            "resolution": resolution,
            "escalated_to_human": amount > 10.0,
        }

    async def monitor_reviews(self, platform: str = "gumroad") -> dict[str, Any]:
        """Monitorea y responde a reviews de productos."""
        reviews = await self._fetch_reviews(platform)
        if not reviews:
            return {"success": True, "agent": "support_agent", "reviews_processed": 0}

        responses = []
        for review in reviews[:5]:  # Procesar max 5 por ciclo
            rating = review.get("rating", 5)
            content = review.get("content", "")

            if rating <= 2:  # Review negativa
                response = await self.handle_inquiry(
                    f"Reseña negativa: {content}", review.get("language", "en")
                )
                responses.append({"review": review, "response": response, "type": "negative"})
                await self._send_telegram(
                    f"⭐ <b>REVIEW NEGATIVA ({rating}/5)</b>\n\n{content[:200]}"
                )
            else:
                responses.append({"review": review, "type": "positive"})

        await self._log("reviews_monitored", f"Platform: {platform} | Reviews: {len(responses)}")
        return {
            "success": True,
            "agent": "support_agent",
            "platform": platform,
            "reviews_processed": len(responses),
            "responses": responses,
        }

    async def _fetch_reviews(self, platform: str) -> list[dict[str, Any]]:
        """Obtiene reviews de la plataforma especificada."""
        # Placeholder — integración real con cada plataforma
        return []
