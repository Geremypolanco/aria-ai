"""
Email marketing connection para ARIA AI.
Soporta Klaviyo, ActiveCampaign, ConvertKit (Kit), Brevo (Sendinblue), Postmark.
Todos usan API key — no requieren OAuth web flow.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

logger = logging.getLogger("aria.connections.email_marketing")


class KlaviyoConnection:
    """Klaviyo via Private API Key."""

    API = "https://a.klaviyo.com/api"

    def _key(self) -> str | None:
        from apps.core.config import settings

        return getattr(settings, "KLAVIYO_API_KEY", None)

    def _h(self) -> dict:
        return {
            "Authorization": f"Klaviyo-API-Key {self._key()}",
            "revision": "2024-02-15",
            "Accept": "application/json",
        }

    async def get_lists(self) -> list[dict]:
        key = self._key()
        if not key:
            return [{"error": "KLAVIYO_API_KEY no configurado"}]
        async with httpx.AsyncClient(timeout=15.0) as http:
            r = await http.get(f"{self.API}/lists", headers=self._h())
            r.raise_for_status()
            return [
                {
                    "id": l["id"],
                    "name": l["attributes"].get("name"),
                    "created": l["attributes"].get("created"),
                }
                for l in r.json().get("data", [])
            ]

    async def add_profile(
        self, email: str, first_name: str = "", last_name: str = "", list_id: str = ""
    ) -> dict:
        key = self._key()
        if not key:
            return {"error": "KLAVIYO_API_KEY no configurado"}
        profile_payload = {
            "data": {
                "type": "profile",
                "attributes": {"email": email, "first_name": first_name, "last_name": last_name},
            }
        }
        async with httpx.AsyncClient(timeout=15.0) as http:
            r = await http.post(
                f"{self.API}/profiles",
                headers={**self._h(), "Content-Type": "application/json"},
                json=profile_payload,
            )
            if r.status_code in (200, 201, 409):
                profile_id = r.json().get("data", {}).get("id")
                if profile_id and list_id:
                    await http.post(
                        f"{self.API}/lists/{list_id}/relationships/profiles",
                        headers={**self._h(), "Content-Type": "application/json"},
                        json={"data": [{"type": "profile", "id": profile_id}]},
                    )
                return {"success": True, "profile_id": profile_id}
            return {"success": False, "status": r.status_code}

    async def get_metrics(self) -> list[dict]:
        key = self._key()
        if not key:
            return [{"error": "KLAVIYO_API_KEY no configurado"}]
        async with httpx.AsyncClient(timeout=15.0) as http:
            r = await http.get(f"{self.API}/metrics", headers=self._h())
            r.raise_for_status()
            return [
                {"id": m["id"], "name": m["attributes"].get("name")}
                for m in r.json().get("data", [])
            ]

    async def get_campaigns(self) -> list[dict]:
        key = self._key()
        if not key:
            return [{"error": "KLAVIYO_API_KEY no configurado"}]
        async with httpx.AsyncClient(timeout=15.0) as http:
            r = await http.get(f"{self.API}/campaigns", headers=self._h())
            r.raise_for_status()
            return [
                {
                    "id": c["id"],
                    "name": c["attributes"].get("name"),
                    "status": c["attributes"].get("status"),
                    "send_time": c["attributes"].get("scheduled_at"),
                }
                for c in r.json().get("data", [])
            ]


class ActiveCampaignConnection:
    """ActiveCampaign via API URL + Key."""

    def _creds(self) -> tuple[str, str]:
        from apps.core.config import settings

        url = getattr(settings, "ACTIVECAMPAIGN_URL", "") or ""
        key = getattr(settings, "ACTIVECAMPAIGN_API_KEY", "") or ""
        return url.rstrip("/"), key

    def _h(self, key: str) -> dict:
        return {"Api-Token": key, "Accept": "application/json"}

    async def get_lists(self) -> list[dict]:
        url, key = self._creds()
        if not url or not key:
            return [{"error": "ACTIVECAMPAIGN_URL / ACTIVECAMPAIGN_API_KEY no configurados"}]
        async with httpx.AsyncClient(timeout=15.0) as http:
            r = await http.get(f"{url}/api/3/lists", headers=self._h(key))
            r.raise_for_status()
            return [
                {
                    "id": l.get("id"),
                    "name": l.get("name"),
                    "subscriber_count": l.get("subscriber_count"),
                }
                for l in r.json().get("lists", [])
            ]

    async def add_contact(self, email: str, first_name: str = "", last_name: str = "") -> dict:
        url, key = self._creds()
        if not url or not key:
            return {"error": "ACTIVECAMPAIGN_URL / ACTIVECAMPAIGN_API_KEY no configurados"}
        async with httpx.AsyncClient(timeout=15.0) as http:
            r = await http.post(
                f"{url}/api/3/contacts",
                headers={**self._h(key), "Content-Type": "application/json"},
                json={"contact": {"email": email, "firstName": first_name, "lastName": last_name}},
            )
            if r.status_code in (200, 201):
                return {"success": True, "id": r.json().get("contact", {}).get("id")}
            return {"success": False, "status": r.status_code}

    async def get_campaigns(self) -> list[dict]:
        url, key = self._creds()
        if not url or not key:
            return [{"error": "ACTIVECAMPAIGN_URL / ACTIVECAMPAIGN_API_KEY no configurados"}]
        async with httpx.AsyncClient(timeout=15.0) as http:
            r = await http.get(f"{url}/api/3/campaigns", headers=self._h(key))
            r.raise_for_status()
            return [
                {
                    "id": c.get("id"),
                    "name": c.get("name"),
                    "status": c.get("status"),
                    "send_amt": c.get("send_amt"),
                    "open_rate": c.get("open_rate"),
                }
                for c in r.json().get("campaigns", [])
            ]


class ConvertKitConnection:
    """ConvertKit (Kit) via API Secret."""

    API = "https://api.convertkit.com/v3"

    def _secret(self) -> str | None:
        from apps.core.config import settings

        return getattr(settings, "CONVERTKIT_API_SECRET", None)

    async def get_subscribers(self, from_date: str = "") -> dict:
        secret = self._secret()
        if not secret:
            return {"error": "CONVERTKIT_API_SECRET no configurado"}
        params: dict = {"api_secret": secret}
        if from_date:
            params["from"] = from_date
        async with httpx.AsyncClient(timeout=15.0) as http:
            r = await http.get(f"{self.API}/subscribers", params=params)
            r.raise_for_status()
            return {
                "total_subscribers": r.json().get("total_subscribers"),
                "page": r.json().get("page"),
                "total_pages": r.json().get("total_pages"),
            }

    async def get_forms(self) -> list[dict]:
        secret = self._secret()
        if not secret:
            return [{"error": "CONVERTKIT_API_SECRET no configurado"}]
        async with httpx.AsyncClient(timeout=15.0) as http:
            r = await http.get(f"{self.API}/forms", params={"api_secret": secret})
            r.raise_for_status()
            return [
                {"id": f.get("id"), "name": f.get("name"), "type": f.get("type")}
                for f in r.json().get("forms", [])
            ]

    async def add_subscriber(self, form_id: int, email: str, first_name: str = "") -> dict:
        secret = self._secret()
        if not secret:
            return {"error": "CONVERTKIT_API_SECRET no configurado"}
        async with httpx.AsyncClient(timeout=15.0) as http:
            r = await http.post(
                f"{self.API}/forms/{form_id}/subscribe",
                json={"api_secret": secret, "email": email, "first_name": first_name},
            )
            if r.status_code in (200, 201):
                return {
                    "success": True,
                    "subscriber_id": r.json()
                    .get("subscription", {})
                    .get("subscriber", {})
                    .get("id"),
                }
            return {"success": False, "status": r.status_code}


class BrevoConnection:
    """Brevo (ex Sendinblue) via API key."""

    API = "https://api.brevo.com/v3"

    def _key(self) -> str | None:
        from apps.core.config import settings

        return getattr(settings, "BREVO_API_KEY", None)

    def _h(self) -> dict:
        return {"api-key": self._key() or "", "Accept": "application/json"}

    async def get_contacts(self, limit: int = 50) -> list[dict]:
        key = self._key()
        if not key:
            return [{"error": "BREVO_API_KEY no configurado"}]
        async with httpx.AsyncClient(timeout=15.0) as http:
            r = await http.get(f"{self.API}/contacts", headers=self._h(), params={"limit": limit})
            r.raise_for_status()
            return [
                {"id": c.get("id"), "email": c.get("email"), "attributes": c.get("attributes", {})}
                for c in r.json().get("contacts", [])
            ]

    async def create_contact(
        self, email: str, attributes: dict = None, list_ids: list = None
    ) -> dict:
        if list_ids is None:
            list_ids = []
        if attributes is None:
            attributes = {}
        key = self._key()
        if not key:
            return {"error": "BREVO_API_KEY no configurado"}
        payload: dict[str, Any] = {"email": email}
        if attributes:
            payload["attributes"] = attributes
        if list_ids:
            payload["listIds"] = list_ids
        async with httpx.AsyncClient(timeout=15.0) as http:
            r = await http.post(
                f"{self.API}/contacts",
                headers={**self._h(), "Content-Type": "application/json"},
                json=payload,
            )
            if r.status_code in (200, 201):
                return {"success": True, "id": r.json().get("id")}
            return {"success": False, "status": r.status_code}

    async def send_transactional_email(
        self,
        to_email: str,
        to_name: str,
        subject: str,
        html_content: str,
        from_email: str = "",
        from_name: str = "ARIA AI",
    ) -> dict:
        key = self._key()
        if not key:
            return {"error": "BREVO_API_KEY no configurado"}
        if not from_email:
            from apps.core.config import settings

            from_email = getattr(settings, "EMAIL_FROM", "") or "aria@aria-ai.fly.dev"
        payload = {
            "sender": {"email": from_email, "name": from_name},
            "to": [{"email": to_email, "name": to_name}],
            "subject": subject,
            "htmlContent": html_content,
        }
        async with httpx.AsyncClient(timeout=15.0) as http:
            r = await http.post(
                f"{self.API}/smtp/email",
                headers={**self._h(), "Content-Type": "application/json"},
                json=payload,
            )
            return {"success": r.status_code in (200, 201), "messageId": r.json().get("messageId")}

    async def get_campaigns(self, status: str = "sent") -> list[dict]:
        key = self._key()
        if not key:
            return [{"error": "BREVO_API_KEY no configurado"}]
        async with httpx.AsyncClient(timeout=15.0) as http:
            r = await http.get(
                f"{self.API}/emailCampaigns", headers=self._h(), params={"status": status}
            )
            r.raise_for_status()
            return [
                {
                    "id": c.get("id"),
                    "name": c.get("name"),
                    "subject": c.get("subject"),
                    "status": c.get("status"),
                    "statistics": c.get("statistics", {}),
                }
                for c in r.json().get("campaigns", [])
            ]


class PostmarkConnection:
    """Postmark via Server API Token — transactional email."""

    API = "https://api.postmarkapp.com"

    def _token(self) -> str | None:
        from apps.core.config import settings

        return getattr(settings, "POSTMARK_SERVER_TOKEN", None)

    def _h(self) -> dict:
        return {
            "X-Postmark-Server-Token": self._token() or "",
            "Accept": "application/json",
            "Content-Type": "application/json",
        }

    async def send_email(
        self,
        to: str,
        subject: str,
        html_body: str,
        from_email: str = "aria@aria-ai.fly.dev",
        text_body: str = "",
    ) -> dict:
        token = self._token()
        if not token:
            return {"error": "POSTMARK_SERVER_TOKEN no configurado"}
        payload = {
            "From": from_email,
            "To": to,
            "Subject": subject,
            "HtmlBody": html_body,
        }
        if text_body:
            payload["TextBody"] = text_body
        async with httpx.AsyncClient(timeout=15.0) as http:
            r = await http.post(f"{self.API}/email", headers=self._h(), json=payload)
            return {
                "success": r.status_code == 200,
                "message_id": r.json().get("MessageID"),
                "submitted_at": r.json().get("SubmittedAt"),
            }

    async def get_stats(self, tag: str = "", days: int = 30) -> dict:
        token = self._token()
        if not token:
            return {"error": "POSTMARK_SERVER_TOKEN no configurado"}
        params: dict = {"days": days}
        if tag:
            params["tag"] = tag
        async with httpx.AsyncClient(timeout=15.0) as http:
            r = await http.get(f"{self.API}/stats/outbound", headers=self._h(), params=params)
            r.raise_for_status()
            return r.json()

    async def get_bounces(self, limit: int = 20) -> list[dict]:
        token = self._token()
        if not token:
            return [{"error": "POSTMARK_SERVER_TOKEN no configurado"}]
        async with httpx.AsyncClient(timeout=15.0) as http:
            r = await http.get(
                f"{self.API}/bounces", headers=self._h(), params={"count": limit, "offset": 0}
            )
            r.raise_for_status()
            return r.json().get("Bounces", [])
