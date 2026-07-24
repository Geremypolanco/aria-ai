"""
marketing_tools.py — Meta Ads management and advanced analytics for ARIA AI.
"""

from __future__ import annotations

import logging
import os
from typing import Any

import httpx

logger = logging.getLogger("aria.marketing_tools")


class MetaMarketingTools:
    """Meta Ads management (Facebook/Instagram Ads)."""

    def __init__(self) -> None:
        self._http = httpx.AsyncClient(timeout=30.0)
        self._token = os.getenv("FACEBOOK_MARKETING_TOKEN")
        self._ad_account = os.getenv("FACEBOOK_AD_ACCOUNT_ID")

    def _ok(self) -> bool:
        return bool(self._token and self._ad_account)

    async def get_campaign_stats(self) -> dict[str, Any]:
        if not self._ok():
            return {
                "success": False,
                "error": "FACEBOOK_MARKETING_TOKEN or AD_ACCOUNT_ID not configured",
            }
        try:
            url = f"https://graph.facebook.com/v25.0/{self._ad_account}/campaigns"
            params = {
                "access_token": self._token,
                "fields": "name,status,objective,insights{spend,impressions,clicks,cpc,ctr}",
            }
            res = await self._http.get(url, params=params)
            if res.status_code == 200:
                campaigns = res.json().get("data", [])
                return {"success": True, "campaigns": campaigns}
            return {"success": False, "error": f"HTTP {res.status_code}: {res.text}"}
        except Exception as exc:
            return {"success": False, "error": str(exc)}

    async def create_campaign(
        self, name: str, objective: str, status: str = "PAUSED"
    ) -> dict[str, Any]:
        if not self._ok():
            return {"success": False, "error": "Not configured"}
        try:
            url = f"https://graph.facebook.com/v25.0/{self._ad_account}/campaigns"
            data = {
                "access_token": self._token,
                "name": name,
                "objective": objective,
                "status": status,
                "special_ad_categories": "NONE",
            }
            res = await self._http.post(url, data=data)
            if res.status_code == 200:
                return {"success": True, "campaign_id": res.json().get("id")}
            return {"success": False, "error": res.text}
        except Exception as exc:
            return {"success": False, "error": str(exc)}
