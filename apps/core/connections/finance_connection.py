"""
Financial data connections for ARIA AI.
Covers: QuickBooks (OAuth), Alpha Vantage (API key), CoinGecko (free), Plaid (API key).

Requires in Fly.io secrets:
  QUICKBOOKS_CLIENT_ID     → from developer.intuit.com
  QUICKBOOKS_CLIENT_SECRET → same place
  ALPHA_VANTAGE_API_KEY    → from alphavantage.co
"""

from __future__ import annotations

import logging
from urllib.parse import urlencode

import httpx

logger = logging.getLogger("aria.connections.finance")


# ── QUICKBOOKS ────────────────────────────────────────────────────────────────


class QuickBooksConnection:

    REDIRECT_URI = "https://aria-ai.fly.dev/oauth/callback/quickbooks"
    AUTH_URL = "https://appcenter.intuit.com/connect/oauth2"
    TOKEN_URL = "https://oauth.platform.intuit.com/oauth2/v1/tokens/bearer"
    SCOPES = "com.intuit.quickbooks.accounting"

    def _client_id(self) -> str | None:
        from apps.core.config import settings

        return getattr(settings, "QUICKBOOKS_CLIENT_ID", None)

    def _client_secret(self) -> str | None:
        from apps.core.config import settings

        return getattr(settings, "QUICKBOOKS_CLIENT_SECRET", None)

    def get_auth_url(self, chat_id: str) -> str | None:
        cid = self._client_id()
        if not cid:
            return None
        params = {
            "client_id": cid,
            "redirect_uri": self.REDIRECT_URI,
            "response_type": "code",
            "scope": self.SCOPES,
            "state": chat_id,
        }
        return f"{self.AUTH_URL}?{urlencode(params)}"

    async def exchange_code(self, code: str, chat_id: str, realm_id: str = "") -> dict | None:
        """Exchange auth code for tokens. realm_id comes from query param realmId."""
        cid = self._client_id()
        sec = self._client_secret()
        if not cid or not sec:
            raise ValueError("QUICKBOOKS_CLIENT_ID / QUICKBOOKS_CLIENT_SECRET not configured")
        import base64 as _b64

        credentials = _b64.b64encode(f"{cid}:{sec}".encode()).decode()
        async with httpx.AsyncClient(timeout=15.0) as http:
            r = await http.post(
                self.TOKEN_URL,
                headers={
                    "Authorization": f"Basic {credentials}",
                    "Content-Type": "application/x-www-form-urlencoded",
                },
                data={
                    "code": code,
                    "redirect_uri": self.REDIRECT_URI,
                    "grant_type": "authorization_code",
                },
            )
            r.raise_for_status()
            data = r.json()
            return {
                "access_token": data["access_token"],
                "refresh_token": data.get("refresh_token"),
                "expires_in": data.get("expires_in", 3600),
                "realm_id": realm_id,
                "service_user": realm_id,
            }

    def _base(self, tokens: dict) -> str:
        return f"https://quickbooks.api.intuit.com/v3/company/{tokens['realm_id']}"

    def _headers(self, tokens: dict) -> dict:
        return {
            "Authorization": f"Bearer {tokens['access_token']}",
            "Accept": "application/json",
        }

    async def get_profit_loss(self, tokens: dict, start_date: str, end_date: str) -> dict:
        """Fetch Profit & Loss report from QuickBooks."""
        async with httpx.AsyncClient(timeout=15.0) as http:
            r = await http.get(
                f"{self._base(tokens)}/reports/ProfitAndLoss",
                headers=self._headers(tokens),
                params={"start_date": start_date, "end_date": end_date},
            )
            r.raise_for_status()
            return r.json()

    async def list_invoices(self, tokens: dict, limit: int = 20) -> list[dict]:
        """List QuickBooks invoices."""
        async with httpx.AsyncClient(timeout=15.0) as http:
            query = f"SELECT * FROM Invoice MAXRESULTS {limit}"
            r = await http.get(
                f"{self._base(tokens)}/query",
                headers=self._headers(tokens),
                params={"query": query},
            )
            r.raise_for_status()
            invoices = r.json().get("QueryResponse", {}).get("Invoice", [])
            return [
                {
                    "id": inv.get("Id"),
                    "doc_number": inv.get("DocNumber"),
                    "customer": inv.get("CustomerRef", {}).get("name"),
                    "total": inv.get("TotalAmt"),
                    "balance": inv.get("Balance"),
                    "due_date": inv.get("DueDate"),
                    "status": inv.get("EmailStatus"),
                }
                for inv in invoices
            ]

    async def create_invoice(
        self, tokens: dict, customer_ref: str, amount: float, description: str = ""
    ) -> dict:
        """Create a new QuickBooks invoice."""
        body = {
            "Line": [
                {
                    "Amount": amount,
                    "DetailType": "SalesItemLineDetail",
                    "SalesItemLineDetail": {
                        "ItemRef": {"value": "1", "name": "Services"},
                        "Qty": 1,
                        "UnitPrice": amount,
                    },
                    "Description": description,
                }
            ],
            "CustomerRef": {"value": customer_ref},
        }
        async with httpx.AsyncClient(timeout=15.0) as http:
            r = await http.post(
                f"{self._base(tokens)}/invoice",
                headers={**self._headers(tokens), "Content-Type": "application/json"},
                json=body,
            )
            r.raise_for_status()
            data = r.json().get("Invoice", {})
            return {
                "success": True,
                "invoice_id": data.get("Id"),
                "doc_number": data.get("DocNumber"),
                "total": data.get("TotalAmt"),
            }

    async def list_customers(self, tokens: dict, limit: int = 20) -> list[dict]:
        """List QuickBooks customers."""
        async with httpx.AsyncClient(timeout=15.0) as http:
            query = f"SELECT * FROM Customer MAXRESULTS {limit}"
            r = await http.get(
                f"{self._base(tokens)}/query",
                headers=self._headers(tokens),
                params={"query": query},
            )
            r.raise_for_status()
            customers = r.json().get("QueryResponse", {}).get("Customer", [])
            return [
                {
                    "id": c.get("Id"),
                    "name": c.get("DisplayName"),
                    "email": c.get("PrimaryEmailAddr", {}).get("Address"),
                    "phone": c.get("PrimaryPhone", {}).get("FreeFormNumber"),
                    "balance": c.get("Balance"),
                }
                for c in customers
            ]

    async def get_balance_sheet(self, tokens: dict) -> dict:
        """Fetch Balance Sheet report from QuickBooks."""
        async with httpx.AsyncClient(timeout=15.0) as http:
            r = await http.get(
                f"{self._base(tokens)}/reports/BalanceSheet",
                headers=self._headers(tokens),
            )
            r.raise_for_status()
            return r.json()


