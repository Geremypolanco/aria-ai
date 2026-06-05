"""
ARIA Affiliate Tools — Gestión de programas de afiliados.

Plataformas:
- Amazon Associates (PA API o tag-based)
- ClickBank (hop links)
- Hotmart (afiliados Latam)
- ShareASale / CJ Affiliate
- Gumroad / LemonSqueezy (productos propios)

Sin costo, solo necesitas registrarte en cada programa.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Optional
from urllib.parse import quote_plus

import httpx

from apps.core.config import settings

logger = logging.getLogger("aria.affiliate")


class AffiliateTools:

    def __init__(self) -> None:
        self._http = httpx.AsyncClient(timeout=20.0)

    # ── AMAZON ASSOCIATES ─────────────────────────────────

    def build_amazon_link(self, asin: str, tag: Optional[str] = None) -> str:
        """
        Construye un link de afiliado Amazon.
        No requiere API — solo el tag de tu cuenta Associates.
        Registro: affiliate-program.amazon.com
        """
        affiliate_tag = tag or settings.AMAZON_ASSOCIATE_TAG or "aria-ai-20"
        return f"https://www.amazon.com/dp/{asin}?tag={affiliate_tag}"

    async def search_amazon_products(self, keywords: str, category: str = "All") -> list[dict]:
        """
        Busca productos en Amazon usando PA API v5.
        Requiere: AMAZON_PA_ACCESS_KEY, AMAZON_PA_SECRET_KEY, AMAZON_PA_PARTNER_TAG
        Si no están configurados, usa el catálogo local.
        """
        if not all([settings.AMAZON_PA_ACCESS_KEY, settings.AMAZON_PA_SECRET_KEY, settings.AMAZON_PA_PARTNER_TAG]):
            # Fallback: retorna productos del catálogo local por keyword
            return self._search_local_catalog(keywords)

        try:
            import hmac
            import hashlib
            import datetime
            import json

            host = "webservices.amazon.com"
            region = "us-east-1"
            service = "ProductAdvertisingAPI"
            endpoint = f"https://{host}/paapi5/searchitems"

            payload = {
                "Keywords": keywords,
                "SearchIndex": category,
                "Resources": ["ItemInfo.Title", "Offers.Listings.Price", "Images.Primary.Medium"],
                "PartnerTag": settings.AMAZON_PA_PARTNER_TAG,
                "PartnerType": "Associates",
                "Marketplace": "www.amazon.com",
            }

            body = json.dumps(payload)
            amz_date = datetime.datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
            date_stamp = amz_date[:8]

            # Canonical request
            content_type = "application/json; charset=utf-8"
            headers_str = f"content-type:{content_type}\nhost:{host}\nx-amz-date:{amz_date}\nx-amz-target:com.amazon.paapi5.v1.ProductAdvertisingAPIv1.SearchItems\n"
            signed_headers = "content-type;host;x-amz-date;x-amz-target"
            payload_hash = hashlib.sha256(body.encode()).hexdigest()
            canonical = f"POST\n/paapi5/searchitems\n\n{headers_str}\n{signed_headers}\n{payload_hash}"

            # String to sign
            credential_scope = f"{date_stamp}/{region}/{service}/aws4_request"
            string_to_sign = f"AWS4-HMAC-SHA256\n{amz_date}\n{credential_scope}\n{hashlib.sha256(canonical.encode()).hexdigest()}"

            # Signing key
            def sign(key, msg):
                return hmac.new(key, msg.encode(), hashlib.sha256).digest()

            k_secret = f"AWS4{settings.AMAZON_PA_SECRET_KEY}".encode()
            k_date = sign(k_secret, date_stamp)
            k_region = sign(k_date, region)
            k_service = sign(k_region, service)
            k_signing = sign(k_service, "aws4_request")
            signature = hmac.new(k_signing, string_to_sign.encode(), hashlib.sha256).hexdigest()

            auth = f"AWS4-HMAC-SHA256 Credential={settings.AMAZON_PA_ACCESS_KEY}/{credential_scope}, SignedHeaders={signed_headers}, Signature={signature}"

            res = await self._http.post(
                endpoint,
                headers={
                    "content-type": content_type,
                    "host": host,
                    "x-amz-date": amz_date,
                    "x-amz-target": "com.amazon.paapi5.v1.ProductAdvertisingAPIv1.SearchItems",
                    "Authorization": auth,
                },
                content=body,
            )

            if res.status_code == 200:
                items = res.json().get("SearchResult", {}).get("Items", [])
                products = []
                for item in items[:5]:
                    asin = item.get("ASIN", "")
                    title = item.get("ItemInfo", {}).get("Title", {}).get("DisplayValue", "")
                    price = item.get("Offers", {}).get("Listings", [{}])[0].get("Price", {}).get("DisplayAmount", "")
                    products.append({
                        "asin": asin,
                        "title": title,
                        "price": price,
                        "affiliate_url": self.build_amazon_link(asin),
                    })
                return products
            else:
                logger.warning("[Affiliate] Amazon PA API error: %s", res.text[:200])
                return self._search_local_catalog(keywords)

        except Exception as exc:
            logger.error("[Affiliate] Amazon search error: %s", exc)
            return self._search_local_catalog(keywords)

    def _search_local_catalog(self, keywords: str) -> list[dict]:
        """Busca en el catálogo local cuando PA API no está disponible."""
        from apps.core.tools.content_pipeline import AFFILIATE_CATALOG
        kw_lower = keywords.lower()
        results = []
        for category, products in AFFILIATE_CATALOG.items():
            for p in products:
                if p["keyword"].lower() in kw_lower or kw_lower in p["keyword"].lower():
                    results.append({
                        "asin": p["asin"],
                        "title": p["title"],
                        "price": "Ver precio",
                        "affiliate_url": self.build_amazon_link(p["asin"]),
                    })
        return results[:5]

    # ── CLICKBANK ─────────────────────────────────────────

    def build_clickbank_hoplink(self, vendor: str, product_id: str = "") -> str:
        """
        Construye hoplink de ClickBank.
        Registro gratuito: accounts.clickbank.com
        Requiere: CLICKBANK_AFFILIATE_ID (tu nickname de afiliado)
        """
        affiliate = settings.CLICKBANK_AFFILIATE_ID or ""
        if not affiliate:
            return ""
        return f"https://hop.clickbank.net/?affiliate={affiliate}&vendor={vendor}"

    async def get_clickbank_marketplace(self, category: str = "ebusiness", limit: int = 5) -> list[dict]:
        """
        Obtiene productos del marketplace de ClickBank via API.
        Requiere: CLICKBANK_API_KEY (developer key)
        """
        if not settings.CLICKBANK_API_KEY:
            # Retorna productos hardcodeados populares
            return self._get_clickbank_defaults(category)

        try:
            res = await self._http.get(
                f"https://api.clickbank.com/rest/1.3/products/list",
                headers={
                    "Accept": "application/json",
                    "Authorization": settings.CLICKBANK_API_KEY,
                },
                params={"category": category, "rows": limit, "gravity": "50"},
            )
            if res.status_code == 200:
                products = res.json().get("products", {}).get("product", [])
                return [
                    {
                        "vendor": p.get("vendor", ""),
                        "title": p.get("title", ""),
                        "commission": f"{p.get('commission', 50)}%",
                        "gravity": p.get("gravity", 0),
                        "hoplink": self.build_clickbank_hoplink(p.get("vendor", "")),
                    }
                    for p in products[:limit]
                ]
        except Exception as exc:
            logger.warning("[Affiliate] ClickBank API error: %s", exc)

        return self._get_clickbank_defaults(category)

    def _get_clickbank_defaults(self, category: str) -> list[dict]:
        """Productos ClickBank de alta conversión por categoría."""
        defaults = {
            "ebusiness": [
                {"vendor": "vidsy", "title": "Video Marketing Blaster", "commission": "75%", "gravity": 45, "hoplink": self.build_clickbank_hoplink("vidsy")},
                {"vendor": "amzsellerp", "title": "Amazon Seller Pro", "commission": "65%", "gravity": 38, "hoplink": self.build_clickbank_hoplink("amzsellerp")},
            ],
            "health": [
                {"vendor": "flatbelly", "title": "Flat Belly Fix", "commission": "75%", "gravity": 55, "hoplink": self.build_clickbank_hoplink("flatbelly")},
            ],
            "self-help": [
                {"vendor": "mindmaster", "title": "Mind Master", "commission": "70%", "gravity": 40, "hoplink": self.build_clickbank_hoplink("mindmaster")},
            ],
        }
        return defaults.get(category, defaults["ebusiness"])

    # ── HOTMART ───────────────────────────────────────────

    async def get_hotmart_products(self, limit: int = 5) -> list[dict]:
        """
        Obtiene productos de Hotmart para promover.
        Requiere: HOTMART_CLIENT_ID, HOTMART_CLIENT_SECRET, HOTMART_BASIC_TOKEN
        Registro gratuito: hotmart.com
        """
        if not settings.HOTMART_BASIC_TOKEN:
            return self._get_hotmart_defaults()

        try:
            # Obtener token
            token_res = await self._http.post(
                "https://api-sec-vlc.hotmart.com/security/oauth/token",
                headers={"Authorization": f"Basic {settings.HOTMART_BASIC_TOKEN}", "Content-Type": "application/json"},
                json={"grant_type": "client_credentials"},
            )
            if token_res.status_code != 200:
                return self._get_hotmart_defaults()

            token = token_res.json().get("access_token")
            # Obtener productos del afiliado
            prod_res = await self._http.get(
                "https://developers.hotmart.com/payments/api/v1/sales/summary",
                headers={"Authorization": f"Bearer {token}"},
            )
            if prod_res.status_code == 200:
                return prod_res.json().get("items", [])[:limit]

        except Exception as exc:
            logger.warning("[Affiliate] Hotmart error: %s", exc)

        return self._get_hotmart_defaults()

    def _get_hotmart_defaults(self) -> list[dict]:
        return [
            {"title": "Curso IA para Negocios", "commission": "50%", "platform": "hotmart", "category": "technology"},
            {"title": "Marketing Digital Completo", "commission": "40%", "platform": "hotmart", "category": "marketing"},
            {"title": "Emprendimiento Digital", "commission": "50%", "platform": "hotmart", "category": "business"},
        ]

    # ── GUMROAD (PRODUCTOS PROPIOS) ───────────────────────

    async def create_gumroad_product(self, name: str, description: str, price_cents: int, file_url: str = "") -> dict:
        """
        Crea un producto en Gumroad automáticamente.
        Requiere: GUMROAD_TOKEN (ya existente en config)
        El producto se crea inmediatamente y es monetizable.
        """
        if not settings.GUMROAD_TOKEN:
            return {"success": False, "error": "GUMROAD_TOKEN no configurado"}

        try:
            data = {
                "name": name,
                "description": description,
                "price": price_cents,  # en centavos USD
                "published": True,
                "require_shipping": False,
            }
            res = await self._http.post(
                "https://api.gumroad.com/v2/products",
                headers={"Authorization": f"Bearer {settings.GUMROAD_TOKEN}"},
                data=data,
            )
            if res.status_code == 200:
                product = res.json().get("product", {})
                url = product.get("short_url", "")
                logger.info("[Affiliate] Gumroad product created: %s", url)
                return {"success": True, "url": url, "id": product.get("id"), "name": name}
            else:
                return {"success": False, "error": res.text[:200]}

        except Exception as exc:
            logger.error("[Affiliate] Gumroad error: %s", exc)
            return {"success": False, "error": str(exc)}

    async def create_lemonsqueezy_product(self, name: str, description: str, price_cents: int) -> dict:
        """
        Crea producto en LemonSqueezy (alternativa a Gumroad).
        Requiere: LEMONSQUEEZY_API_KEY, LEMONSQUEEZY_STORE_ID
        Registro: app.lemonsqueezy.com
        """
        if not settings.LEMONSQUEEZY_API_KEY or not settings.LEMONSQUEEZY_STORE_ID:
            return {"success": False, "skipped": True}

        try:
            res = await self._http.post(
                "https://api.lemonsqueezy.com/v1/products",
                headers={
                    "Authorization": f"Bearer {settings.LEMONSQUEEZY_API_KEY}",
                    "Accept": "application/vnd.api+json",
                    "Content-Type": "application/vnd.api+json",
                },
                json={
                    "data": {
                        "type": "products",
                        "attributes": {
                            "name": name,
                            "description": description,
                            "status": "published",
                        },
                        "relationships": {
                            "store": {"data": {"type": "stores", "id": settings.LEMONSQUEEZY_STORE_ID}},
                        },
                    }
                },
            )
            if res.status_code in (200, 201):
                data = res.json().get("data", {})
                return {"success": True, "id": data.get("id"), "name": name}
            else:
                return {"success": False, "error": res.text[:200]}

        except Exception as exc:
            return {"success": False, "error": str(exc)}

    # ── AUTO-CREAR PRODUCTOS DIGITALES ────────────────────

    async def auto_create_digital_product(self, topic: str, category: str) -> dict:
        """
        Genera y publica un producto digital automáticamente:
        1. IA genera el contenido del producto (ebook/checklist/template)
        2. Lo publica en Gumroad con precio
        3. Retorna el link de ventas
        """
        try:
            from apps.core.tools.ai_client import AIModel, get_ai_client
            ai = await get_ai_client()

            # Generar contenido del producto
            content_res = await ai.complete(
                system="Eres un experto en crear productos digitales que se venden en Gumroad y LemonSqueezy. Creas contenido de alta calidad y valor real.",
                user=f"""Crea un producto digital completo sobre: {topic}
                
