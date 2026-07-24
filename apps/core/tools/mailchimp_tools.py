"""
mailchimp_tools.py — Automated email marketing via Mailchimp.
Creates campaigns, manages lists, and sends emails autonomously.
"""

from __future__ import annotations

import base64
import logging
from typing import Any

import httpx

from apps.core.config import settings

logger = logging.getLogger("aria.mailchimp_tools")


class MailchimpTools:
    """Automated email marketing via Mailchimp API v3."""

    def __init__(self) -> None:
        self._http = httpx.AsyncClient(timeout=20.0)
        self._api_key = settings.MAILCHIMP_API_KEY
        self._dc = settings.MAILCHIMP_DC or "us1"
        self._base = f"https://{self._dc}.api.mailchimp.com/3.0"
        if self._api_key:
            token = base64.b64encode(f"apikey:{self._api_key}".encode()).decode()
            self._headers = {"Authorization": f"Basic {token}", "Content-Type": "application/json"}
        else:
            self._headers = {}

    def _configured(self) -> bool:
        return bool(self._api_key and self._dc)

    async def get_lists(self) -> dict[str, Any]:
        """Gets all lists/audiences from Mailchimp."""
        if not self._configured():
            return {"success": False, "error": "MAILCHIMP not configured"}
        try:
            res = await self._http.get(
                f"{self._base}/lists", headers=self._headers, params={"count": 20}
            )
            if res.status_code == 200:
                data = res.json()
                lists = [
                    {"id": l["id"], "name": l["name"], "members": l["stats"]["member_count"]}
                    for l in data.get("lists", [])
                ]
                return {"success": True, "lists": lists, "total": len(lists)}
            return {"success": False, "error": f"HTTP {res.status_code}"}
        except Exception as exc:
            logger.error("[Mailchimp] get_lists error: %s", exc)
            return {"success": False, "error": str(exc)}

    async def create_campaign(
        self,
        list_id: str,
        subject: str,
        from_name: str,
        reply_to: str,
        body_html: str,
        preview_text: str = "",
    ) -> dict[str, Any]:
        """Creates and sends an email campaign."""
        if not self._configured():
            return {"success": False, "error": "MAILCHIMP not configured"}
        try:
            # 1. Create campaign
            campaign_payload = {
                "type": "regular",
                "recipients": {"list_id": list_id},
                "settings": {
                    "subject_line": subject,
                    "preview_text": preview_text,
                    "from_name": from_name,
                    "reply_to": reply_to,
                },
            }
            res = await self._http.post(
                f"{self._base}/campaigns", headers=self._headers, json=campaign_payload
            )
            if res.status_code not in (200, 201):
                return {
                    "success": False,
                    "error": f"Create campaign HTTP {res.status_code}: {res.text[:200]}",
                }
            campaign_id = res.json()["id"]

            # 2. Add HTML content
            content_res = await self._http.put(
                f"{self._base}/campaigns/{campaign_id}/content",
                headers=self._headers,
                json={"html": body_html},
            )
            if content_res.status_code not in (200, 201):
                return {"success": False, "error": f"Content HTTP {content_res.status_code}"}

            # 3. Send campaign
            send_res = await self._http.post(
                f"{self._base}/campaigns/{campaign_id}/actions/send",
                headers=self._headers,
            )
            if send_res.status_code == 204:
                logger.info("[Mailchimp] Campaign %s sent", campaign_id)
                return {
                    "success": True,
                    "campaign_id": campaign_id,
                    "subject": subject,
                    "list_id": list_id,
                }

            return {"success": False, "error": f"Send HTTP {send_res.status_code}"}
        except Exception as exc:
            logger.error("[Mailchimp] create_campaign error: %s", exc)
            return {"success": False, "error": str(exc)}

    async def add_subscriber(
        self, list_id: str, email: str, first_name: str = "", last_name: str = ""
    ) -> dict[str, Any]:
        """Adds a subscriber to a list."""
        if not self._configured():
            return {"success": False, "error": "MAILCHIMP not configured"}
        try:
            payload = {
                "email_address": email,
                "status": "subscribed",
                "merge_fields": {"FNAME": first_name, "LNAME": last_name},
            }
            res = await self._http.post(
                f"{self._base}/lists/{list_id}/members", headers=self._headers, json=payload
            )
            if res.status_code in (200, 201):
                return {"success": True, "email": email, "list_id": list_id}
            return {"success": False, "error": f"HTTP {res.status_code}: {res.text[:200]}"}
        except Exception as exc:
            return {"success": False, "error": str(exc)}

    async def get_campaign_stats(self, campaign_id: str) -> dict[str, Any]:
        """Gets stats for a sent campaign."""
        if not self._configured():
            return {"success": False, "error": "MAILCHIMP not configured"}
        try:
            res = await self._http.get(f"{self._base}/reports/{campaign_id}", headers=self._headers)
            if res.status_code == 200:
                d = res.json()
                return {
                    "success": True,
                    "opens": d.get("opens", {}).get("unique_opens", 0),
                    "clicks": d.get("clicks", {}).get("unique_clicks", 0),
                    "sent": d.get("emails_sent", 0),
                    "open_rate": d.get("opens", {}).get("open_rate", 0),
                    "click_rate": d.get("clicks", {}).get("click_rate", 0),
                }
            return {"success": False, "error": f"HTTP {res.status_code}"}
        except Exception as exc:
            return {"success": False, "error": str(exc)}
