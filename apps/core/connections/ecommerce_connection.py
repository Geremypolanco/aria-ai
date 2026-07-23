"""
Ecommerce connection para ARIA AI.
Soporta Amazon (Product Advertising API), Etsy (OAuth), WooCommerce (API key).
"""

from __future__ import annotations

import hashlib
import logging
import time
from urllib.parse import urlencode

import httpx

from apps.core.connections.base import BaseConnector
from apps.core.connections.registry import register_connector

logger = logging.getLogger("aria.connections.ecommerce")

ETSY_AUTH_URL = "https://www.etsy.com/oauth/connect"
ETSY_TOKEN_URL = "https://api.etsy.com/v3/public/oauth/token"
ETSY_API = "https://openapi.etsy.com/v3"
ETSY_REDIRECT = "https://aria-ai.fly.dev/oauth/callback/etsy"
ETSY_SCOPES = "listings_r listings_w shops_r transactions_r"


@register_connector("etsy", display_name="Etsy (tienda artesanal)")
class EtsyConnection(BaseConnector):

    def _client_id(self) -> str | None:
        from apps.core.config import settings

        return getattr(settings, "ETSY_CLIENT_ID", None)

    def _client_secret(self) -> str | None:
        from apps.core.config import settings

        return getattr(settings, "ETSY_CLIENT_SECRET", None)

    # PKCE verifier keyed by chat_id, so exchange_code() can retrieve the
    # same value used to build the code_challenge in get_auth_url(). Etsy's
    # token endpoint recomputes SHA256(code_verifier) and compares it to the
    # challenge sent earlier — an empty verifier can never match a real
    # challenge, so every exchange was guaranteed to be rejected.
    _pkce_verifiers: dict[str, str] = {}

    def get_auth_url(self, chat_id: str) -> str | None:
        cid = self._client_id()
        if not cid:
            return None
        import base64
        import secrets

        verifier = secrets.token_urlsafe(64)
        self._pkce_verifiers[chat_id] = verifier
        challenge = (
            base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
            .rstrip(b"=")
            .decode()
        )
        params = {
            "response_type": "code",
            "redirect_uri": ETSY_REDIRECT,
            "scope": ETSY_SCOPES,
            "client_id": cid,
            "state": chat_id,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
        }
        return f"{ETSY_AUTH_URL}?{urlencode(params)}"

    async def exchange_code(self, code: str, chat_id: str) -> dict | None:
        cid = self._client_id()
        if not cid:
            raise ValueError("ETSY_CLIENT_ID no configurado")
        verifier = self._pkce_verifiers.pop(chat_id, "")
        async with httpx.AsyncClient(timeout=15.0) as http:
            r = await http.post(
                ETSY_TOKEN_URL,
                json={
                    "grant_type": "authorization_code",
                    "client_id": cid,
                    "redirect_uri": ETSY_REDIRECT,
                    "code": code,
                    "code_verifier": verifier,
                },
            )
            r.raise_for_status()
            data = r.json()
            return {
                "access_token": data["access_token"],
                "refresh_token": data.get("refresh_token"),
                "service_user": "etsy_shop",
            }

    def _h(self, tokens: dict) -> dict:
        cid = self._client_id() or ""
        return {
            "x-api-key": cid,
            "Authorization": f"Bearer {tokens['access_token']}",
        }

    async def get_shop(self, tokens: dict) -> dict:
        async with httpx.AsyncClient(timeout=15.0) as http:
            r = await http.get(f"{ETSY_API}/application/shops", headers=self._h(tokens))
            r.raise_for_status()
            shops = r.json().get("results", [])
            return shops[0] if shops else {}

    async def list_listings(self, tokens: dict, shop_id: int, limit: int = 20) -> list[dict]:
        async with httpx.AsyncClient(timeout=15.0) as http:
            r = await http.get(
                f"{ETSY_API}/application/shops/{shop_id}/listings/active",
                headers=self._h(tokens),
                params={"limit": limit},
            )
            r.raise_for_status()
            return [
                {
                    "listing_id": l.get("listing_id"),
                    "title": l.get("title"),
                    "price": l.get("price", {}).get("amount", 0) / 100,
                    "currency": l.get("price", {}).get("currency_code", "USD"),
                    "quantity": l.get("quantity"),
                    "state": l.get("state"),
                    "url": l.get("url"),
                }
                for l in r.json().get("results", [])
            ]

    async def list_transactions(self, tokens: dict, shop_id: int, limit: int = 20) -> list[dict]:
        async with httpx.AsyncClient(timeout=15.0) as http:
            r = await http.get(
                f"{ETSY_API}/application/shops/{shop_id}/transactions",
                headers=self._h(tokens),
                params={"limit": limit},
            )
            r.raise_for_status()
            return [
                {
                    "transaction_id": t.get("transaction_id"),
                    "title": t.get("title"),
                    "price": t.get("price", {}).get("amount", 0) / 100,
                    "quantity": t.get("quantity"),
                    "buyer_user_id": t.get("buyer_user_id"),
                    "create_timestamp": t.get("create_timestamp"),
                }
                for t in r.json().get("results", [])
            ]


