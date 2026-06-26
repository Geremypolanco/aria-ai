"""
ShopifyAPIClient — Real Shopify Admin API integration.

Reads credentials from environment:
  SHOPIFY_SHOP_DOMAIN  — e.g. "mystore.myshopify.com"
  SHOPIFY_ACCESS_TOKEN — Admin API access token

Uses Shopify Admin REST API 2024-01 and GraphQL Admin API.
Gracefully degrades when credentials absent.
"""

from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass, field

import httpx

logger = logging.getLogger(__name__)

_SHOPIFY_KEY = "shopify:api:cache:v1"
_SHOPIFY_TTL = 86400 * 7


# ── Dataclasses ───────────────────────────────────────────────────────────────


@dataclass
class ShopifyProduct:
    product_id: str = ""
    title: str = ""
    description: str = ""
    price: float = 0.0
    inventory_qty: int = 0
    status: str = "active"
    tags: list[str] = field(default_factory=list)
    seo_title: str = ""
    seo_description: str = ""

    def to_dict(self) -> dict:
        return {
            "product_id": self.product_id,
            "title": self.title,
            "description": self.description,
            "price": self.price,
            "inventory_qty": self.inventory_qty,
            "status": self.status,
            "tags": self.tags,
            "seo_title": self.seo_title,
            "seo_description": self.seo_description,
        }


@dataclass
class ShopifyOrder:
    order_id: str = ""
    total_price: float = 0.0
    status: str = ""
    customer_email: str = ""
    line_items: list[dict] = field(default_factory=list)
    created_at: str = ""

    def to_dict(self) -> dict:
        return {
            "order_id": self.order_id,
            "total_price": self.total_price,
            "status": self.status,
            "customer_email": self.customer_email,
            "line_items": self.line_items,
            "created_at": self.created_at,
        }


@dataclass
class ShopifyAnalytics:
    period: str = ""
    total_revenue: float = 0.0
    orders_count: int = 0
    avg_order_value: float = 0.0
    top_products: list[dict] = field(default_factory=list)
    conversion_rate_pct: float = 0.0

    def to_dict(self) -> dict:
        return {
            "period": self.period,
            "total_revenue": round(self.total_revenue, 4),
            "orders_count": self.orders_count,
            "avg_order_value": round(self.avg_order_value, 4),
            "top_products": self.top_products,
            "conversion_rate_pct": round(self.conversion_rate_pct, 4),
        }


# ── Client ────────────────────────────────────────────────────────────────────


