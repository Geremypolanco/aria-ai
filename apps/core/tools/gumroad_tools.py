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
        file_content: str | None = None,
    ) -> dict:
        """
        Crea un producto digital en Gumroad y adjunta un archivo descargable.
        price_cents: precio en centavos (497 = $4.97)
        file_content: contenido HTML/texto del archivo descargable (optional)
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

            # Upload downloadable file so product is purchasable with a real deliverable
            if product_id:
                content_to_upload = file_content or description
                html_bytes = self._build_html_file(name, content_to_upload).encode("utf-8")
                safe_filename = name[:40].replace(" ", "_").replace("/", "_") + ".html"
                await self._upload_file(product_id, safe_filename, html_bytes)

            logger.info(
                "[Gumroad] Producto creado: '%s' | URL: %s | $%.2f",
                name,
                product_url,
                price_cents / 100,
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

    def _build_html_file(self, title: str, content: str) -> str:
        """Generate a simple HTML page from the product content."""
        paragraphs = "".join(f"<p>{line}</p>" for line in content.split("\n") if line.strip())
        return f"""<!DOCTYPE html>
<html lang="en">
<head><meta charset="UTF-8"><title>{title}</title>
<style>body{{font-family:Georgia,serif;max-width:700px;margin:40px auto;padding:0 20px;line-height:1.7;color:#222}}
h1{{color:#1a1a2e;border-bottom:2px solid #eee;padding-bottom:10px}}
p{{margin:12px 0}}</style></head>
<body><h1>{title}</h1>{paragraphs}</body></html>"""

    async def _upload_file(self, product_id: str, filename: str, content: bytes) -> bool:
        """Upload a file to an existing Gumroad product via PUT /products/:id."""
        try:
            resp = await self._http.put(
                f"{GUMROAD_API}/products/{product_id}",
                files={"file": (filename, content, "text/html")},
                data={"access_token": self._token},
            )
            ok = resp.json().get("success", False)
            if ok:
                logger.info("[Gumroad] File uploaded to product %s", product_id)
            else:
                logger.warning("[Gumroad] File upload returned: %s", resp.text[:200])
            return ok
        except Exception as exc:
            logger.warning("[Gumroad] File upload error (product still live): %s", exc)
            return False

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
