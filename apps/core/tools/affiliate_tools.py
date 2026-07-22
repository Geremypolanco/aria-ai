"""
ARIA Affiliate Tools — Gestion de programas de afiliados.

Plataformas soportadas:
- Amazon Associates (PA API v5 — requiere AMAZON_PA_ACCESS_KEY, AMAZON_PA_SECRET_KEY, AMAZON_PA_PARTNER_TAG)
- Amazon link builder (solo tag — requiere AMAZON_ASSOCIATE_TAG)
- ClickBank (hop links — no requiere API)
- Hotmart (afiliados Latam — no requiere API)
- Gumroad / LemonSqueezy (productos propios)

Principio: Si una API no esta configurada, lo dice explicitamente.
NUNCA retorna datos hardcodeados como si fueran resultados reales de busqueda.
"""

from __future__ import annotations

import datetime
import hashlib
import hmac
import json
import logging
from typing import Any

import httpx

from apps.core.config import settings

logger = logging.getLogger("aria.affiliate")


class AffiliateTools:

    def __init__(self) -> None:
        self._http = httpx.AsyncClient(timeout=20.0)

    # ── AMAZON ASSOCIATES ─────────────────────────────────

    def build_amazon_link(self, asin: str, tag: str | None = None) -> str:
        """
        Construye un link de afiliado Amazon usando el tag de Associates.
        Requiere AMAZON_ASSOCIATE_TAG configurado.
        """
        affiliate_tag = tag or getattr(settings, "AMAZON_ASSOCIATE_TAG", None)
        if not affiliate_tag:
            logger.warning(
                "[Affiliate] AMAZON_ASSOCIATE_TAG no configurado — link sin tag de afiliado"
            )
            return f"https://www.amazon.com/dp/{asin}"
        return f"https://www.amazon.com/dp/{asin}?tag={affiliate_tag}"

    async def search_amazon_products(self, keywords: str, category: str = "All") -> dict[str, Any]:
        """
        Busca productos en Amazon usando PA API v5.
        Requiere: AMAZON_PA_ACCESS_KEY, AMAZON_PA_SECRET_KEY, AMAZON_PA_PARTNER_TAG

        Si no estan configurados, retorna error explicito.
        NO retorna datos hardcodeados como fallback.
        """
        access_key = getattr(settings, "AMAZON_PA_ACCESS_KEY", None)
        secret_key = getattr(settings, "AMAZON_PA_SECRET_KEY", None)
        partner_tag = getattr(settings, "AMAZON_PA_PARTNER_TAG", None)

        missing = []
        if not access_key:
            missing.append("AMAZON_PA_ACCESS_KEY")
        if not secret_key:
            missing.append("AMAZON_PA_SECRET_KEY")
        if not partner_tag:
            missing.append("AMAZON_PA_PARTNER_TAG")

        if missing:
            return {
                "success": False,
                "error": f"Amazon PA API no disponible. Faltan secrets: {', '.join(missing)}. "
                f"Registrate en: https://affiliate-program.amazon.com/",
                "products": [],
                "available": False,
            }

        try:
            host = "webservices.amazon.com"
            region = "us-east-1"
            endpoint = f"https://{host}/paapi5/searchitems"

            payload = {
                "Keywords": keywords,
                "SearchIndex": category,
                "Resources": [
                    "ItemInfo.Title",
                    "Offers.Listings.Price",
                    "Images.Primary.Medium",
                    "ItemInfo.Features",
                ],
                "PartnerTag": partner_tag,
                "PartnerType": "Associates",
                "Marketplace": "www.amazon.com",
            }

            body = json.dumps(payload)
            amz_date = datetime.datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
            date_stamp = amz_date[:8]

            # AWS SigV4
            canonical_headers = (
                f"content-encoding:amz-1.0\n"
                f"content-type:application/json; charset=utf-8\n"
                f"host:{host}\n"
                f"x-amz-date:{amz_date}\n"
                f"x-amz-target:com.amazon.paapi5.v1.ProductAdvertisingAPIv1.SearchItems\n"
            )
            signed_headers = "content-encoding;content-type;host;x-amz-date;x-amz-target"
            payload_hash = hashlib.sha256(body.encode()).hexdigest()
            canonical_request = (
                f"POST\n/paapi5/searchitems\n\n"
                f"{canonical_headers}\n{signed_headers}\n{payload_hash}"
            )
            credential_scope = f"{date_stamp}/{region}/{region}/aws4_request"
            string_to_sign = (
                f"AWS4-HMAC-SHA256\n{amz_date}\n{credential_scope}\n"
                + hashlib.sha256(canonical_request.encode()).hexdigest()
            )

            def sign(key: bytes, msg: str) -> bytes:
                return hmac.new(key, msg.encode(), hashlib.sha256).digest()

            signing_key = sign(
                sign(sign(sign(f"AWS4{secret_key}".encode(), date_stamp), region), region),
                "aws4_request",
            )
            signature = hmac.new(signing_key, string_to_sign.encode(), hashlib.sha256).hexdigest()
            auth_header = (
                f"AWS4-HMAC-SHA256 Credential={access_key}/{credential_scope}, "
                f"SignedHeaders={signed_headers}, Signature={signature}"
            )

            res = await self._http.post(
                endpoint,
                content=body,
                headers={
                    "Content-Encoding": "amz-1.0",
                    "Content-Type": "application/json; charset=utf-8",
                    "Host": host,
                    "X-Amz-Date": amz_date,
                    "X-Amz-Target": "com.amazon.paapi5.v1.ProductAdvertisingAPIv1.SearchItems",
                    "Authorization": auth_header,
                },
            )

            if res.status_code == 200:
                items = res.json().get("SearchResult", {}).get("Items", [])
                products = []
                for item in items:
                    asin = item.get("ASIN", "")
                    title = item.get("ItemInfo", {}).get("Title", {}).get("DisplayValue", "")
                    price = (
                        item.get("Offers", {})
                        .get("Listings", [{}])[0]
                        .get("Price", {})
                        .get("DisplayAmount", "N/A")
                    )
                    image = (
                        item.get("Images", {}).get("Primary", {}).get("Medium", {}).get("URL", "")
                    )
                    affiliate_link = self.build_amazon_link(asin)
                    products.append(
                        {
                            "asin": asin,
                            "title": title,
                            "price": price,
                            "image": image,
                            "affiliate_link": affiliate_link,
                        }
                    )
                return {
                    "success": True,
                    "products": products,
                    "count": len(products),
                    "query": keywords,
                }

            return {
                "success": False,
                "error": f"Amazon PA API HTTP {res.status_code}: {res.text[:300]}",
                "products": [],
            }

        except Exception as exc:
            logger.error("[Affiliate] search_amazon_products error: %s", exc)
            return {"success": False, "error": str(exc), "products": []}

    # ── CLICKBANK ─────────────────────────────────────────

    def build_clickbank_link(self, vendor: str, affiliate_id: str | None = None) -> dict[str, Any]:
        """
        Construye hop link de ClickBank.
        affiliate_id proviene de CLICKBANK_AFFILIATE_ID en secrets.
        Si no esta configurado, lo dice explicitamente.
        """
        cb_id = affiliate_id or getattr(settings, "CLICKBANK_AFFILIATE_ID", None)
        if not cb_id:
            return {
                "success": False,
                "error": "CLICKBANK_AFFILIATE_ID no configurado. Registrate en clickbank.com y agrega el ID a secrets.",
                "link": None,
            }
        link = f"https://{cb_id}.{vendor}.hop.clickbank.net/"
        return {"success": True, "link": link, "vendor": vendor, "affiliate_id": cb_id}

    # ── HOTMART ───────────────────────────────────────────

    def build_hotmart_link(
        self, product_id: str, affiliate_id: str | None = None
    ) -> dict[str, Any]:
        """
        Construye link de afiliado Hotmart.
        affiliate_id proviene de HOTMART_AFFILIATE_ID en secrets.
        """
        hm_id = affiliate_id or getattr(settings, "HOTMART_AFFILIATE_ID", None)
        if not hm_id:
            return {
                "success": False,
                "error": "HOTMART_AFFILIATE_ID no configurado. Registrate en hotmart.com y agrega el ID a secrets.",
                "link": None,
            }
        link = f"https://go.hotmart.com/{product_id}?ap={hm_id}"
        return {"success": True, "link": link, "product_id": product_id}

    # ── GUMROAD PROPIOS ───────────────────────────────────

    async def get_own_products(self) -> dict[str, Any]:
        """
        Obtiene los productos propios de Gumroad para generar links de afiliado.
        Requiere GUMROAD_TOKEN.
        """
        token = getattr(settings, "GUMROAD_TOKEN", None)
        if not token:
            return {
                "success": False,
                "error": "GUMROAD_TOKEN no configurado. Agrega el token de Gumroad a secrets.",
                "products": [],
            }
        try:
            res = await self._http.get(
                "https://api.gumroad.com/v2/products",
                params={"access_token": token},
            )
            if res.status_code == 200:
                products = res.json().get("products", [])
                return {
                    "success": True,
                    "products": [
                        {
                            "id": p.get("id"),
                            "name": p.get("name"),
                            "short_url": p.get("short_url"),
                            "price": p.get("formatted_price"),
                            "sales_count": p.get("sales_count", 0),
                        }
                        for p in products
                    ],
                    "count": len(products),
                }
            return {
                "success": False,
                "error": f"Gumroad API HTTP {res.status_code}: {res.text[:200]}",
                "products": [],
            }
        except Exception as exc:
            logger.error("[Affiliate] get_own_products error: %s", exc)
            return {"success": False, "error": str(exc), "products": []}

    # ── INYECCION EN CONTENIDO ────────────────────────────

    def inject_affiliate_links(
        self,
        content: str,
        topic: str,
        platform: str = "amazon",
    ) -> dict[str, Any]:
        """
        Inyecta links de afiliado en contenido basado en el tema.
        Solo inyecta links reales — si no hay credenciales, reporta cuales faltan.
        """
        available_platforms: list[str] = []
        unavailable: list[str] = []

        if getattr(settings, "AMAZON_ASSOCIATE_TAG", None):
            available_platforms.append("amazon")
        else:
            unavailable.append("amazon (requiere AMAZON_ASSOCIATE_TAG)")

        if getattr(settings, "CLICKBANK_AFFILIATE_ID", None):
            available_platforms.append("clickbank")
        else:
            unavailable.append("clickbank (requiere CLICKBANK_AFFILIATE_ID)")

        if getattr(settings, "HOTMART_AFFILIATE_ID", None):
            available_platforms.append("hotmart")
        else:
            unavailable.append("hotmart (requiere HOTMART_AFFILIATE_ID)")

        if not available_platforms:
            return {
                "success": False,
                "error": f"No hay plataformas de afiliado configuradas. Faltan: {', '.join(unavailable)}",
                "content": content,
                "links_injected": 0,
            }

        injected_content = content
        links_injected = 0

        # Solo amazon tag-based (no requiere PA API, solo el tag)
        if "amazon" in available_platforms and platform in ("amazon", "all"):
            import urllib.parse

            tag = getattr(settings, "AMAZON_ASSOCIATE_TAG", "")
            # No hay ASIN especifico disponible aqui (solo topic/content) —
            # build_amazon_link("", tag) generaba un link roto (/dp/?tag=...,
            # sin producto). Un link de busqueda con el tag es un link real
            # que efectivamente funciona y atribuye la comision.
            search_url = f"https://www.amazon.com/s?k={urllib.parse.quote(topic)}&tag={tag}"
            cta = (
                f"\n\n---\n*Links de afiliado: Los productos mencionados pueden encontrarse "
                f"en [Amazon]({search_url}). "
                f"Como afiliado de Amazon, recibo una comision por compras elegibles.*"
            )
            injected_content += cta
            links_injected += 1

        return {
            "success": True,
            "content": injected_content,
            "links_injected": links_injected,
            "platforms_used": available_platforms,
            "platforms_unavailable": unavailable,
        }

    # ── REPORTE DE DISPONIBILIDAD ─────────────────────────

    def capability_report(self) -> dict[str, Any]:
        """
        Reporta que funciones de afiliados estan disponibles y cuales no.
        Llamar antes de usar este modulo para saber que se puede hacer.
        """
        amazon_tag = getattr(settings, "AMAZON_ASSOCIATE_TAG", None)
        amazon_pa = all(
            [
                getattr(settings, "AMAZON_PA_ACCESS_KEY", None),
                getattr(settings, "AMAZON_PA_SECRET_KEY", None),
                getattr(settings, "AMAZON_PA_PARTNER_TAG", None),
            ]
        )
        clickbank = bool(getattr(settings, "CLICKBANK_AFFILIATE_ID", None))
        hotmart = bool(getattr(settings, "HOTMART_AFFILIATE_ID", None))
        gumroad = bool(getattr(settings, "GUMROAD_TOKEN", None))

        return {
            "amazon_link_building": bool(amazon_tag),
            "amazon_product_search": amazon_pa,
            "clickbank": clickbank,
            "hotmart": hotmart,
            "gumroad_own_products": gumroad,
            "any_available": any([amazon_tag, amazon_pa, clickbank, hotmart, gumroad]),
            "missing": [
                name
                for name, avail in [
                    ("AMAZON_ASSOCIATE_TAG", amazon_tag),
                    ("Amazon PA API (3 keys)", amazon_pa),
                    ("CLICKBANK_AFFILIATE_ID", clickbank),
                    ("HOTMART_AFFILIATE_ID", hotmart),
                    ("GUMROAD_TOKEN (productos propios)", gumroad),
                ]
                if not avail
            ],
        }