Tipo: eBook/Guía práctica (categoría: {category})

Genera:
1. Título atractivo del producto
2. Descripción de ventas (200 palabras)  
3. Precio sugerido en USD (entre $7 y $27)
4. Índice de 8-10 capítulos
5. Introducción del capítulo 1 (300 palabras)

Formato: usa JSON con campos: title, description, price_usd, chapters, intro""",
                model=AIModel.STRATEGY,
                max_tokens=2000,
                json_mode=True,
            )

            if not content_res or not content_res.success:
                return {"success": False, "error": "AI falló generando producto"}

            import json as json_lib
            try:
                product_data = json_lib.loads(content_res.content) if isinstance(content_res.content, str) else content_res.content
            except Exception:
                return {"success": False, "error": "No se pudo parsear el JSON del producto"}

            title = product_data.get("title", f"Guía sobre {topic}")
            description = product_data.get("description", "")
            price_usd = float(product_data.get("price_usd", 9.99))
            price_cents = int(price_usd * 100)

            # Publicar en Gumroad
            result = await self.create_gumroad_product(title, description, price_cents)

            if result.get("success"):
                logger.info("[Affiliate] Producto digital creado: %s — %s", title, result.get("url"))
                # Guardar en Supabase
                await self._save_product(result, product_data, price_usd)

            return {**result, "product_data": product_data, "price_usd": price_usd}

        except Exception as exc:
            logger.error("[Affiliate] auto_create_digital_product error: %s", exc)
            return {"success": False, "error": str(exc)}

    async def _save_product(self, result: dict, product_data: dict, price: float) -> None:
        try:
            from apps.core.memory.supabase_client import get_db
            import json as json_lib
            db = get_db()
            db._client.table("products").insert({
                "name": product_data.get("title", "")[:200],
                "type": "digital_product",
                "platform": "gumroad",
                "url": result.get("url", ""),
                "price": price,
                "status": "active",
                "metadata": json_lib.dumps(product_data),
            }).execute()
        except Exception as exc:
            logger.warning("[Affiliate] Error saving product: %s", exc)