class ShopifyAPIClient:
    """
    Real Shopify Admin API client.

    Wraps REST and GraphQL Admin APIs with graceful degradation when
    SHOPIFY_SHOP_DOMAIN / SHOPIFY_ACCESS_TOKEN are not set.
    """

    def __init__(self) -> None:
        self._domain: str = os.environ.get("SHOPIFY_SHOP_DOMAIN", "")
        self._token: str = os.environ.get("SHOPIFY_ACCESS_TOKEN", "")
        self._api_version: str = "2024-01"
        self._products_cache: list[dict] = []
        self._orders_cache: list[dict] = []
        self._loaded: bool = False

    # ── Properties ────────────────────────────────────────────────────────────

    @property
    def is_configured(self) -> bool:
        return bool(self._domain and self._token)

    @property
    def base_url(self) -> str:
        return f"https://{self._domain}/admin/api/{self._api_version}"

    # ── HTTP helpers ──────────────────────────────────────────────────────────

    async def _get(self, path: str, params: dict = None) -> dict:
        if params is None:
            params = {}
        if not self.is_configured:
            return {"error": "Shopify not configured"}
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.get(
                    f"{self.base_url}{path}",
                    params=params,
                    headers={
                        "X-Shopify-Access-Token": self._token,
                        "Content-Type": "application/json",
                    },
                )
                response.raise_for_status()
                return response.json()
        except httpx.HTTPStatusError as exc:
            logger.error("Shopify GET %s HTTP %d: %s", path, exc.response.status_code, exc)
            return {"error": f"HTTP {exc.response.status_code}", "path": path}
        except Exception as exc:
            logger.error("Shopify GET %s error: %s", path, exc)
            return {"error": str(exc), "path": path}

    async def _post(self, path: str, body: dict) -> dict:
        if not self.is_configured:
            return {"error": "Shopify not configured"}
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(
                    f"{self.base_url}{path}",
                    json=body,
                    headers={
                        "X-Shopify-Access-Token": self._token,
                        "Content-Type": "application/json",
                    },
                )
                response.raise_for_status()
                return response.json()
        except httpx.HTTPStatusError as exc:
            logger.error("Shopify POST %s HTTP %d: %s", path, exc.response.status_code, exc)
            return {"error": f"HTTP {exc.response.status_code}", "path": path}
        except Exception as exc:
            logger.error("Shopify POST %s error: %s", path, exc)
            return {"error": str(exc), "path": path}

    async def _put(self, path: str, body: dict) -> dict:
        if not self.is_configured:
            return {"error": "Shopify not configured"}
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.put(
                    f"{self.base_url}{path}",
                    json=body,
                    headers={
                        "X-Shopify-Access-Token": self._token,
                        "Content-Type": "application/json",
                    },
                )
                response.raise_for_status()
                return response.json()
        except httpx.HTTPStatusError as exc:
            logger.error("Shopify PUT %s HTTP %d: %s", path, exc.response.status_code, exc)
            return {"error": f"HTTP {exc.response.status_code}", "path": path}
        except Exception as exc:
            logger.error("Shopify PUT %s error: %s", path, exc)
            return {"error": str(exc), "path": path}

    # ── Products ──────────────────────────────────────────────────────────────

    async def get_products(self, limit: int = 50, status: str = "active") -> list[ShopifyProduct]:
        try:
            data = await self._get("/products.json", params={"limit": limit, "status": status})
            if "error" in data:
                return []

            products: list[ShopifyProduct] = []
            for raw in data.get("products", []):
                # Extract price from first variant if present
                variants = raw.get("variants", [])
                price = float(variants[0].get("price", 0.0)) if variants else 0.0
                inventory_qty = sum(int(v.get("inventory_quantity", 0)) for v in variants)

                tags_raw = raw.get("tags", "")
                tags = [t.strip() for t in tags_raw.split(",")] if tags_raw else []

                seo = raw.get("metafields_global_title_tag", "") or ""
                seo_desc = raw.get("metafields_global_description_tag", "") or ""

                product = ShopifyProduct(
                    product_id=str(raw.get("id", "")),
                    title=raw.get("title", ""),
                    description=raw.get("body_html", ""),
                    price=price,
                    inventory_qty=inventory_qty,
                    status=raw.get("status", "active"),
                    tags=tags,
                    seo_title=seo,
                    seo_description=seo_desc,
                )
                products.append(product)

            self._products_cache = [p.to_dict() for p in products]
            return products
        except Exception as exc:
            logger.error("get_products error: %s", exc)
            return []

    async def update_product(self, product_id: str, updates: dict) -> ShopifyProduct | None:
        try:
            data = await self._put(f"/products/{product_id}.json", body={"product": updates})
            if "error" in data or "product" not in data:
                return None

            raw = data["product"]
            variants = raw.get("variants", [])
            price = float(variants[0].get("price", 0.0)) if variants else 0.0
            inventory_qty = sum(int(v.get("inventory_quantity", 0)) for v in variants)

            tags_raw = raw.get("tags", "")
            tags = [t.strip() for t in tags_raw.split(",")] if tags_raw else []

            return ShopifyProduct(
                product_id=str(raw.get("id", "")),
                title=raw.get("title", ""),
                description=raw.get("body_html", ""),
                price=price,
                inventory_qty=inventory_qty,
                status=raw.get("status", "active"),
                tags=tags,
                seo_title=raw.get("metafields_global_title_tag", "") or "",
                seo_description=raw.get("metafields_global_description_tag", "") or "",
            )
        except Exception as exc:
            logger.error("update_product %s error: %s", product_id, exc)
            return None

    # ── Orders ────────────────────────────────────────────────────────────────

    async def get_orders(self, limit: int = 50, status: str = "any") -> list[ShopifyOrder]:
        try:
            data = await self._get("/orders.json", params={"limit": limit, "status": status})
            if "error" in data:
                return []

            orders: list[ShopifyOrder] = []
            for raw in data.get("orders", []):
                customer = raw.get("customer") or {}
                email = customer.get("email", "") or raw.get("email", "")

                order = ShopifyOrder(
                    order_id=str(raw.get("id", "")),
                    total_price=float(raw.get("total_price", 0.0)),
                    status=raw.get("financial_status", raw.get("fulfillment_status", "")),
                    customer_email=email,
                    line_items=raw.get("line_items", []),
                    created_at=raw.get("created_at", ""),
                )
                orders.append(order)

            self._orders_cache = [o.to_dict() for o in orders]
            return orders
        except Exception as exc:
            logger.error("get_orders error: %s", exc)
            return []

    # ── Analytics ─────────────────────────────────────────────────────────────

    async def get_revenue_analytics(self, days: int = 30) -> ShopifyAnalytics:
        try:
            data = await self._get(
                "/orders.json",
                params={"status": "closed", "limit": 250},
            )
            if "error" in data:
                return ShopifyAnalytics(period=f"last_{days}_days")

            orders = data.get("orders", [])
            if not orders:
                return ShopifyAnalytics(period=f"last_{days}_days")

            # Filter to the requested window using created_at
            cutoff_ts = time.time() - (days * 86400)
            recent_orders = []
            for raw in orders:
                created_str = raw.get("created_at", "")
                # Parse ISO 8601 date cheaply
                try:
                    from datetime import datetime  # noqa: PLC0415

                    dt = datetime.fromisoformat(created_str.replace("Z", "+00:00"))
                    if dt.timestamp() >= cutoff_ts:
                        recent_orders.append(raw)
                except Exception:
                    recent_orders.append(raw)  # include if we can't parse

            total_revenue = sum(float(o.get("total_price", 0.0)) for o in recent_orders)
            orders_count = len(recent_orders)
            avg_order_value = total_revenue / max(orders_count, 1)

            # Top products by revenue
            product_revenue: dict[str, float] = {}
            product_titles: dict[str, str] = {}
            for o in recent_orders:
                for item in o.get("line_items", []):
                    pid = str(item.get("product_id", ""))
                    item_total = float(item.get("price", 0.0)) * int(item.get("quantity", 1))
                    product_revenue[pid] = product_revenue.get(pid, 0.0) + item_total
                    product_titles[pid] = item.get("title", pid)

            top_products = sorted(
                [
                    {"product_id": pid, "title": product_titles[pid], "revenue": round(rev, 4)}
                    for pid, rev in product_revenue.items()
                ],
                key=lambda x: x["revenue"],
                reverse=True,
            )[:10]

            return ShopifyAnalytics(
                period=f"last_{days}_days",
                total_revenue=total_revenue,
                orders_count=orders_count,
                avg_order_value=avg_order_value,
                top_products=top_products,
                conversion_rate_pct=0.0,  # requires session data not available via orders API
            )
        except Exception as exc:
            logger.error("get_revenue_analytics error: %s", exc)
            return ShopifyAnalytics(period=f"last_{days}_days")

    # ── GraphQL ───────────────────────────────────────────────────────────────

    async def graphql_query(self, query: str, variables: dict = None) -> dict:
        if variables is None:
            variables = {}
        return await self._post("/graphql.json", body={"query": query, "variables": variables})

    # ── SEO helpers ───────────────────────────────────────────────────────────

    async def optimize_product_seo(
        self, product_id: str, seo_title: str, seo_description: str
    ) -> bool:
        try:
            result = await self.update_product(
                product_id,
                {
                    "seo": {
                        "title": seo_title,
                        "description": seo_description,
                    }
                },
            )
            return result is not None
        except Exception as exc:
            logger.error("optimize_product_seo %s error: %s", product_id, exc)
            return False

    # ── Status ────────────────────────────────────────────────────────────────

    def client_status(self) -> dict:
        masked_domain = ""
        if self._domain:
            # e.g. "mystore.myshopify.com" → "my***re.myshopify.com"
            parts = self._domain.split(".")
            if parts:
                name = parts[0]
                if len(name) > 4:
                    masked_domain = name[:2] + "***" + name[-2:] + "." + ".".join(parts[1:])
                else:
                    masked_domain = "***." + ".".join(parts[1:])
            else:
                masked_domain = "***"

        return {
            "configured": self.is_configured,
            "domain": masked_domain if self._domain else "not set",
            "api_version": self._api_version,
            "cached_products": len(self._products_cache),
            "cached_orders": len(self._orders_cache),
        }


# ── Singleton ─────────────────────────────────────────────────────────────────

_client_instance: ShopifyAPIClient | None = None


def get_shopify_api_client() -> ShopifyAPIClient:
    global _client_instance
    if _client_instance is None:
        _client_instance = ShopifyAPIClient()
    return _client_instance
