"""
CFOAgent — Chief Financial Officer Agent
Creates and publishes digital products, manages payments, and records revenue.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from apps.core.agents.base_agent import BaseAgent
from apps.core.config import settings
from apps.core.tools.ai_client import AIModel

logger = logging.getLogger("aria.cfo_agent")


class CFOAgent(BaseAgent):
    def __init__(self) -> None:
        super().__init__(
            name="cfo",
            description="CFO — digital products, payments, and revenue",
            capabilities=["ebook_creation", "gumroad", "stripe", "shopify", "revenue_tracking"],
        )

    async def _execute(self, context: dict[str, Any]) -> dict[str, Any]:
        context.get("task", "")
        market_focus = context.get("market_focus", "digital products")
        language = context.get("primary_language", "en")

        ebook = await self.create_ebook(market_focus, language)
        if not ebook:
            return {"success": False, "error": "Could not generate the ebook"}

        results: dict[str, Any] = {"success": True, "agent": "cfo_agent", "ebook": ebook}

        # Publish to Gumroad (requires approval if price > 0)
        if settings.GUMROAD_TOKEN and ebook.get("price_usd", 0) > 0:
            gumroad_result = await self.execute_with_approval(
                action="Publish ebook to Gumroad",
                details=f"Title: {ebook['title']} | Price: ${ebook['price_usd']}",
                fn=lambda: self.publish_to_gumroad(ebook),
                amount_usd=0.0,  # No cost, generates revenue
            )
            results["gumroad"] = gumroad_result

        # Create payment link in Stripe
        if settings.STRIPE_SECRET_KEY:
            stripe_result = await self.create_payment_link(
                name=ebook["title"],
                price_usd=ebook["price_usd"],
                description=ebook["description"],
            )
            results["stripe"] = stripe_result

        return results

    async def create_ebook(self, niche: str, language: str) -> dict[str, Any] | None:
        """Generates the full content of an ebook using AI."""
        meta = await self.think(
            system="You are an expert in information marketing and creating high-value digital products.",
            user=(
                f"Niche: {niche} | Language: {language}\n\n"
                "Create the metadata for an ebook that can be sold for $7-$27 USD. JSON:\n"
                '{"title": "...", "subtitle": "...", "description": "...", '
                '"price_usd": 9.99, "pages_estimate": 30, '
                '"chapter_titles": ["Chapter 1", "Chapter 2", "Chapter 3", "Chapter 4", "Chapter 5"], '
                '"target_audience": "...", "unique_value_proposition": "...", '
                '"keywords": ["kw1", "kw2", "kw3"]}'
            ),
            model=AIModel.STRATEGY,
            json_mode=True,
        )
        if not meta:
            return None

        # Generate content for the first 2 chapters
        content = await self.think(
            system="You are an expert writer of non-fiction books focused on practical results.",
            user=(
                f"Write the introduction and first chapter of the ebook '{meta.get('title', '')}' "
                f"about '{niche}'. Language: {language}. "
                "Be practical, with real examples and actionable steps. Minimum 800 words."
            ),
            model=AIModel.CREATIVE,
        )
        meta["sample_content"] = content or ""
        meta["niche"] = niche
        meta["language"] = language
        logger.info(
            "[CFOAgent] Ebook created: %s | $%.2f", meta.get("title"), meta.get("price_usd", 0)
        )
        return meta

    async def publish_to_gumroad(self, ebook: dict[str, Any]) -> dict[str, Any]:
        """Publishes the ebook to Gumroad via API."""
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                res = await client.post(
                    "https://api.gumroad.com/v2/products",
                    data={
                        "access_token": settings.GUMROAD_TOKEN,
                        "name": ebook["title"],
                        "description": ebook["description"],
                        "price": int(ebook.get("price_usd", 9.99) * 100),  # cents
                        "url": "https://gumroad.com",
                        "published": "true",
                    },
                )
                if res.status_code == 201:
                    data = res.json().get("product", {})
                    url = data.get("short_url", "")
                    logger.info("[CFOAgent] Published to Gumroad: %s", url)
                    # Do NOT register revenue here — this only confirms the
                    # LISTING was created (HTTP 201), not that anyone bought
                    # it. Recording ebook["price_usd"] as revenue at this
                    # point fabricates a sale that hasn't happened, for every
                    # single product published. Real revenue must come from
                    # a Gumroad sale webhook/confirmation, not listing
                    # creation.
                    return {"success": True, "url": url, "product_id": data.get("id")}
                logger.warning("[CFOAgent] Gumroad error %d: %s", res.status_code, res.text[:200])
                return {"success": False, "error": f"HTTP {res.status_code}"}
        except Exception as exc:
            logger.error("[CFOAgent] Error publishing to Gumroad: %s", exc)
            return {"success": False, "error": str(exc)}

    async def create_stripe_product(
        self, name: str, price_usd: float, description: str
    ) -> dict[str, Any]:
        """Creates a product in Stripe."""
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                prod_res = await client.post(
                    "https://api.stripe.com/v1/products",
                    auth=(settings.STRIPE_SECRET_KEY or "", ""),
                    data={"name": name, "description": description},
                )
                if prod_res.status_code != 200:
                    return {
                        "success": False,
                        "error": f"Stripe product HTTP {prod_res.status_code}",
                    }
                product_id = prod_res.json()["id"]

                price_res = await client.post(
                    "https://api.stripe.com/v1/prices",
                    auth=(settings.STRIPE_SECRET_KEY or "", ""),
                    data={
                        "product": product_id,
                        "unit_amount": int(price_usd * 100),
                        "currency": "usd",
                    },
                )
                if price_res.status_code != 200:
                    return {"success": False, "error": f"Stripe price HTTP {price_res.status_code}"}
                price_id = price_res.json()["id"]
                logger.info("[CFOAgent] Stripe product created: %s", product_id)
                return {"success": True, "product_id": product_id, "price_id": price_id}
        except Exception as exc:
            logger.error("[CFOAgent] Error creating Stripe product: %s", exc)
            return {"success": False, "error": str(exc)}

    async def create_payment_link(
        self, name: str, price_usd: float, description: str
    ) -> dict[str, Any]:
        """Creates a direct payment link in Stripe."""
        try:
            stripe_prod = await self.create_stripe_product(name, price_usd, description)
            if not stripe_prod.get("success"):
                return stripe_prod

            async with httpx.AsyncClient(timeout=15.0) as client:
                res = await client.post(
                    "https://api.stripe.com/v1/payment_links",
                    auth=(settings.STRIPE_SECRET_KEY or "", ""),
                    data={
                        "line_items[0][price]": stripe_prod["price_id"],
                        "line_items[0][quantity]": "1",
                    },
                )
                if res.status_code == 200:
                    url = res.json().get("url", "")
                    logger.info("[CFOAgent] Payment link created: %s", url)
                    return {"success": True, "url": url}
                return {"success": False, "error": f"HTTP {res.status_code}"}
        except Exception as exc:
            logger.error("[CFOAgent] Error creating payment link: %s", exc)
            return {"success": False, "error": str(exc)}

    async def create_shopify_product(
        self, name: str, description: str, price_usd: float, niche: str
    ) -> dict[str, Any]:
        """Creates a product in Shopify."""
        shop_url = settings.SHOPIFY_URL or settings.SHOPIFY_SHOP_NAME
        token = (
            settings.SHOPIFY_ADMIN_TOKEN
            or settings.SHOPIFY_AUTOMATION_TOKEN
            or settings.SHOPIFY_ACCESS_TOKEN
        )

        if not shop_url or not token:
            return {"success": False, "error": "Shopify is not configured on the server"}
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                res = await client.post(
                    f"https://{shop_url}/admin/api/2024-01/products.json",
                    headers={
                        "X-Shopify-Access-Token": token,
                        "Content-Type": "application/json",
                    },
                    json={
                        "product": {
                            "title": name,
                            "body_html": f"<p>{description}</p>",
                            "vendor": "Aria AI",
                            "product_type": "Digital",
                            "tags": [niche],
                            "variants": [{"price": str(price_usd), "inventory_management": None}],
                            "published": True,
                        }
                    },
                )
                if res.status_code in (200, 201):
                    product = res.json().get("product", {})
                    logger.info("[CFOAgent] Shopify product created: %s", product.get("id"))
                    return {
                        "success": True,
                        "product_id": product.get("id"),
                        "handle": product.get("handle"),
                    }
                return {"success": False, "error": f"HTTP {res.status_code}"}
        except Exception as exc:
            logger.error("[CFOAgent] Error creating Shopify product: %s", exc)
            return {"success": False, "error": str(exc)}

    async def _register_revenue(
        self,
        revenue_type: str,
        amount: float,
        product_name: str,
        platform: str,
        currency: str = "USD",
    ) -> None:
        try:
            from apps.core.memory.supabase_client import get_db

            db = get_db()
            await db.save_revenue(
                revenue_type=revenue_type,
                amount=amount,
                currency=currency,
                product_name=product_name,
                platform=platform,
            )
            self.metrics.revenue_generated += amount
            logger.info(
                "[CFOAgent] Revenue recorded: $%.2f %s via %s", amount, currency, platform
            )
        except Exception as exc:
            logger.warning("[CFOAgent] Could not record revenue: %s", exc)
