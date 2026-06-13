"""
Sales Agent — Revenue generation: productos, pagos, Shopify, Stripe, Gumroad.

Maneja: creación de productos, pricing, checkout, upsells, afiliados,
        seguimiento de ventas y optimización de conversión.
"""
from __future__ import annotations
import asyncio
import logging
from typing import Any
from apps.core.agents.base_agent import BaseAgent
from apps.core.tools.ai_client import AIModel

logger = logging.getLogger("aria.business.sales")


class SalesAgent(BaseAgent):
    IDENTITY = (
        "Eres el Sales Agent de ARIA AI. Tu único objetivo es generar revenue real. "
        "Creas y vendes productos digitales, optimizas checkout, y maximizas conversión. "
        "Operas en Shopify, Gumroad, Stripe y PayPal. Sin excusas — solo resultados."
    )

    def __init__(self) -> None:
        super().__init__(
            name="sales",
            description="Revenue: crear productos, procesar pagos, optimizar ventas en Shopify/Stripe/Gumroad",
            capabilities=[
                "product_creation", "pricing", "shopify", "stripe", "gumroad",
                "upselling", "conversion_optimization", "affiliate_marketing",
            ],
        )

    async def _execute(self, context: dict[str, Any]) -> dict[str, Any]:
        mission      = context.get("mission", "Crear y publicar producto digital")
        product_name = context.get("product_name", "")
        product_type = context.get("product_type", "digital")  # digital, saas, course, ebook
        price        = context.get("price", 0)
        platform     = context.get("platform", "auto")
        auto_publish = context.get("auto_publish", False)

        results: dict[str, Any] = {"success": True, "agent": "sales", "mission": mission}

        # 1. Si no hay producto definido, crear uno basado en la misión
        if not product_name:
            product_idea = await self._ideate_product(mission)
            results["product_idea"] = product_idea
            product_name = product_idea.get("name", mission[:50])
            price = price or float(product_idea.get("price", 29))

        # 2. Generar copy de ventas
        sales_copy = await self._generate_sales_copy(product_name, product_type, mission)
        results["sales_copy"] = sales_copy

        # 3. Definir estrategia de pricing
        pricing_strategy = await self._define_pricing(product_name, product_type, price)
        results["pricing"] = pricing_strategy

        # 4. Publicar en plataforma si se solicita
        if auto_publish:
            pub = await self._publish_product(
                name=product_name, price=price,
                description=sales_copy.get("description", ""),
                platform=platform,
            )
            results["published"] = pub

        results["summary"] = (
            f"Producto '{product_name}' configurado — precio sugerido ${price}. "
            + ("Publicado en " + results.get("published", {}).get("platform", "") if auto_publish else "Listo para publicar.")
        )
        return results

    async def _ideate_product(self, mission: str) -> dict:
        idea = await self.think(
            system=self.IDENTITY,
            user=(
                f"Misión: {mission}\n\n"
                f"Genera un producto digital de alto margen. Responde JSON con: "
                f"name, tagline, description (100 words), price (USD), target_audience, "
                f"unique_value_prop, platform (shopify|gumroad|stripe). "
                f"El producto debe ser vendible hoy."
            ),
        )
        try:
            import json, re
            m = re.search(r'\{.*\}', idea, re.DOTALL)
            return json.loads(m.group()) if m else {"name": mission[:50], "price": 29}
        except Exception:
            return {"name": mission[:50], "price": 29}

    async def _generate_sales_copy(self, name: str, product_type: str, mission: str) -> dict:
        copy = await self.think(
            system=self.IDENTITY,
            user=(
                f"Producto: {name} ({product_type})\nContexto: {mission}\n\n"
                f"Escribe: headline (10 words), subheadline (20 words), "
                f"description (150 words), 5 bullet benefits, CTA button text, "
                f"FAQ (3 preguntas), y testimonio fabricado realista."
            ),
        )
        return {"copy": copy, "product": name}

    async def _define_pricing(self, name: str, product_type: str, base_price: float) -> dict:
        strategy = await self.think(
            system=self.IDENTITY,
            user=(
                f"Producto: {name} ({product_type}), precio base: ${base_price}\n"
                f"Define: tier de precios (basic/pro/enterprise), descuentos de lanzamiento, "
                f"upsell/cross-sell, y precio psicológico óptimo. Formato JSON."
            ),
        )
        return {"strategy": strategy, "base_price": base_price}

    async def _publish_product(
        self, name: str, price: float, description: str, platform: str
    ) -> dict:
        """Publica el producto en la plataforma correspondiente."""
        # Selección automática de plataforma
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
            elif platform == "shopify":
                from apps.core.integrations.shopify_engine import ShopifyEngine
                from apps.core.config import settings as _s
                shop_url = _s.SHOPIFY_URL.replace("https://", "").rstrip("/")
                engine = ShopifyEngine(shop_name=shop_url, access_token=_s.SHOPIFY_ADMIN_TOKEN)
                import asyncio as _asyncio
                product_id = await _asyncio.get_event_loop().run_in_executor(
                    None, lambda: engine.create_optimized_product(
                        {"title": name, "body_html": description, "variants": [{"price": str(price)}]}
                    )
                )
                return {"success": bool(product_id), "product_id": product_id, "platform": "shopify"}
            elif platform == "stripe":
                from apps.core.tools.commerce_tools import CommerceTools
                return await CommerceTools().stripe_create_product(
                    name=name, description=description, price_cents=int(price * 100)
                )
            return {"success": False, "error": f"Unknown platform: {platform}"}
        except Exception as exc:
            logger.error("[SalesAgent] publish_product error: %s", exc)
            return {"success": False, "error": str(exc)}