# ── ALPHA VANTAGE ─────────────────────────────────────────────────────────────


class AlphaVantageConnection:

    BASE = "https://www.alphavantage.co/query"

    def _key(self) -> str | None:
        from apps.core.config import settings

        return getattr(settings, "ALPHA_VANTAGE_API_KEY", None)

    async def search_symbol(self, query: str) -> list[dict]:
        """Search for ticker symbols by keyword."""
        async with httpx.AsyncClient(timeout=15.0) as http:
            r = await http.get(
                self.BASE,
                params={
                    "function": "SYMBOL_SEARCH",
                    "keywords": query,
                    "apikey": self._key(),
                },
            )
            r.raise_for_status()
            matches = r.json().get("bestMatches", [])
            return [
                {
                    "symbol": m.get("1. symbol"),
                    "name": m.get("2. name"),
                    "type": m.get("3. type"),
                    "exchange": m.get("4. region"),
                }
                for m in matches
            ]

    async def get_stock_quote(self, symbol: str) -> dict:
        """Get real-time stock quote for a symbol."""
        async with httpx.AsyncClient(timeout=15.0) as http:
            r = await http.get(
                self.BASE,
                params={
                    "function": "GLOBAL_QUOTE",
                    "symbol": symbol,
                    "apikey": self._key(),
                },
            )
            r.raise_for_status()
            q = r.json().get("Global Quote", {})
            return {
                "symbol": q.get("01. symbol"),
                "price": q.get("05. price"),
                "change": q.get("09. change"),
                "change_percent": q.get("10. change percent"),
                "volume": q.get("06. volume"),
                "high": q.get("03. high"),
                "low": q.get("04. low"),
                "previous_close": q.get("08. previous close"),
                "latest_day": q.get("07. latest trading day"),
            }

    async def get_time_series_daily(self, symbol: str, outputsize: str = "compact") -> list[dict]:
        """Get daily OHLCV data. Returns last 30 days when outputsize='compact'."""
        async with httpx.AsyncClient(timeout=15.0) as http:
            r = await http.get(
                self.BASE,
                params={
                    "function": "TIME_SERIES_DAILY",
                    "symbol": symbol,
                    "outputsize": outputsize,
                    "apikey": self._key(),
                },
            )
            r.raise_for_status()
            series = r.json().get("Time Series (Daily)", {})
            result = []
            for date, values in list(series.items())[:30]:
                result.append(
                    {
                        "date": date,
                        "open": values.get("1. open"),
                        "high": values.get("2. high"),
                        "low": values.get("3. low"),
                        "close": values.get("4. close"),
                        "volume": values.get("5. volume"),
                    }
                )
            return result

    async def get_forex_rate(self, from_currency: str, to_currency: str) -> dict:
        """Get real-time exchange rate between two currencies."""
        async with httpx.AsyncClient(timeout=15.0) as http:
            r = await http.get(
                self.BASE,
                params={
                    "function": "CURRENCY_EXCHANGE_RATE",
                    "from_currency": from_currency,
                    "to_currency": to_currency,
                    "apikey": self._key(),
                },
            )
            r.raise_for_status()
            rate = r.json().get("Realtime Currency Exchange Rate", {})
            return {
                "from": rate.get("1. From_Currency Code"),
                "to": rate.get("3. To_Currency Code"),
                "rate": rate.get("5. Exchange Rate"),
                "last_refreshed": rate.get("6. Last Refreshed"),
                "bid": rate.get("8. Bid Price"),
                "ask": rate.get("9. Ask Price"),
            }

    async def get_crypto_price(self, symbol: str, market: str = "USD") -> dict:
        """Get crypto exchange rate for a given symbol."""
        async with httpx.AsyncClient(timeout=15.0) as http:
            r = await http.get(
                self.BASE,
                params={
                    "function": "CURRENCY_EXCHANGE_RATE",
                    "from_currency": symbol,
                    "to_currency": market,
                    "apikey": self._key(),
                },
            )
            r.raise_for_status()
            rate = r.json().get("Realtime Currency Exchange Rate", {})
            return {
                "symbol": rate.get("1. From_Currency Code"),
                "name": rate.get("2. From_Currency Name"),
                "market": rate.get("3. To_Currency Code"),
                "price": rate.get("5. Exchange Rate"),
                "last_refreshed": rate.get("6. Last Refreshed"),
            }


