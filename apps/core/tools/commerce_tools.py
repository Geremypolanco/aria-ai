"""
commerce_tools.py — Herramientas de comercio electrónico.
Gumroad, Stripe, PayPal, Shopify — creación de productos y cobros.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

import httpx

from apps.core.config import settings

logger = logging.getLogger("aria.commerce_tools")


class CommerceTools:
    """Herramientas completas de monetización y e-commerce."""

    def __init__(self) -> None:
        self._http = httpx.AsyncClient(timeout=20.0)

    # ── GUMROAD ───────────────────────────────────────────

    async def gumroad_create_product(
        self,
        name: str,
        description: str,
        price_cents: int = 997,
        file_url: Optional[str] = None,
    ) -> dict[str, Any]:
        """Crea un producto digital en Gumroad."""
        if not settings.GUMROAD_TOKEN:
            return {"success": False, "error": "GUMROAD_TOKEN no configurado"}
        try:
            data: dict[str, Any] = {
                "access_token": settings.GUMROAD_TOKEN,
                "name": name,
                "description": description,
                "price": price_cents,
                "currency": "usd",
                "published": "true",
                "require_shipping": "false",
            }
            if file_url:
                data["url"] = file_url

            res = await self._http.post("https://api.gumroad.com/v2/products", data=data)
            if res.status_code == 200:
                product = res.json().get("product", {})
                logger.info("[CommerceTools] Gumroad producto creado: %s", product.get("id"))
                return {
                    "success": True,
                    "product_id": product.get("id"),
                    "short_url": product.get("short_url"),
                    "name": product.get("name"),
                    "price": product.get("formatted_price"),
                }
            return {"success": False, "error": f"Gumroad HTTP {res.status_code}: {res.text[:200]}"}
        except Exception as exc:
            logger.error("[CommerceTools] Error Gumroad create: %s", exc)
            return {"success": False, "error": str(exc)}

    async def gumroad_get_sales(self, product_id: Optional[str] = None) -> dict[str, Any]:
        """Obtiene las ventas de Gumroad."""
        if not settings.GUMROAD_TOKEN:
            return {"success": False, "error": "GUMROAD_TOKEN no configurado"}
        try:
            params = {"access_token": settings.GUMROAD_TOKEN}
            if product_id:
                params["product_id"] = product_id
            res = await self._http.get("https://api.gumroad.com/v2/sales", params=params)
            if res.status_code == 200:
                data = res.json()
                sales = data.get("sales", [])
                total = sum(float(s.get("price", 0)) / 100 for s in sales)
                return {"success": True, "total_usd": total, "count": len(sales), "sales": sales[:10]}
            return {"success": False, "error": f"HTTP {res.status_code}"}
        except Exception as exc:
            return {"success": False, "error": str(exc)}

    async def gumroad_update_product(
        self, product_id: str, updates: dict[str, Any]
    ) -> dict[str, Any]:
        """Actualiza un producto en Gumroad."""
        if not settings.GUMROAD_TOKEN:
            return {"success": False, "error": "GUMROAD_TOKEN no configurado"}
        try:
            data = {"access_token": settings.GUMROAD_TOKEN, **updates}
            res = await self._http.put(f"https://api.gumroad.com/v2/products/{product_id}", data=data)
            return {"success": res.status_code == 200, "data": res.json() if res.status_code == 200 else {}}
        except Exception as exc:
            return {"success": False, "error": str(exc)}

    # ── STRIPE ────────────────────────────────────────────

    async def stripe_create_product(
        self,
        name: str,
        description: str,
        price_cents: int,
        currency: str = "usd",
        recurring: bool = False,
        recurring_interval: str = "month",
    ) -> dict[str, Any]:
        """Crea un producto + precio en Stripe."""
        if not settings.STRIPE_SECRET_KEY:
            return {"success": False, "error": "STRIPE_SECRET_KEY no configurado"}
        try:
            headers = {"Authorization": f"Bearer {settings.STRIPE_SECRET_KEY}"}

            # 1. Crear producto
            prod_res = await self._http.post(
                "https://api.stripe.com/v1/products",
                headers=headers,
                data={"name": name, "description": description},
            )
            if prod_res.status_code != 200:
                return {"success": False, "error": f"Stripe product HTTP {prod_res.status_code}: {prod_res.text[:200]}"}
            product_id = prod_res.json()["id"]

            # 2. Crear precio
            price_data: dict[str, Any] = {
                "product": product_id,
                "unit_amount": price_cents,
                "currency": currency,
            }
            if recurring:
                price_data["recurring[interval]"] = recurring_interval

            price_res = await self._http.post(
                "https://api.stripe.com/v1/prices",
                headers=headers,
                data=price_data,
            )
            if price_res.status_code != 200:
                return {"success": False, "error": f"Stripe price HTTP {price_res.status_code}"}
            price_id = price_res.json()["id"]

            # 3. Crear payment link
            link_res = await self._http.post(
                "https://api.stripe.com/v1/payment_links",
                headers=headers,
                data={"line_items[0][price]": price_id, "line_items[0][quantity]": "1"},
            )
            payment_link = ""
            if link_res.status_code == 200:
                payment_link = link_res.json().get("url", "")

            logger.info("[CommerceTools] Stripe producto creado: %s", product_id)
            return {
                "success": True,
                "product_id": product_id,
                "price_id": price_id,
                "payment_link": payment_link,
                "amount_usd": price_cents / 100,
            }
        except Exception as exc:
            logger.error("[CommerceTools] Error Stripe: %s", exc)
            return {"success": False, "error": str(exc)}

    async def stripe_create_checkout(
        self,
        price_id: str,
        success_url: str = "https://aria-ai.fly.dev/success",
        cancel_url: str = "https://aria-ai.fly.dev/cancel",
    ) -> dict[str, Any]:
        """Crea una sesión de Stripe Checkout."""
        if not settings.STRIPE_SECRET_KEY:
            return {"success": False, "error": "STRIPE_SECRET_KEY no configurado"}
        try:
            headers = {"Authorization": f"Bearer {settings.STRIPE_SECRET_KEY}"}
            res = await self._http.post(
                "https://api.stripe.com/v1/checkout/sessions",
                headers=headers,
                data={
                    "mode": "payment",
                    "line_items[0][price]": price_id,
                    "line_items[0][quantity]": "1",
                    "success_url": success_url,
                    "cancel_url": cancel_url,
                },
            )
            if res.status_code == 200:
                session = res.json()
                return {"success": True, "checkout_url": session.get("url"), "session_id": session.get("id")}
            return {"success": False, "error": f"HTTP {res.status_code}: {res.text[:200]}"}
        except Exception as exc:
            return {"success": False, "error": str(exc)}

    async def stripe_get_revenue(self) -> dict[str, Any]:
        """Obtiene el revenue total de Stripe."""
        if not settings.STRIPE_SECRET_KEY:
            return {"success": False, "error": "STRIPE_SECRET_KEY no configurado"}
        try:
            headers = {"Authorization": f"Bearer {settings.STRIPE_SECRET_KEY}"}
            res = await self._http.get(
                "https://api.stripe.com/v1/charges",
                headers=headers,
                params={"limit": 100, "status": "succeeded"},
            )
            if res.status_code == 200:
                charges = res.json().get("data", [])
                total = sum(c.get("amount", 0) for c in charges) / 100
                return {"success": True, "total_usd": total, "count": len(charges)}
            return {"success": False, "error": f"HTTP {res.status_code}"}
        except Exception as exc:
            return {"success": False, "error": str(exc)}

    # ── PAYPAL ────────────────────────────────────────────

    async def _paypal_get_token(self) -> Optional[str]:
        """Obtiene access token de PayPal."""
        if not settings.PAYPAL_CLIENT_ID or not settings.PAYPAL_SECRET:
            return None
        try:
            res = await self._http.post(
                "https://api-m.paypal.com/v1/oauth2/token",
                auth=(settings.PAYPAL_CLIENT_ID, settings.PAYPAL_SECRET),
                data={"grant_type": "client_credentials"},
            )
            if res.status_code == 200:
                return res.json().get("access_token")
        except Exception as exc:
            logger.error("[CommerceTools] Error PayPal token: %s", exc)
        return None

    async def paypal_create_payment_link(
        self,
        name: str,
        description: str,
        amount: float,
        currency: str = "USD",
    ) -> dict[str, Any]:
        """Crea un enlace de pago en PayPal."""
        token = await self._paypal_get_token()
        if not token:
            return {"success": False, "error": "PayPal no configurado o token inválido"}
        try:
            headers = {
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            }
            res = await self._http.post(
                "https://api-m.paypal.com/v1/billing/plans",
                headers=headers,
                json={
                    "product_id": "PROD-ARIA-001",
                    "name": name,
                    "description": description,
                    "billing_cycles": [
                        {
                            "frequency": {"interval_unit": "MONTH", "interval_count": 1},
                            "tenure_type": "REGULAR",
                            "sequence": 1,
                            "total_cycles": 0,
                            "pricing_scheme": {
                                "fixed_price": {"value": str(amount), "currency_code": currency}
                            },
                        }
                    ],
                    "payment_preferences": {"auto_bill_outstanding": True},
                },
            )
            if res.status_code in (200, 201):
                plan = res.json()
                links = {link["rel"]: link["href"] for link in plan.get("links", [])}
                return {"success": True, "plan_id": plan.get("id"), "approve_url": links.get("approve", "")}
            return {"success": False, "error": f"PayPal HTTP {res.status_code}: {res.text[:200]}"}
        except Exception as exc:
            logger.error("[CommerceTools] Error PayPal create: %s", exc)
            return {"success": False, "error": str(exc)}

    # ── SHOPIFY ───────────────────────────────────────────

    async def shopify_create_product(
        self,
        title: str,
        description: str,
        price: float,
        product_type: str = "Digital",
        vendor: str = "Aria AI",
    ) -> dict[str, Any]:
        """Crea un producto en Shopify via Admin API."""
        if not settings.SHOPIFY_URL or not settings.SHOPIFY_AUTOMATION_TOKEN:
            return {"success": False, "error": "Shopify no configurado"}
        try:
            url = f"https://{settings.SHOPIFY_URL}/admin/api/2024-01/products.json"
            headers = {
                "X-Shopify-Access-Token": settings.SHOPIFY_AUTOMATION_TOKEN,
                "Content-Type": "application/json",
            }
            payload = {
                "product": {
                    "title": title,
                    "body_html": description,
                    "vendor": vendor,
                    "product_type": product_type,
                    "status": "active",
                    "variants": [
                        {
                            "price": str(price),
                            "requires_shipping": False,
                            "taxable": True,
                        }
                    ],
                }
            }
            res = await self._http.post(url, headers=headers, json=payload)
            if res.status_code in (200, 201):
                product = res.json().get("product", {})
                product_id = product.get("id")
                shop_url = f"https://{settings.SHOPIFY_URL}/products/{product.get('handle', '')}"
                logger.info("[CommerceTools] Shopify producto creado: %s", product_id)
                return {
                    "success": True,
                    "product_id": str(product_id),
                    "shop_url": shop_url,
                    "title": product.get("title"),
                    "price": price,
                }
            return {"success": False, "error": f"Shopify HTTP {res.status_code}: {res.text[:200]}"}
        except Exception as exc:
            logger.error("[CommerceTools] Error Shopify: %s", exc)
            return {"success": False, "error": str(exc)}

    async def shopify_get_orders(self, limit: int = 20) -> dict[str, Any]:
        """Obtiene los últimos pedidos de Shopify."""
        if not settings.SHOPIFY_URL or not settings.SHOPIFY_AUTOMATION_TOKEN:
            return {"success": False, "error": "Shopify no configurado"}
        try:
            url = f"https://{settings.SHOPIFY_URL}/admin/api/2024-01/orders.json"
            headers = {"X-Shopify-Access-Token": settings.SHOPIFY_AUTOMATION_TOKEN}
            res = await self._http.get(url, headers=headers, params={"limit": limit, "status": "any"})
            if res.status_code == 200:
                orders = res.json().get("orders", [])
                total = sum(float(o.get("total_price", 0)) for o in orders)
                return {"success": True, "orders": orders[:5], "count": len(orders), "total_usd": total}
            return {"success": False, "error": f"HTTP {res.status_code}"}
        except Exception as exc:
            return {"success": False, "error": str(exc)}

    async def close(self) -> None:
        await self._http.aclose()


# ── SINGLETON ─────────────────────────────────────────────
_instance: Optional[CommerceTools] = None


def get_commerce_tools() -> CommerceTools:
    global _instance
    if _instance is None:
        _instance = CommerceTools()
    return _instance
