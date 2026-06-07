"""
CFOAgent — Chief Financial Officer Agent
Crea y publica productos digitales, gestiona pagos y registra ingresos.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

import httpx

from apps.core.agents.base_agent import BaseAgent
from apps.core.config import settings
from apps.core.tools.ai_client import AIModel

logger = logging.getLogger("aria.cfo_agent")


class CFOAgent(BaseAgent):
    def __init__(self) -> None:
        super().__init__(
            name="cfo",
            description="CFO — productos digitales, pagos e ingresos",
            capabilities=["ebook_creation", "gumroad", "stripe", "shopify", "revenue_tracking"],
        )

    async def _execute(self, context: dict[str, Any]) -> dict[str, Any]:
        task = context.get("task", "")
        market_focus = context.get("market_focus", "digital products")
        language = context.get("primary_language", "en")

        ebook = await self.create_ebook(market_focus, language)
        if not ebook:
            return {"success": False, "error": "No se pudo generar el ebook"}

        results: dict[str, Any] = {"success": True, "agent": "cfo_agent", "ebook": ebook}

        # Publicar en Gumroad (requiere aprobación si precio > 0)
        if settings.GUMROAD_TOKEN and ebook.get("price_usd", 0) > 0:
            gumroad_result = await self.execute_with_approval(
                action="Publicar ebook en Gumroad",
                details=f"Título: {ebook['title']} | Precio: ${ebook['price_usd']}",
                fn=lambda: self.publish_to_gumroad(ebook),
                amount_usd=0.0,  # No tiene costo, genera ingresos
            )
            results["gumroad"] = gumroad_result

        # Crear link de pago en Stripe
        if settings.STRIPE_SECRET_KEY:
            stripe_result = await self.create_payment_link(
                name=ebook["title"],
                price_usd=ebook["price_usd"],
                description=ebook["description"],
            )
            results["stripe"] = stripe_result

        return results

    async def create_ebook(self, niche: str, language: str) -> Optional[dict[str, Any]]:
        """Genera el contenido completo de un ebook usando IA."""
        meta = await self.think(
            system="Eres un experto en marketing de información y creación de productos digitales de alto valor.",
            user=(
                f"Nicho: {niche} | Idioma: {language}\n\n"
                "Crea los metadatos de un ebook que se pueda vender por $7-$27 USD. JSON:\n"
                '{"title": "...", "subtitle": "...", "description": "...", '
                '"price_usd": 9.99, "pages_estimate": 30, '
                '"chapter_titles": ["Cap 1", "Cap 2", "Cap 3", "Cap 4", "Cap 5"], '
                '"target_audience": "...", "unique_value_proposition": "...", '
                '"keywords": ["kw1", "kw2", "kw3"]}'
            ),
            model=AIModel.STRATEGY,
            json_mode=True,
        )
        if not meta:
            return None

        # Generar contenido de los primeros 2 capítulos
        content = await self.think(
            system="Eres un escritor experto en libros de no-ficción orientados a resultados prácticos.",
            user=(
                f"Escribe la introducción y el primer capítulo del ebook '{meta.get('title', '')}' "
                f"sobre '{niche}'. Idioma: {language}. "
                "Sé práctico, con ejemplos reales y pasos accionables. Mínimo 800 palabras."
            ),
            model=AIModel.CREATIVE,
        )
        meta["sample_content"] = content or ""
        meta["niche"] = niche
        meta["language"] = language
        logger.info("[CFOAgent] Ebook creado: %s | $%.2f", meta.get("title"), meta.get("price_usd", 0))
        return meta

    async def publish_to_gumroad(self, ebook: dict[str, Any]) -> dict[str, Any]:
        """Publica el ebook en Gumroad via API."""
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                res = await client.post(
                    "https://api.gumroad.com/v2/products",
                    data={
                        "access_token": settings.GUMROAD_TOKEN,
                        "name": ebook["title"],
                        "description": ebook["description"],
                        "price": int(ebook.get("price_usd", 9.99) * 100),  # centavos
                        "url": f"https://gumroad.com",
                        "published": "true",
                    },
                )
                if res.status_code == 201:
                    data = res.json().get("product", {})
                    url = data.get("short_url", "")
                    logger.info("[CFOAgent] Publicado en Gumroad: %s", url)
                    await self._register_revenue(
                        revenue_type="digital_product",
                        amount=ebook.get("price_usd", 9.99),
                        product_name=ebook["title"],
                        platform="gumroad",
                    )
                    return {"success": True, "url": url, "product_id": data.get("id")}
                else:
                    logger.warning("[CFOAgent] Gumroad error %d: %s", res.status_code, res.text[:200])
                    return {"success": False, "error": f"HTTP {res.status_code}"}
        except Exception as exc:
            logger.error("[CFOAgent] Error publicando en Gumroad: %s", exc)
            return {"success": False, "error": str(exc)}

    async def create_stripe_product(
        self, name: str, price_usd: float, description: str
    ) -> dict[str, Any]:
        """Crea un producto en Stripe."""
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                prod_res = await client.post(
                    "https://api.stripe.com/v1/products",
                    auth=(settings.STRIPE_SECRET_KEY or "", ""),
                    data={"name": name, "description": description},
                )
                if prod_res.status_code != 200:
                    return {"success": False, "error": f"Stripe product HTTP {prod_res.status_code}"}
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
                logger.info("[CFOAgent] Producto Stripe creado: %s", product_id)
                return {"success": True, "product_id": product_id, "price_id": price_id}
        except Exception as exc:
            logger.error("[CFOAgent] Error creando producto Stripe: %s", exc)
            return {"success": False, "error": str(exc)}

    async def create_payment_link(
        self, name: str, price_usd: float, description: str
    ) -> dict[str, Any]:
        """Crea un link de pago directo en Stripe."""
        try:
            stripe_prod = await self.create_stripe_product(name, price_usd, description)
            if not stripe_prod.get("success"):
                return stripe_prod

            async with httpx.AsyncClient(timeout=15.0) as client:
                res = await client.post(
                    "https://api.stripe.com/v1/payment_links",
                    auth=(settings.STRIPE_SECRET_KEY or "", ""),
                    data={"line_items[0][price]": stripe_prod["price_id"], "line_items[0][quantity]": "1"},
                )
                if res.status_code == 200:
                    url = res.json().get("url", "")
                    logger.info("[CFOAgent] Payment link creado: %s", url)
                    return {"success": True, "url": url}
                return {"success": False, "error": f"HTTP {res.status_code}"}
        except Exception as exc:
            logger.error("[CFOAgent] Error creando payment link: %s", exc)
            return {"success": False, "error": str(exc)}

    async def create_shopify_product(
        self, name: str, description: str, price_usd: float, niche: str
    ) -> dict[str, Any]:
        """Crea un producto en Shopify."""
        shop_url = settings.SHOPIFY_URL or settings.SHOPIFY_SHOP_NAME
        token = settings.SHOPIFY_ADMIN_TOKEN or settings.SHOPIFY_AUTOMATION_TOKEN or settings.SHOPIFY_ACCESS_TOKEN
        
        if not shop_url or not token:
            return {"success": False, "error": "Shopify no configurado en el servidor"}
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
                    logger.info("[CFOAgent] Producto Shopify creado: %s", product.get("id"))
                    return {"success": True, "product_id": product.get("id"), "handle": product.get("handle")}
                return {"success": False, "error": f"HTTP {res.status_code}"}
        except Exception as exc:
            logger.error("[CFOAgent] Error creando producto Shopify: %s", exc)
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
            logger.info("[CFOAgent] Ingreso registrado: $%.2f %s via %s", amount, currency, platform)
        except Exception as exc:
            logger.warning("[CFOAgent] No se pudo registrar ingreso: %s", exc)
