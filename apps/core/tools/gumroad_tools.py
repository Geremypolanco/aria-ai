"""
gumroad_tools.py — Crea y gestiona productos digitales en Gumroad automáticamente.
ARIA genera el contenido con IA y lo pone a la venta sin intervención manual.
"""
from __future__ import annotations
import logging
import httpx
from apps.core.config import settings

logger = logging.getLogger("aria.gumroad")

GUMROAD_API = "https://api.gumroad.com/v2"


class GumroadTools:
    """Crea ebooks, guias y recursos digitales en Gumroad para venta inmediata."""

    def __init__(self) -> None:
        self._http = httpx.AsyncClient(timeout=20.0)
        self._token = settings.GUMROAD_TOKEN

    async def create_product(
        self,
        name: str,
        description: str,
        price_cents: int = 497,
        tags: list[str] | None = None,
    ) -> dict:
        """
        Crea un producto digital en Gumroad.
        price_cents: precio en centavos (497 = $4.97)
        """
        if not self._token:
            return {"success": False, "error": "GUMROAD_TOKEN no configurado"}

        try:
            data = {
                "access_token": self._token,
                "name": name,
                "description": description,
                "price": price_cents,
                "type": "digital",
                "published": "true",
            }
            if tags:
                data["tags"] = ",".join(tags)

            resp = await self._http.post(f"{GUMROAD_API}/products", data=data)
            result = resp.json()

            if not result.get("success"):
                logger.error("[Gumroad] Error creando producto: %s", result)
                return {"success": False, "error": str(result)[:200]}

            product = result.get("product", {})
            product_id = product.get("id", "")
            product_url = product.get("short_url", "") or product.get("url", "")

            logger.info(
                "[Gumroad] Producto creado: '%s' | URL: %s | $%.2f",
                name, product_url, price_cents / 100,
            )
            return {
                "success": True,
                "product_id": product_id,
                "url": product_url,
                "name": name,
                "price_usd": round(price_cents / 100, 2),
                "platform": "gumroad",
            }

        except Exception as exc:
            logger.error("[Gumroad] Excepcion: %s", exc)
            return {"success": False, "error": str(exc)}

    async def list_products(self) -> list[dict]:
        """Lista todos los productos activos en Gumroad."""
        if not self._token:
            return []
        try:
            resp = await self._http.get(
                f"{GUMROAD_API}/products",
                params={"access_token": self._token},
            )
            data = resp.json()
            if data.get("success"):
                products = data.get("products", [])
                logger.info("[Gumroad] %d productos activos", len(products))
                return products
        except Exception as exc:
            logger.error("[Gumroad] Error listando: %s", exc)
        return []

    async def get_sales_summary(self) -> dict:
        """Obtiene resumen de ventas recientes."""
        if not self._token:
            return {"error": "no token", "total_sales": 0, "total_revenue_usd": 0}
        try:
            resp = await self._http.get(
                f"{GUMROAD_API}/sales",
                params={"access_token": self._token},
            )
            data = resp.json()
            if data.get("success"):
                sales = data.get("sales", [])
                total = sum(s.get("price", 0) / 100 for s in sales)
                return {
                    "total_sales": len(sales),
                    "total_revenue_usd": round(total, 2),
                    "recent_sales": [
                        {"product": s.get("product_name", ""), "amount": s.get("price", 0) / 100}
                        for s in sales[:5]
                    ],
                }
        except Exception as exc:
            logger.error("[Gumroad] Error ventas: %s", exc)
        return {"total_sales": 0, "total_revenue_usd": 0}

    def build_ebook_listing(self, topic: str, trending_context: str = "") -> dict:
        """
        Genera los metadatos para publicar un ebook.
        El contenido real lo genera la IA en el ciclo del orchestrator.
        """
        clean = topic.strip().title()
        return {
            "name": f"Guia Definitiva: {clean}",
            "description": (
                f"Todo lo que necesitas saber sobre {clean}. "
                "Guia practica con estrategias probadas, ejemplos reales "
                f"y pasos de accion inmediata. {trending_context}".strip()
            ),
            "price_cents": 497,
            "tags": [topic.lower().replace(" ", "-"), "guia", "digital", "ia", "tutorial"],
        }
