"""
CRM OAuth connections for ARIA AI.
  - HubSpotConnection  → HubSpot CRM (contacts, deals, companies)
  - SalesforceConnection → Salesforce CRM (leads, opportunities)

Requiere en Fly.io secrets:
  HUBSPOT_CLIENT_ID     → developers.hubspot.com → Apps
  HUBSPOT_CLIENT_SECRET → mismo lugar
  HUBSPOT_API_KEY       → HubSpot private app token (alternativa sin OAuth)
  SALESFORCE_CLIENT_ID     → setup.salesforce.com → App Manager
  SALESFORCE_CLIENT_SECRET → mismo lugar
"""

from __future__ import annotations

import logging
from typing import Any
from urllib.parse import urlencode

import httpx

logger = logging.getLogger("aria.connections.crm")

# ── HUBSPOT CONSTANTS ──────────────────────────────────────────────────────────

HUBSPOT_REDIRECT_URI = "https://aria-ai.fly.dev/oauth/callback/hubspot"
HUBSPOT_AUTH_URL = "https://app.hubspot.com/oauth/authorize"
HUBSPOT_TOKEN_URL = "https://api.hubapi.com/oauth/v1/token"
HUBSPOT_BASE = "https://api.hubapi.com"

# ── SALESFORCE CONSTANTS ───────────────────────────────────────────────────────

SALESFORCE_REDIRECT_URI = "https://aria-ai.fly.dev/oauth/callback/salesforce"
SALESFORCE_AUTH_URL = "https://login.salesforce.com/services/oauth2/authorize"
SALESFORCE_TOKEN_URL = "https://login.salesforce.com/services/oauth2/token"


# ══════════════════════════════════════════════════════════════════════════════
#  HubSpot
# ══════════════════════════════════════════════════════════════════════════════