# ── COINGECKO ─────────────────────────────────────────────────────────────────


class CoinGeckoConnection:

    BASE = "https://api.coingecko.com/api/v3"

    async def get_price(self, coin_ids: str, vs_currencies: str = "usd") -> dict:
        """Get current price(s) for one or more coins. coin_ids='bitcoin,ethereum'."""
        async with httpx.AsyncClient(timeout=15.0) as http:
            r = await http.get(
                f"{self.BASE}/simple/price",
                params={
                    "ids": coin_ids,
                    "vs_currencies": vs_currencies,
                    "include_market_cap": True,
                    "include_24hr_change": True,
                },
            )
            r.raise_for_status()
            return r.json()

    async def get_trending(self) -> list[dict]:
        """Get top trending coins on CoinGecko."""
        async with httpx.AsyncClient(timeout=15.0) as http:
            r = await http.get(f"{self.BASE}/search/trending")
            r.raise_for_status()
            coins = r.json().get("coins", [])
            return [
                {
                    "id": c["item"].get("id"),
                    "name": c["item"].get("name"),
                    "symbol": c["item"].get("symbol"),
                    "market_cap_rank": c["item"].get("market_cap_rank"),
                    "thumb": c["item"].get("thumb"),
                }
                for c in coins
            ]

    async def get_coin_info(self, coin_id: str) -> dict:
        """Get detailed info for a specific coin."""
        async with httpx.AsyncClient(timeout=15.0) as http:
            r = await http.get(
                f"{self.BASE}/coins/{coin_id}",
                params={
                    "localization": False,
                    "tickers": False,
                    "community_data": False,
                    "developer_data": False,
                },
            )
            r.raise_for_status()
            d = r.json()
            market = d.get("market_data", {})
            return {
                "id": d.get("id"),
                "name": d.get("name"),
                "symbol": d.get("symbol"),
                "current_price": market.get("current_price", {}).get("usd"),
                "market_cap": market.get("market_cap", {}).get("usd"),
                "price_change_24h": market.get("price_change_percentage_24h"),
                "total_volume": market.get("total_volume", {}).get("usd"),
                "high_24h": market.get("high_24h", {}).get("usd"),
                "low_24h": market.get("low_24h", {}).get("usd"),
                "description": d.get("description", {}).get("en", "")[:500],
            }

    async def get_market_chart(self, coin_id: str, days: int = 7) -> list[dict]:
        """Get price history for a coin over the given number of days."""
        async with httpx.AsyncClient(timeout=15.0) as http:
            r = await http.get(
                f"{self.BASE}/coins/{coin_id}/market_chart",
                params={"vs_currency": "usd", "days": days},
            )
            r.raise_for_status()
            prices = r.json().get("prices", [])
            return [{"timestamp": p[0], "price": p[1]} for p in prices]

    async def search_coins(self, query: str) -> list[dict]:
        """Search for coins by name or symbol."""
        async with httpx.AsyncClient(timeout=15.0) as http:
            r = await http.get(f"{self.BASE}/search", params={"query": query})
            r.raise_for_status()
            coins = r.json().get("coins", [])
            return [
                {
                    "id": c.get("id"),
                    "name": c.get("name"),
                    "symbol": c.get("symbol"),
                    "market_cap_rank": c.get("market_cap_rank"),
                    "thumb": c.get("thumb"),
                }
                for c in coins
            ]
