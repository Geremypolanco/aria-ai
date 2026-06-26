"""
lemon_squeezy_tools.py — LemonSqueezy integration for digital product sales.

LemonSqueezy is a modern alternative to Gumroad with lower fees (5%+$0.50).
Requires: LEMONSQUEEZY_API_KEY and LEMONSQUEEZY_STORE_ID in Fly.io secrets.

Get API key at: https://app.lemonsqueezy.com/settings/api
Get Store ID at: https://app.lemonsqueezy.com/settings/general
"""

from __future__ import annotations

import logging

import httpx

from apps.core.config import settings

logger = logging.getLogger("aria.lemonsqueezy")

LS_API = "https://api.lemonsqueezy.com/v1"


class LemonSqueezyTools:
    """Create and manage digital products on LemonSqueezy."""

    def __init__(self) -> None:
        self._http = httpx.AsyncClient(timeout=20.0)
        self._api_key = getattr(settings, "LEMONSQUEEZY_API_KEY", None)
        self._store_id = getattr(settings, "LEMONSQUEEZY_STORE_ID", None)

    def _configured(self) -> bool:
        return bool(self._api_key and self._store_id)

    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self._api_key}",
            "Accept": "application/vnd.api+json",
            "Content-Type": "application/vnd.api+json",
        }

    async def create_product(
        self,
        name: str,
        description: str,
        price_cents: int = 997,
        tags: list[str] | None = None,
    ) -> dict:
        """
        Create a digital product on LemonSqueezy.
        Returns {success, url, product_id, price_usd, platform}
        """
        if not self._configured():
            missing = []
            if not self._api_key:
                missing.append("LEMONSQUEEZY_API_KEY")
            if not self._store_id:
                missing.append("LEMONSQUEEZY_STORE_ID")
            return {
                "success": False,
                "error": f"LemonSqueezy not configured. Add to Fly.io: fly secrets set {' '.join(f'{k}=...' for k in missing)} -a aria-ai",
            }

        try:
            # Step 1: Create the product
            product_payload = {
                "data": {
                    "type": "products",
                    "attributes": {
                        "name": name[:100],
                        "description": description[:5000],
                        "status": "published",
                        "buy_now_url": None,
                    },
                    "relationships": {
                        "store": {"data": {"type": "stores", "id": str(self._store_id)}}
                    },
                }
            }

            r = await self._http.post(
                f"{LS_API}/products",
                json=product_payload,
                headers=self._headers(),
            )
            if r.status_code not in (200, 201):
                return {
                    "success": False,
                    "error": f"LemonSqueezy product error: HTTP {r.status_code}: {r.text[:200]}",
                }

            product_data = r.json().get("data", {})
            product_id = product_data.get("id", "")
            product_attrs = product_data.get("attributes", {})

            # Step 2: Create a variant (required — price lives on variant)
            variant_payload = {
                "data": {
                    "type": "variants",
                    "attributes": {
                        "name": "Standard",
                        "price": price_cents,
                        "is_subscription": False,
                        "has_free_trial": False,
                        "status": "published",
                    },
                    "relationships": {
                        "product": {"data": {"type": "products", "id": str(product_id)}}
                    },
                }
            }

            r2 = await self._http.post(
                f"{LS_API}/variants",
                json=variant_payload,
                headers=self._headers(),
            )
            if r2.status_code not in (200, 201):
                logger.warning("[LemonSqueezy] Variant creation: HTTP %d", r2.status_code)

            # Build checkout URL from store + product slug
            store_url = (
                product_attrs.get("buy_now_url")
                or f"https://app.lemonsqueezy.com/products/{product_id}"
            )

            logger.info(
                "[LemonSqueezy] Product created: '%s' | ID: %s | $%.2f",
                name,
                product_id,
                price_cents / 100,
            )
            return {
                "success": True,
                "product_id": product_id,
                "url": store_url,
                "name": name,
                "price_usd": round(price_cents / 100, 2),
                "platform": "lemonsqueezy",
            }

        except Exception as exc:
            logger.error("[LemonSqueezy] Exception: %s", exc)
            return {"success": False, "error": str(exc)[:200]}

    async def list_products(self) -> list[dict]:
        """List all products in the store."""
        if not self._configured():
            return []
        try:
            r = await self._http.get(
                f"{LS_API}/products",
                params={"filter[store_id]": self._store_id},
                headers=self._headers(),
            )
            if r.status_code == 200:
                return r.json().get("data", [])
        except Exception as exc:
            logger.error("[LemonSqueezy] list_products: %s", exc)
        return []

    async def get_sales_summary(self) -> dict:
        """Get recent orders/sales summary."""
        if not self._configured():
            return {"error": "not configured", "total_orders": 0, "total_revenue_usd": 0}
        try:
            r = await self._http.get(
                f"{LS_API}/orders",
                params={"filter[store_id]": self._store_id, "page[size]": 50},
                headers=self._headers(),
            )
            if r.status_code == 200:
                orders = r.json().get("data", [])
                total = sum(o.get("attributes", {}).get("total", 0) for o in orders)
                return {
                    "total_orders": len(orders),
                    "total_revenue_usd": round(total / 100, 2),
                    "recent_orders": orders[:5],
                }
        except Exception as exc:
            logger.error("[LemonSqueezy] sales: %s", exc)
        return {"error": "failed", "total_orders": 0, "total_revenue_usd": 0}