class HubSpotConnection:

    REDIRECT_URI = HUBSPOT_REDIRECT_URI
    AUTH_URL = HUBSPOT_AUTH_URL
    TOKEN_URL = HUBSPOT_TOKEN_URL

    def _api_key(self) -> str | None:
        from apps.core.config import settings

        return getattr(settings, "HUBSPOT_API_KEY", None)

    def _client_id(self) -> str | None:
        from apps.core.config import settings

        return getattr(settings, "HUBSPOT_CLIENT_ID", None)

    def _client_secret(self) -> str | None:
        from apps.core.config import settings

        return getattr(settings, "HUBSPOT_CLIENT_SECRET", None)

    def get_auth_url(self, chat_id: str) -> str | None:
        cid = self._client_id()
        if not cid:
            return None
        params = {
            "client_id": cid,
            "redirect_uri": HUBSPOT_REDIRECT_URI,
            "scope": "crm.objects.contacts.read crm.objects.contacts.write "
            "crm.objects.deals.read crm.objects.deals.write "
            "crm.objects.companies.read",
            "response_type": "code",
            "state": chat_id,
        }
        return f"{HUBSPOT_AUTH_URL}?{urlencode(params)}"

    async def exchange_code(self, code: str, chat_id: str) -> dict | None:
        cid = self._client_id()
        sec = self._client_secret()
        if not cid or not sec:
            raise ValueError("HUBSPOT_CLIENT_ID / HUBSPOT_CLIENT_SECRET no configurados")
        async with httpx.AsyncClient(timeout=15.0) as http:
            r = await http.post(
                HUBSPOT_TOKEN_URL,
                data={
                    "grant_type": "authorization_code",
                    "client_id": cid,
                    "client_secret": sec,
                    "redirect_uri": HUBSPOT_REDIRECT_URI,
                    "code": code,
                },
            )
            r.raise_for_status()
            data = r.json()
            # Fetch account info for service_user
            info_r = await http.get(
                f"{HUBSPOT_BASE}/oauth/v1/access-tokens/{data['access_token']}",
            )
            hub_user = (
                info_r.json().get("user", "unknown") if info_r.status_code == 200 else "unknown"
            )
            return {
                "access_token": data["access_token"],
                "refresh_token": data.get("refresh_token"),
                "expires_in": data.get("expires_in", 21600),
                "scope": data.get("scope", ""),
                "service_user": hub_user,
            }

    async def refresh_token(self, tokens: dict) -> dict:
        cid = self._client_id()
        sec = self._client_secret()
        async with httpx.AsyncClient(timeout=15.0) as http:
            r = await http.post(
                HUBSPOT_TOKEN_URL,
                data={
                    "grant_type": "refresh_token",
                    "client_id": cid,
                    "client_secret": sec,
                    "refresh_token": tokens["refresh_token"],
                },
            )
            r.raise_for_status()
            data = r.json()
            tokens["access_token"] = data["access_token"]
            if data.get("refresh_token"):
                tokens["refresh_token"] = data["refresh_token"]
            return tokens

    def _headers(self, tokens_or_key: Any) -> dict:
        """Accepts either a tokens dict (OAuth) or a bare API key string."""
        if isinstance(tokens_or_key, str):
            return {"Authorization": f"Bearer {tokens_or_key}"}
        # OAuth token dict
        return {"Authorization": f"Bearer {tokens_or_key['access_token']}"}

    def _auth(self, tokens: Any) -> Any:
        """Return tokens dict or fall back to the private app API key."""
        if tokens:
            return tokens
        key = self._api_key()
        if key:
            return key
        raise ValueError("No HubSpot credentials — provide OAuth tokens or HUBSPOT_API_KEY")

    # ── CONTACTS ─────────────────────────────────────────────────────────

    async def list_contacts(self, tokens: Any, limit: int = 20) -> list[dict]:
        """List CRM contacts."""
        auth = self._auth(tokens)
        params = {
            "limit": limit,
            "properties": "firstname,lastname,email,company,phone",
        }
        async with httpx.AsyncClient(timeout=15.0) as http:
            r = await http.get(
                f"{HUBSPOT_BASE}/crm/v3/objects/contacts",
                headers=self._headers(auth),
                params=params,
            )
            if r.status_code != 200:
                raise RuntimeError(f"HubSpot list_contacts error {r.status_code}: {r.text[:200]}")
            results = r.json().get("results", [])
            return [
                {
                    "id": c.get("id"),
                    "firstname": c.get("properties", {}).get("firstname", ""),
                    "lastname": c.get("properties", {}).get("lastname", ""),
                    "email": c.get("properties", {}).get("email", ""),
                    "company": c.get("properties", {}).get("company", ""),
                    "phone": c.get("properties", {}).get("phone", ""),
                }
                for c in results
            ]

    async def create_contact(
        self,
        tokens: Any,
        email: str,
        firstname: str = "",
        lastname: str = "",
        company: str = "",
        phone: str = "",
    ) -> dict:
        """Create a new CRM contact."""
        auth = self._auth(tokens)
        payload = {
            "properties": {
                "email": email,
                "firstname": firstname,
                "lastname": lastname,
                "company": company,
                "phone": phone,
            }
        }
        async with httpx.AsyncClient(timeout=15.0) as http:
            r = await http.post(
                f"{HUBSPOT_BASE}/crm/v3/objects/contacts",
                headers={**self._headers(auth), "Content-Type": "application/json"},
                json=payload,
            )
            r.raise_for_status()
            d = r.json()
            return {
                "success": True,
                "id": d.get("id"),
                "email": d.get("properties", {}).get("email", email),
            }

    # ── DEALS ────────────────────────────────────────────────────────────

    async def list_deals(self, tokens: Any, limit: int = 20) -> list[dict]:
        """List CRM deals."""
        auth = self._auth(tokens)
        params = {
            "limit": limit,
            "properties": "dealname,amount,dealstage,closedate",
        }
        async with httpx.AsyncClient(timeout=15.0) as http:
            r = await http.get(
                f"{HUBSPOT_BASE}/crm/v3/objects/deals",
                headers=self._headers(auth),
                params=params,
            )
            if r.status_code != 200:
                raise RuntimeError(f"HubSpot list_deals error {r.status_code}: {r.text[:200]}")
            results = r.json().get("results", [])
            return [
                {
                    "id": d.get("id"),
                    "dealname": d.get("properties", {}).get("dealname", ""),
                    "amount": d.get("properties", {}).get("amount", "0"),
                    "stage": d.get("properties", {}).get("dealstage", ""),
                    "closedate": d.get("properties", {}).get("closedate", ""),
                }
                for d in results
            ]

    async def create_deal(
        self, tokens: Any, dealname: str, amount: float = 0, stage: str = "appointmentscheduled"
    ) -> dict:
        """Create a new CRM deal."""
        auth = self._auth(tokens)
        payload = {
            "properties": {
                "dealname": dealname,
                "amount": str(amount),
                "dealstage": stage,
            }
        }
        async with httpx.AsyncClient(timeout=15.0) as http:
            r = await http.post(
                f"{HUBSPOT_BASE}/crm/v3/objects/deals",
                headers={**self._headers(auth), "Content-Type": "application/json"},
                json=payload,
            )
            r.raise_for_status()
            d = r.json()
            return {
                "success": True,
                "id": d.get("id"),
                "dealname": d.get("properties", {}).get("dealname", dealname),
                "stage": d.get("properties", {}).get("dealstage", stage),
            }

    # ── COMPANIES ────────────────────────────────────────────────────────

    async def list_companies(self, tokens: Any, limit: int = 20) -> list[dict]:
        """List CRM companies."""
        auth = self._auth(tokens)
        params = {
            "limit": limit,
            "properties": "name,domain,industry,city,phone,numberofemployees",
        }
        async with httpx.AsyncClient(timeout=15.0) as http:
            r = await http.get(
                f"{HUBSPOT_BASE}/crm/v3/objects/companies",
                headers=self._headers(auth),
                params=params,
            )
            if r.status_code != 200:
                raise RuntimeError(f"HubSpot list_companies error {r.status_code}: {r.text[:200]}")
            results = r.json().get("results", [])
            return [
                {
                    "id": c.get("id"),
                    "name": c.get("properties", {}).get("name", ""),
                    "domain": c.get("properties", {}).get("domain", ""),
                    "industry": c.get("properties", {}).get("industry", ""),
                    "city": c.get("properties", {}).get("city", ""),
                    "phone": c.get("properties", {}).get("phone", ""),
                    "employees": c.get("properties", {}).get("numberofemployees", ""),
                }
                for c in results
            ]

    # ── SEARCH ───────────────────────────────────────────────────────────

    async def search_contacts(self, tokens: Any, query: str) -> list[dict]:
        """Search contacts by name, email, or company."""
        auth = self._auth(tokens)
        payload = {
            "query": query,
            "properties": ["firstname", "lastname", "email", "company", "phone"],
            "limit": 20,
        }
        async with httpx.AsyncClient(timeout=15.0) as http:
            r = await http.post(
                f"{HUBSPOT_BASE}/crm/v3/objects/contacts/search",
                headers={**self._headers(auth), "Content-Type": "application/json"},
                json=payload,
            )
            if r.status_code != 200:
                raise RuntimeError(f"HubSpot search_contacts error {r.status_code}: {r.text[:200]}")
            results = r.json().get("results", [])
            return [
                {
                    "id": c.get("id"),
                    "firstname": c.get("properties", {}).get("firstname", ""),
                    "lastname": c.get("properties", {}).get("lastname", ""),
                    "email": c.get("properties", {}).get("email", ""),
                    "company": c.get("properties", {}).get("company", ""),
                    "phone": c.get("properties", {}).get("phone", ""),
                }
                for c in results
            ]