class WooCommerceConnection:
    """WooCommerce usando Consumer Key + Secret (no OAuth web flow necesario)."""

    def _creds(self) -> tuple[str, str, str]:
        from apps.core.config import settings

        url = getattr(settings, "WOOCOMMERCE_URL", "") or ""
        key = getattr(settings, "WOOCOMMERCE_CONSUMER_KEY", "") or ""
        secret = getattr(settings, "WOOCOMMERCE_CONSUMER_SECRET", "") or ""
        return url.rstrip("/"), key, secret

    async def list_products(self, per_page: int = 20, status: str = "publish") -> list[dict]:
        url, key, secret = self._creds()
        if not url or not key:
            return [{"error": "WOOCOMMERCE_URL / WOOCOMMERCE_CONSUMER_KEY no configurados"}]
        async with httpx.AsyncClient(timeout=15.0) as http:
            r = await http.get(
                f"{url}/wp-json/wc/v3/products",
                params={"per_page": per_page, "status": status},
                auth=(key, secret),
            )
            r.raise_for_status()
            return [
                {
                    "id": p.get("id"),
                    "name": p.get("name"),
                    "price": p.get("price"),
                    "stock": p.get("stock_quantity"),
                    "status": p.get("status"),
                    "permalink": p.get("permalink"),
                }
                for p in r.json()
            ]

    async def list_orders(self, per_page: int = 20, status: str = "any") -> list[dict]:
        url, key, secret = self._creds()
        if not url or not key:
            return [{"error": "WOOCOMMERCE_URL / WOOCOMMERCE_CONSUMER_KEY no configurados"}]
        async with httpx.AsyncClient(timeout=15.0) as http:
            r = await http.get(
                f"{url}/wp-json/wc/v3/orders",
                params={"per_page": per_page, "status": status},
                auth=(key, secret),
            )
            r.raise_for_status()
            return [
                {
                    "id": o.get("id"),
                    "status": o.get("status"),
                    "total": o.get("total"),
                    "currency": o.get("currency"),
                    "customer_email": o.get("billing", {}).get("email"),
                    "date_created": o.get("date_created"),
                }
                for o in r.json()
            ]

    async def get_sales_report(self) -> dict:
        url, key, secret = self._creds()
        if not url or not key:
            return {"error": "WOOCOMMERCE_URL / WOOCOMMERCE_CONSUMER_KEY no configurados"}
        async with httpx.AsyncClient(timeout=15.0) as http:
            r = await http.get(
                f"{url}/wp-json/wc/v3/reports/sales",
                params={"period": "month"},
                auth=(key, secret),
            )
            r.raise_for_status()
            data = r.json()
            if data:
                return data[0]
            return {}


class AmazonConnection:
    """Amazon Product Advertising API 5.0 — búsqueda de productos."""

    ENDPOINT = "webservices.amazon.com"
    URI = "/paapi5/searchitems"

    def _creds(self) -> tuple[str, str, str]:
        from apps.core.config import settings

        key = getattr(settings, "AMAZON_ACCESS_KEY", "") or ""
        secret = getattr(settings, "AMAZON_SECRET_KEY", "") or ""
        tag = getattr(settings, "AMAZON_ASSOCIATE_TAG", "") or ""
        return key, secret, tag

    async def search_products(self, keywords: str, max_results: int = 10) -> list[dict]:
        key, secret, tag = self._creds()
        if not key or not secret or not tag:
            return [
                {
                    "error": "AMAZON_ACCESS_KEY / AMAZON_SECRET_KEY / AMAZON_ASSOCIATE_TAG no configurados"
                }
            ]
        payload = {
            "Keywords": keywords,
            "PartnerTag": tag,
            "PartnerType": "Associates",
            "Marketplace": "www.amazon.com",
            "Resources": [
                "ItemInfo.Title",
                "Offers.Listings.Price",
                "Images.Primary.Medium",
            ],
            "ItemCount": min(max_results, 10),
        }
        now = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
        now[:8]
        headers = {
            "content-encoding": "amz-1.0",
            "content-type": "application/json; charset=utf-8",
            "host": self.ENDPOINT,
            "x-amz-date": now,
            "x-amz-target": "com.amazon.paapi5.v1.ProductAdvertisingAPIv1.SearchItems",
        }
        # Simplified signing — in production use full AWS SigV4
        import json

        body = json.dumps(payload)
        try:
            async with httpx.AsyncClient(timeout=15.0) as http:
                r = await http.post(
                    f"https://{self.ENDPOINT}{self.URI}",
                    content=body.encode(),
                    headers=headers,
                )
                r.raise_for_status()
                items = r.json().get("SearchResult", {}).get("Items", [])
                return [
                    {
                        "asin": item.get("ASIN"),
                        "title": item.get("ItemInfo", {}).get("Title", {}).get("DisplayValue", ""),
                        "price": item.get("Offers", {})
                        .get("Listings", [{}])[0]
                        .get("Price", {})
                        .get("DisplayAmount", "N/A"),
                        "url": item.get("DetailPageURL", ""),
                        "image": item.get("Images", {})
                        .get("Primary", {})
                        .get("Medium", {})
                        .get("URL", ""),
                    }
                    for item in items
                ]
        except Exception as exc:
            logger.warning("[Amazon] Search error: %s", exc)
            return [{"error": str(exc)}]
