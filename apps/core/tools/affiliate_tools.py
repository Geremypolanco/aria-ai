"""
ARIA Affiliate Tools — Affiliate program management.

Supported platforms:
- Amazon Associates (PA API v5 — requires AMAZON_ACCESS_KEY, AMAZON_SECRET_KEY, AMAZON_ASSOCIATE_TAG)
- Amazon link builder (tag only — requires AMAZON_ASSOCIATE_TAG)
- ClickBank (hop links — no API required)
- Hotmart (Latam affiliates — no API required)
- Gumroad / LemonSqueezy (own products)

Principle: If an API isn't configured, say so explicitly.
NEVER returns hardcoded data as if it were real search results.
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
        Builds an Amazon affiliate link using the Associates tag.
        Requires AMAZON_ASSOCIATE_TAG to be configured.
        """
        affiliate_tag = tag or getattr(settings, "AMAZON_ASSOCIATE_TAG", None)
        if not affiliate_tag:
            logger.warning(
                "[Affiliate] AMAZON_ASSOCIATE_TAG not configured — link without affiliate tag"
            )
            return f"https://www.amazon.com/dp/{asin}"
        return f"https://www.amazon.com/dp/{asin}?tag={affiliate_tag}"

    async def search_amazon_products(self, keywords: str, category: str = "All") -> dict[str, Any]:
        """
        Searches for products on Amazon using PA API v5.
        Requires: AMAZON_ACCESS_KEY, AMAZON_SECRET_KEY, AMAZON_ASSOCIATE_TAG

        If they're not configured, returns an explicit error.
        Does NOT return hardcoded data as a fallback.
        """
        access_key = getattr(settings, "AMAZON_ACCESS_KEY", None)
        secret_key = getattr(settings, "AMAZON_SECRET_KEY", None)
        partner_tag = getattr(settings, "AMAZON_ASSOCIATE_TAG", None)

        missing = []
        if not access_key:
            missing.append("AMAZON_ACCESS_KEY")
        if not secret_key:
            missing.append("AMAZON_SECRET_KEY")
        if not partner_tag:
            missing.append("AMAZON_ASSOCIATE_TAG")

        if missing:
            return {
                "success": False,
                "error": f"Amazon PA API not available. Missing secrets: {', '.join(missing)}. "
                f"Sign up at: https://affiliate-program.amazon.com/",
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
                        (item.get("Offers", {}).get("Listings") or [{}])[0]
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
        Builds a ClickBank hop link.
        affiliate_id comes from CLICKBANK_AFFILIATE_ID in secrets.
        If it isn't configured, say so explicitly.
        """
        cb_id = affiliate_id or getattr(settings, "CLICKBANK_AFFILIATE_ID", None)
        if not cb_id:
            return {
                "success": False,
                "error": "CLICKBANK_AFFILIATE_ID not configured. Sign up at clickbank.com and add the ID to secrets.",
                "link": None,
            }
        link = f"https://{cb_id}.{vendor}.hop.clickbank.net/"
        return {"success": True, "link": link, "vendor": vendor, "affiliate_id": cb_id}

    # ── HOTMART ───────────────────────────────────────────

    def build_hotmart_link(
        self, product_id: str, affiliate_id: str | None = None
    ) -> dict[str, Any]:
        """
        Builds a Hotmart affiliate link.
        affiliate_id comes from HOTMART_AFFILIATE_ID in secrets.
        """
        hm_id = affiliate_id or getattr(settings, "HOTMART_AFFILIATE_ID", None)
        if not hm_id:
            return {
                "success": False,
                "error": "HOTMART_AFFILIATE_ID not configured. Sign up at hotmart.com and add the ID to secrets.",
                "link": None,
            }
        link = f"https://go.hotmart.com/{product_id}?ap={hm_id}"
        return {"success": True, "link": link, "product_id": product_id}

    # ── OWN GUMROAD PRODUCTS ───────────────────────────────

    async def get_own_products(self) -> dict[str, Any]:
        """
        Fetches your own Gumroad products to generate affiliate links.
        Requires GUMROAD_TOKEN.
        """
        token = getattr(settings, "GUMROAD_TOKEN", None)
        if not token:
            return {
                "success": False,
                "error": "GUMROAD_TOKEN not configured. Add the Gumroad token to secrets.",
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

    # ── CONTENT INJECTION ─────────────────────────────────

    def inject_affiliate_links(
        self,
        content: str,
        topic: str,
        platform: str = "amazon",
    ) -> dict[str, Any]:
        """
        Injects affiliate links into content based on the topic.
        Only injects real links — if credentials are missing, reports which ones.
        """
        available_platforms: list[str] = []
        unavailable: list[str] = []

        if getattr(settings, "AMAZON_ASSOCIATE_TAG", None):
            available_platforms.append("amazon")
        else:
            unavailable.append("amazon (requires AMAZON_ASSOCIATE_TAG)")

        if getattr(settings, "CLICKBANK_AFFILIATE_ID", None):
            available_platforms.append("clickbank")
        else:
            unavailable.append("clickbank (requires CLICKBANK_AFFILIATE_ID)")

        if getattr(settings, "HOTMART_AFFILIATE_ID", None):
            available_platforms.append("hotmart")
        else:
            unavailable.append("hotmart (requires HOTMART_AFFILIATE_ID)")

        if not available_platforms:
            return {
                "success": False,
                "error": f"No affiliate platforms configured. Missing: {', '.join(unavailable)}",
                "content": content,
                "links_injected": 0,
            }

        injected_content = content
        links_injected = 0

        # Amazon tag-based only (doesn't require PA API, just the tag)
        if "amazon" in available_platforms and platform in ("amazon", "all"):
            import urllib.parse

            tag = getattr(settings, "AMAZON_ASSOCIATE_TAG", "")
            # No specific ASIN is available here (only topic/content) —
            # build_amazon_link("", tag) used to generate a broken link (/dp/?tag=...,
            # with no product). A search link with the tag is a real link
            # that actually works and attributes the commission.
            search_url = f"https://www.amazon.com/s?k={urllib.parse.quote(topic)}&tag={tag}"
            cta = (
                f"\n\n---\n*Affiliate links: The products mentioned can be found "
                f"on [Amazon]({search_url}). "
                f"As an Amazon affiliate, I earn a commission on qualifying purchases.*"
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

    # ── AVAILABILITY REPORT ────────────────────────────────

    def capability_report(self) -> dict[str, Any]:
        """
        Reports which affiliate functions are available and which aren't.
        Call this before using this module to know what's possible.
        """
        amazon_tag = getattr(settings, "AMAZON_ASSOCIATE_TAG", None)
        amazon_pa = all(
            [
                getattr(settings, "AMAZON_ACCESS_KEY", None),
                getattr(settings, "AMAZON_SECRET_KEY", None),
                getattr(settings, "AMAZON_ASSOCIATE_TAG", None),
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
                    ("GUMROAD_TOKEN (own products)", gumroad),
                ]
                if not avail
            ],
        }