# ══════════════════════════════════════════════════════════════════════════════
#  Salesforce
# ══════════════════════════════════════════════════════════════════════════════


class SalesforceConnection:

    REDIRECT_URI = SALESFORCE_REDIRECT_URI
    AUTH_URL = SALESFORCE_AUTH_URL
    TOKEN_URL = SALESFORCE_TOKEN_URL

    def _client_id(self) -> str | None:
        from apps.core.config import settings

        return getattr(settings, "SALESFORCE_CLIENT_ID", None)

    def _client_secret(self) -> str | None:
        from apps.core.config import settings

        return getattr(settings, "SALESFORCE_CLIENT_SECRET", None)

    def get_auth_url(self, chat_id: str) -> str | None:
        cid = self._client_id()
        if not cid:
            return None
        params = {
            "client_id": cid,
            "redirect_uri": SALESFORCE_REDIRECT_URI,
            "response_type": "code",
            "state": chat_id,
        }
        return f"{SALESFORCE_AUTH_URL}?{urlencode(params)}"

    async def exchange_code(self, code: str, chat_id: str) -> dict | None:
        cid = self._client_id()
        sec = self._client_secret()
        if not cid or not sec:
            raise ValueError("SALESFORCE_CLIENT_ID / SALESFORCE_CLIENT_SECRET no configurados")
        async with httpx.AsyncClient(timeout=15.0) as http:
            r = await http.post(
                SALESFORCE_TOKEN_URL,
                data={
                    "grant_type": "authorization_code",
                    "client_id": cid,
                    "client_secret": sec,
                    "redirect_uri": SALESFORCE_REDIRECT_URI,
                    "code": code,
                },
            )
            r.raise_for_status()
            data = r.json()
            return {
                "access_token": data["access_token"],
                "refresh_token": data.get("refresh_token"),
                "instance_url": data.get("instance_url", ""),
                "token_type": data.get("token_type", "Bearer"),
                "scope": data.get("scope", ""),
                "service_user": data.get("id", "").split("/")[-1] if data.get("id") else "unknown",
            }

    async def refresh_token(self, tokens: dict) -> dict:
        cid = self._client_id()
        sec = self._client_secret()
        async with httpx.AsyncClient(timeout=15.0) as http:
            r = await http.post(
                SALESFORCE_TOKEN_URL,
                data={
                    "grant_type": "refresh_token",
                    "client_id": cid,
                    "client_secret": sec,
                    "refresh_token": tokens["refresh_token"],
                },
            )
            r.raise_for_status()
            data = r.json()
            tokens["access_token"] = data["access_token"]
            if data.get("instance_url"):
                tokens["instance_url"] = data["instance_url"]
            return tokens

    def _headers(self, tokens: dict) -> dict:
        return {"Authorization": f"Bearer {tokens['access_token']}"}

    def _base(self, tokens: dict) -> str:
        """Return the versioned Salesforce REST API base URL."""
        instance_url = tokens.get("instance_url", "")
        return f"{instance_url}/services/data/v58.0"

    # ── SOQL ─────────────────────────────────────────────────────────────

    async def soql_query(self, tokens: dict, query: str) -> list[dict]:
        """Execute a SOQL query and return records."""
        async with httpx.AsyncClient(timeout=20.0) as http:
            r = await http.get(
                f"{self._base(tokens)}/query",
                headers=self._headers(tokens),
                params={"q": query},
            )
            if r.status_code != 200:
                raise RuntimeError(f"Salesforce SOQL error {r.status_code}: {r.text[:200]}")
            return r.json().get("records", [])

    # ── LEADS ────────────────────────────────────────────────────────────

    async def list_leads(self, tokens: dict, limit: int = 20) -> list[dict]:
        """List CRM leads."""
        query = (
            f"SELECT Id, FirstName, LastName, Email, Company, Phone, Status "
            f"FROM Lead ORDER BY CreatedDate DESC LIMIT {limit}"
        )
        records = await self.soql_query(tokens, query)
        return [
            {
                "id": r.get("Id"),
                "firstname": r.get("FirstName", ""),
                "lastname": r.get("LastName", ""),
                "email": r.get("Email", ""),
                "company": r.get("Company", ""),
                "phone": r.get("Phone", ""),
                "status": r.get("Status", ""),
            }
            for r in records
        ]

    async def create_lead(
        self, tokens: dict, lastname: str, email: str, company: str, phone: str = ""
    ) -> dict:
        """Create a new lead."""
        payload = {
            "LastName": lastname,
            "Email": email,
            "Company": company,
            "Phone": phone,
        }
        async with httpx.AsyncClient(timeout=15.0) as http:
            r = await http.post(
                f"{self._base(tokens)}/sobjects/Lead",
                headers={**self._headers(tokens), "Content-Type": "application/json"},
                json=payload,
            )
            r.raise_for_status()
            d = r.json()
            return {
                "success": d.get("success", True),
                "id": d.get("id"),
                "lastname": lastname,
                "email": email,
                "company": company,
            }

    # ── OPPORTUNITIES ────────────────────────────────────────────────────

    async def list_opportunities(self, tokens: dict, limit: int = 20) -> list[dict]:
        """List CRM opportunities."""
        query = (
            f"SELECT Id, Name, StageName, CloseDate, Amount, AccountId "
            f"FROM Opportunity ORDER BY CreatedDate DESC LIMIT {limit}"
        )
        records = await self.soql_query(tokens, query)
        return [
            {
                "id": r.get("Id"),
                "name": r.get("Name", ""),
                "stage": r.get("StageName", ""),
                "close_date": r.get("CloseDate", ""),
                "amount": r.get("Amount", 0),
                "account_id": r.get("AccountId", ""),
            }
            for r in records
        ]

    async def create_opportunity(
        self, tokens: dict, name: str, stage: str, close_date: str, amount: float = 0
    ) -> dict:
        """Create a new opportunity.

        close_date: 'YYYY-MM-DD' string.
        stage: e.g. 'Prospecting', 'Qualification', 'Proposal/Price Quote', 'Closed Won'.
        """
        payload = {
            "Name": name,
            "StageName": stage,
            "CloseDate": close_date,
            "Amount": amount,
        }
        async with httpx.AsyncClient(timeout=15.0) as http:
            r = await http.post(
                f"{self._base(tokens)}/sobjects/Opportunity",
                headers={**self._headers(tokens), "Content-Type": "application/json"},
                json=payload,
            )
            r.raise_for_status()
            d = r.json()
            return {
                "success": d.get("success", True),
                "id": d.get("id"),
                "name": name,
                "stage": stage,
                "close_date": close_date,
                "amount": amount,
            }
