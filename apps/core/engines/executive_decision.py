import logging
from typing import Any

from apps.core.engines.market_scanner import MarketScanner
from apps.core.engines.revenue_attribution import RevenueAttributionEngine
from apps.core.tools.ai_client import AIModel, get_ai_client

logger = logging.getLogger("aria.executive")


class ExecutiveDecisionEngine:
    """
    Executive Decision Engine (CEO Layer).

    Orchestrates ALL of Aria's actions based on:
    1. Market opportunities (Market Scanner)
    2. Current performance (Revenue Attribution)
    3. Expected ROI of each action

    Answers: "What should we do TODAY to maximize revenue?"
    """

    def __init__(self):
        self.ai = get_ai_client()
        self.market_scanner = MarketScanner()
        self.attribution = RevenueAttributionEngine()

    async def make_daily_decision(self) -> dict[str, Any]:
        """
        Makes the daily executive decision.

        Answers: What to do today? Create content? Optimize Shopify? Run experiments?
        """

        # 1. Get market opportunities
        opportunities = await self.market_scanner.scan_opportunities()

        # 2. Get current performance
        top_content = await self.attribution.get_top_performing_content(5)
        revenue_graph = await self.attribution.get_revenue_graph_json()

        # 3. Use AI to decide
        prompt = f"""
        ARIA'S CURRENT STATE:
        - Total revenue: ${revenue_graph.get('total_revenue', 0)}
        - Content created: {revenue_graph.get('total_content_pieces', 0)}
        - Top performers: {top_content}

        AVAILABLE OPPORTUNITIES:
        {opportunities}

        EXECUTIVE QUESTION:
        What should Aria do TODAY to maximize revenue?

        Options:
        A) Create more content in the best-performing niche
        B) Optimize the Shopify price/description
        C) Run A/B experiments on current campaigns
        D) Pivot to a completely new opportunity
        E) Scale what's already working

        Respond in JSON with:
        - decision: A, B, C, D, or E
        - reasoning: why
        - expected_roi: expected ROI if we execute
        - action_plan: specific steps
        """

        decision = await self.ai.complete_json(
            system="You are the CEO of ARIA. Your only goal is to maximize revenue.",
            user=prompt,
            model=AIModel.STRATEGY,
        )

        return decision if decision else {"error": "Decision failed"}

    async def evaluate_action_roi(self, action: str, context: dict[str, Any]) -> float:
        """Evaluates the expected ROI of an action."""
        prompt = f"""
        PROPOSED ACTION: {action}
        CONTEXT: {context}

        Estimate the expected ROI (0-10 scale).
        Respond ONLY with a number between 0 and 10.
        """

        try:
            response = await self.ai.complete(
                system="You are an expert in ROI evaluation.", user=prompt, model=AIModel.FAST
            )
            roi = float(response.content.strip())
            return min(10, max(0, roi))
        except Exception:
            return 0.0

    async def prioritize_actions(self, actions: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Sorts actions by expected ROI."""
        for action in actions:
            action["expected_roi"] = await self.evaluate_action_roi(action.get("name", ""), action)

        return sorted(actions, key=lambda x: x["expected_roi"], reverse=True)
