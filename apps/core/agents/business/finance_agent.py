"""
Finance Agent — Autonomous revenue tracking, cost analysis, P&L, and forecasting.
"""

from __future__ import annotations

import logging
from typing import Any

from apps.core.agents.base_agent import BaseAgent

logger = logging.getLogger("aria.business.finance")


class FinanceAgent(BaseAgent):
    IDENTITY = (
        "You are ARIA AI's Finance Agent. You track revenue, costs, and P&L in real time. "
        "You generate forecasts, detect savings opportunities, and raise alerts when the numbers "
        "don't add up. You operate with real data from Stripe, PayPal, and Shopify."
    )

    def __init__(self) -> None:
        super().__init__(
            name="finance",
            description="Revenue tracking, P&L, forecasting, cost analysis, and financial metrics",
            capabilities=[
                "revenue_tracking",
                "cost_analysis",
                "forecasting",
                "stripe_analytics",
                "shopify_analytics",
                "pl_statement",
            ],
        )

    async def _execute(self, context: dict[str, Any]) -> dict[str, Any]:
        mission = context.get("mission", "Generar reporte financiero")
        period = context.get("period", "month")  # day|week|month|quarter
        context.get("include", ["revenue", "costs", "forecast"])

        results: dict[str, Any] = {"success": True, "agent": "finance", "period": period}

        # Recopilar datos reales de plataformas de pago
        revenue_data = await self._gather_revenue(period)
        results["revenue"] = revenue_data

        # Análisis con IA
        analysis = await self.think(
            system=self.IDENTITY,
            user=(
                f"Misión: {mission}\nPeriodo: {period}\n"
                f"Datos de revenue: {revenue_data}\n\n"
                f"Genera: P&L simplificado, métricas clave (MRR, ARR, LTV, CAC), "
                f"tendencia vs período anterior, top 3 oportunidades de crecimiento, "
                f"alertas si alguna métrica está en riesgo."
            ),
        )
        results["analysis"] = analysis
        results["summary"] = analysis[:300] if analysis else "Análisis financiero completado"
        return results

    async def _gather_revenue(self, period: str) -> dict:
        """Recopila datos reales de Stripe, Shopify, Gumroad."""
        revenue: dict = {"sources": {}, "total_usd": 0}
        from apps.core.config import settings

        # Stripe
        if settings.STRIPE_SECRET_KEY:
            try:
                from apps.core.tools.commerce_tools import CommerceTools

                stripe_data = await CommerceTools().stripe_get_revenue()
                if stripe_data.get("success"):
                    revenue["sources"]["stripe"] = stripe_data
                    revenue["total_usd"] += stripe_data.get("total_usd", 0)
            except Exception as exc:
                revenue["sources"]["stripe"] = {"error": str(exc)}

        # Shopify
        if settings.SHOPIFY_URL and settings.SHOPIFY_ADMIN_TOKEN:
            try:
                from apps.core.integrations.shopify_engine import ShopifyEngine

                shop_url = settings.SHOPIFY_URL.replace("https://", "").rstrip("/")
                engine = ShopifyEngine(
                    shop_name=shop_url, access_token=settings.SHOPIFY_ADMIN_TOKEN
                )
                import asyncio as _asyncio

                shop_data = await _asyncio.get_event_loop().run_in_executor(
                    None, lambda: engine.get_orders_report(limit=50)
                )
                if shop_data:
                    revenue["sources"]["shopify"] = shop_data
                    revenue["total_usd"] += shop_data.get("total_revenue", 0)
            except Exception as exc:
                revenue["sources"]["shopify"] = {"error": str(exc)}

        return revenue
