"""
Sales Agent — Revenue generation: products, payments, Shopify, Stripe, Gumroad.

Handles: product creation, pricing, checkout, upsells, affiliates,
        sales tracking, and conversion optimization.
"""

from __future__ import annotations

import logging
from typing import Any

from apps.core.agents.base_agent import BaseAgent

logger = logging.getLogger("aria.business.sales")


class SalesAgent(BaseAgent):
    IDENTITY = (
        "You are ARIA AI's Sales Agent, inspired by Claude Code. Your mission is to generate REAL revenue. "
        "GOLDEN RULE: Never sell something you cannot deliver. "
        "If the user asks to sell a physical product you don't own, you must decline it or propose a digital version (ebook, consulting, design). "
        "Before publishing, verify: 1. Is it real? 2. Do I have the deliverable ready? 3. Is the payment platform connected?"
    )

    def __init__(self) -> None:
        super().__init__(
            name="sales",
            description="Revenue: create products, process payments, optimize sales on Shopify/Stripe/Gumroad",
            capabilities=[
                "product_creation",
                "pricing",
                "shopify",
                "stripe",
                "gumroad",
                "upselling",
                "conversion_optimization",
                "affiliate_marketing",
            ],
        )

    async def _execute(self, context: dict[str, Any]) -> dict[str, Any]:
        mission = context.get("mission", "Create and publish a digital product")
        product_name = context.get("product_name", "")
        product_type = context.get("product_type", "digital")
        price = context.get("price", 0)
        platform = context.get("platform", "auto")
        auto_publish = context.get("auto_publish", False)

        # DELIVERABILITY CHECK (Claude Code Protocol)
        # NOTE: bilingual keyword list — matches mission text in Spanish or
        # English, do not translate the keyword strings below.
        is_physical = any(
            k in mission.lower() for k in ["casa", "físico", "envío", "hardware", "gadget"]
        )
        if is_physical and "digital" not in mission.lower():
            return {
                "success": False,
                "error": "I can't sell physical products (like houses or hardware) because I have no way to deliver them. I can create a digital version (blueprints, guides, consulting) if you'd like.",
                "agent": "sales",
            }

        results: dict[str, Any] = {"success": True, "agent": "sales", "mission": mission}

        # 1. If no product is defined, create one based on the mission
        if not product_name:
            product_idea = await self._ideate_product(mission)
            results["product_idea"] = product_idea
            product_name = product_idea.get("name", mission[:50])
            price = price or float(product_idea.get("price", 29))

        # 2. Generate sales copy
        sales_copy = await self._generate_sales_copy(product_name, product_type, mission)
        results["sales_copy"] = sales_copy

        # 3. Define pricing strategy
        pricing_strategy = await self._define_pricing(product_name, product_type, price)
        results["pricing"] = pricing_strategy

        # 4. Publish to platform if requested
        if auto_publish:
            pub = await self._publish_product(
                name=product_name,
                price=price,
                description=sales_copy.get("description", ""),
                platform=platform,
            )
            results["published"] = pub

        results["summary"] = f"Product '{product_name}' configured — suggested price ${price}. " + (
            "Published on " + results.get("published", {}).get("platform", "")
            if auto_publish
            else "Ready to publish."
        )
        return results

    async def _ideate_product(self, mission: str) -> dict:
        idea = await self.think(
            system=self.IDENTITY,
            user=(
                f"Mission: {mission}\n\n"
                f"Generate a high-margin digital product. Respond with JSON containing: "
                f"name, tagline, description (100 words), price (USD), target_audience, "
                f"unique_value_prop, platform (shopify|gumroad|stripe). "
                f"The product must be sellable today."
            ),
        )
        try:
            import json
            import re

            m = re.search(r"\{.*\}", idea, re.DOTALL)
            return json.loads(m.group()) if m else {"name": mission[:50], "price": 29}
        except Exception:
            return {"name": mission[:50], "price": 29}

    async def _generate_sales_copy(self, name: str, product_type: str, mission: str) -> dict:
        copy = await self.think(
            system=self.IDENTITY,
            user=(
                f"Product: {name} ({product_type})\nContext: {mission}\n\n"
                f"Write: headline (10 words), subheadline (20 words), "
                f"description (150 words), 5 bullet benefits, CTA button text, "
                f"FAQ (3 questions). Do not include testimonials or customer figures — "
                f"there is no real customer data yet; do not make it up."
            ),
        )
        return {"copy": copy, "product": name}

    async def _define_pricing(self, name: str, product_type: str, base_price: float) -> dict:
        strategy = await self.think(
            system=self.IDENTITY,
            user=(
                f"Product: {name} ({product_type}), base price: ${base_price}\n"
                f"Define: pricing tiers (basic/pro/enterprise), launch discounts, "
                f"upsell/cross-sell, and optimal psychological pricing. JSON format."
            ),
        )
        return {"strategy": strategy, "base_price": base_price}

    async def _publish_product(
        self, name: str, price: float, description: str, platform: str
    ) -> dict:
        """Publishes the product to the corresponding platform."""
        # Automatic platform selection
        if platform == "auto":
            from apps.core.config import settings

            if settings.GUMROAD_TOKEN:
                platform = "gumroad"
            elif settings.SHOPIFY_URL and settings.SHOPIFY_ADMIN_TOKEN:
                platform = "shopify"
            elif settings.STRIPE_SECRET_KEY:
                platform = "stripe"
            else:
                return {"success": False, "error": "No payment platform configured"}

        try:
            if platform == "gumroad":
                from apps.core.tools.gumroad_tools import GumroadTools

                return await GumroadTools().create_product(
                    name=name, price_cents=int(price * 100), description=description
                )
            if platform == "shopify":
                from apps.core.config import settings as _s
                from apps.core.integrations.shopify_engine import ShopifyEngine

                shop_url = _s.SHOPIFY_URL.replace("https://", "").rstrip("/")
                engine = ShopifyEngine(shop_name=shop_url, access_token=_s.SHOPIFY_ADMIN_TOKEN)
                import asyncio as _asyncio

                product_id = await _asyncio.get_event_loop().run_in_executor(
                    None,
                    lambda: engine.create_optimized_product(
                        {
                            "title": name,
                            "body_html": description,
                            "variants": [{"price": str(price)}],
                        }
                    ),
                )
                return {
                    "success": bool(product_id),
                    "product_id": product_id,
                    "platform": "shopify",
                }
            if platform == "stripe":
                from apps.core.tools.commerce_tools import CommerceTools

                return await CommerceTools().stripe_create_product(
                    name=name, description=description, price_cents=int(price * 100)
                )
            if platform == "square":
                from apps.core.integrations.square_engine import SquareEngine

                engine = SquareEngine()
                r = await engine.create_catalog_item(name, description, int(price * 100))
                if r.get("success"):
                    link = await engine.create_payment_link(
                        r["data"]["object"]["id"], name, int(price * 100)
                    )
                    return {
                        "success": True,
                        "product_id": r["data"]["object"]["id"],
                        "payment_link": link.get("payment_link"),
                        "platform": "square",
                    }
                return {"success": False, "error": r.get("error")}
            return {"success": False, "error": f"Unknown platform: {platform}"}
        except Exception as exc:
            logger.error("[SalesAgent] publish_product error: %s", exc)
            return {"success": False, "error": str(exc)}
