"""
shopify_bot.py — Bot especializado en gestión autónoma de Shopify.
Aria NO revisa Shopify manualmente. Este bot lo hace y le entrega resúmenes.
"""
from __future__ import annotations
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
logger = logging.getLogger("aria.bots.shopify")

class ShopifyBot:
    def __init__(self):
        self._shop = None
        self._last_check: Optional[str] = None
        self._alerts: List[Dict] = []
        self._low_stock_threshold = 5

    def _get_engine(self):
        if self._shop is None:
            try:
                from apps.core.integrations.shopify_engine import ShopifyEngine
                from apps.core.config import settings
                if not (getattr(settings, "SHOPIFY_SHOP_NAME", None) and getattr(settings, "SHOPIFY_ACCESS_TOKEN", None)):
                    return None
                self._shop = ShopifyEngine(settings.SHOPIFY_SHOP_NAME, settings.SHOPIFY_ACCESS_TOKEN)
            except Exception as e:
                logger.warning("[ShopifyBot] Engine no disponible: %s", e)
                return None
        return self._shop

    def is_configured(self) -> bool:
        return self._get_engine() is not None

    async def get_recent_orders(self, limit: int = 10) -> Dict:
        engine = self._get_engine()
        if not engine:
            return {"success": False, "error": "Shopify no configurado (SHOPIFY_SHOP_NAME + SHOPIFY_ACCESS_TOKEN)"}
        try:
            orders = await engine.get_orders(limit=limit)
            return {"success": True, "orders": orders, "count": len(orders) if isinstance(orders, list) else 0}
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def check_inventory(self) -> Dict:
        engine = self._get_engine()
        if not engine:
            return {"success": False, "error": "Shopify no configurado"}
        try:
            products = await engine.get_products(limit=50)
            low_stock = []
            if isinstance(products, list):
                for p in products:
                    qty = p.get("inventory_quantity") or (p.get("variants") or [{}])[0].get("inventory_quantity", 0)
                    if isinstance(qty, (int, float)) and qty <= self._low_stock_threshold:
                        low_stock.append({"id": p.get("id"), "title": p.get("title"), "quantity": qty})
                        self._alerts.append({"type": "low_stock", "product": p.get("title"), "quantity": qty,
                                             "timestamp": datetime.now(timezone.utc).isoformat()})
            return {"success": True, "total_products": len(products) if isinstance(products, list) else 0,
                    "low_stock": low_stock, "low_stock_count": len(low_stock)}
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def sales_summary(self) -> Dict:
        engine = self._get_engine()
        if not engine:
            return {"success": False, "error": "Shopify no configurado"}
        try:
            orders = await engine.get_orders(limit=100)
            if not isinstance(orders, list):
                return {"success": False, "error": "Formato de órdenes inesperado"}
            total_revenue = sum(float(o.get("total_price") or 0) for o in orders)
            fulfilled = sum(1 for o in orders if o.get("fulfillment_status") == "fulfilled")
            return {"success": True, "total_orders": len(orders), "fulfilled": fulfilled,
                    "pending": len(orders) - fulfilled, "total_revenue_usd": round(total_revenue, 2),
                    "avg_order_value": round(total_revenue / max(len(orders), 1), 2)}
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def full_report(self) -> str:
        sales = await self.sales_summary()
        inventory = await self.check_inventory()
        try:
            from apps.core.tools.ai_client import AIModel, get_ai_client
            import json as _json
            ai = get_ai_client()
            response = await ai.complete(
                system="Redacta un reporte de tienda Shopify en 4-6 oraciones. Directo, datos concretos, sin listas.",
                user=_json.dumps({"sales": sales, "inventory": inventory}, ensure_ascii=False, default=str)[:1200],
                model=AIModel.FAST, max_tokens=250, agent_name="shopify_bot_report",
            )
            return response.content.strip() if response.success else "No se pudo generar reporte."
        except Exception as e:
            return f"Error: {e}"

    def status(self) -> Dict:
        return {"bot": "ShopifyBot", "configured": self.is_configured(),
                "alerts": len(self._alerts), "last_check": self._last_check}

_instance: Optional[ShopifyBot] = None
def get_shopify_bot() -> ShopifyBot:
    global _instance
    if _instance is None:
        _instance = ShopifyBot()
    return _instance
