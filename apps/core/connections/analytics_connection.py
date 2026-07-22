"""
Analytics connection para ARIA AI.
Soporta Google Analytics 4 (OAuth), Mixpanel (API secret), Amplitude (API key), DataDog (API key).
"""

from __future__ import annotations

import logging
from typing import Any
from urllib.parse import urlencode

import httpx

from apps.core.connections.base import BaseConnector
from apps.core.connections.registry import register_connector

logger = logging.getLogger("aria.connections.analytics")

GA4_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GA4_TOKEN_URL = "https://oauth2.googleapis.com/token"
GA4_API = "https://analyticsdata.googleapis.com/v1beta"
GA4_REDIRECT = "https://aria-ai.fly.dev/oauth/callback/google_analytics"
GA4_SCOPES = "https://www.googleapis.com/auth/analytics.readonly"


@register_connector("google_analytics", display_name="Google Analytics 4")
class GoogleAnalyticsConnection(BaseConnector):
    """Google Analytics 4 via OAuth (reutiliza Google OAuth infraestructura)."""

    def _client_id(self) -> str | None:
        from apps.core.config import settings

        return getattr(settings, "GOOGLE_CLIENT_ID", None)

    def _client_secret(self) -> str | None:
        from apps.core.config import settings

        return getattr(settings, "GOOGLE_CLIENT_SECRET", None)

    def get_auth_url(self, chat_id: str) -> str | None:
        cid = self._client_id()
        if not cid:
            return None
        params = {
            "client_id": cid,
            "redirect_uri": GA4_REDIRECT,
            "response_type": "code",
            "scope": GA4_SCOPES,
            "access_type": "offline",
            "state": chat_id,
        }
        return f"{GA4_AUTH_URL}?{urlencode(params)}"

    async def exchange_code(self, code: str, chat_id: str) -> dict | None:
        cid = self._client_id()
        sec = self._client_secret()
        if not cid or not sec:
            raise ValueError("GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET no configurados")
        async with httpx.AsyncClient(timeout=15.0) as http:
            r = await http.post(
                GA4_TOKEN_URL,
                data={
                    "code": code,
                    "client_id": cid,
                    "client_secret": sec,
                    "redirect_uri": GA4_REDIRECT,
                    "grant_type": "authorization_code",
                },
            )
            r.raise_for_status()
            data = r.json()
            return {
                "access_token": data["access_token"],
                "refresh_token": data.get("refresh_token"),
                "service_user": "google_analytics",
            }

    def _h(self, tokens: dict) -> dict:
        return {"Authorization": f"Bearer {tokens['access_token']}"}

    async def run_report(
        self,
        tokens: dict,
        property_id: str,
        metrics: list[str],
        dimensions: list[str],
        date_range: tuple[str, str] = ("30daysAgo", "today"),
    ) -> dict:
        body = {
            "dateRanges": [{"startDate": date_range[0], "endDate": date_range[1]}],
            "metrics": [{"name": m} for m in metrics],
            "dimensions": [{"name": d} for d in dimensions],
        }
        async with httpx.AsyncClient(timeout=20.0) as http:
            r = await http.post(
                f"{GA4_API}/properties/{property_id}:runReport",
                headers={**self._h(tokens), "Content-Type": "application/json"},
                json=body,
            )
            r.raise_for_status()
            return r.json()

    async def get_realtime(self, tokens: dict, property_id: str) -> dict:
        body = {
            "metrics": [{"name": "activeUsers"}],
            "dimensions": [{"name": "country"}],
        }
        async with httpx.AsyncClient(timeout=15.0) as http:
            r = await http.post(
                f"{GA4_API}/properties/{property_id}:runRealtimeReport",
                headers={**self._h(tokens), "Content-Type": "application/json"},
                json=body,
            )
            r.raise_for_status()
            return r.json()


class MixpanelConnection:
    """Mixpanel via API Secret (no OAuth)."""

    API = "https://data.mixpanel.com/api/2.0"
    EXPORT_API = "https://mixpanel.com/api/2.0"

    def _secret(self) -> str | None:
        from apps.core.config import settings

        return getattr(settings, "MIXPANEL_API_SECRET", None)

    def _project_token(self) -> str | None:
        from apps.core.config import settings

        return getattr(settings, "MIXPANEL_PROJECT_TOKEN", None)

    async def get_events(self, event_names: list[str], from_date: str, to_date: str) -> list[dict]:
        secret = self._secret()
        if not secret:
            return [{"error": "MIXPANEL_API_SECRET no configurado"}]
        async with httpx.AsyncClient(timeout=20.0) as http:
            r = await http.get(
                f"{self.EXPORT_API}/events",
                auth=(secret, ""),
                params={
                    "event": event_names,
                    "from_date": from_date,
                    "to_date": to_date,
                    "unit": "day",
                },
            )
            r.raise_for_status()
            return r.json().get("data", {}).get("series", [])

    async def get_funnels(self, funnel_id: int, from_date: str, to_date: str) -> dict:
        secret = self._secret()
        if not secret:
            return {"error": "MIXPANEL_API_SECRET no configurado"}
        async with httpx.AsyncClient(timeout=15.0) as http:
            r = await http.get(
                f"{self.EXPORT_API}/funnels",
                auth=(secret, ""),
                params={"funnel_id": funnel_id, "from_date": from_date, "to_date": to_date},
            )
            r.raise_for_status()
            return r.json()

    async def get_retention(self, from_date: str, to_date: str) -> dict:
        secret = self._secret()
        if not secret:
            return {"error": "MIXPANEL_API_SECRET no configurado"}
        async with httpx.AsyncClient(timeout=15.0) as http:
            r = await http.get(
                f"{self.EXPORT_API}/retention",
                auth=(secret, ""),
                params={"from_date": from_date, "to_date": to_date},
            )
            r.raise_for_status()
            return r.json()


class AmplitudeConnection:
    """Amplitude via API key + Secret key."""

    API = "https://amplitude.com/api/2"

    def _creds(self) -> tuple[str, str]:
        from apps.core.config import settings

        key = getattr(settings, "AMPLITUDE_API_KEY", "") or ""
        secret = getattr(settings, "AMPLITUDE_SECRET_KEY", "") or ""
        return key, secret

    async def get_events(self, start: str, end: str, event: str = "") -> dict:
        key, secret = self._creds()
        if not key or not secret:
            return {"error": "AMPLITUDE_API_KEY / AMPLITUDE_SECRET_KEY no configurados"}
        params: dict[str, Any] = {"start": start, "end": end}
        if event:
            params["e"] = f'{{"event_type":"{event}"}}'
        async with httpx.AsyncClient(timeout=20.0) as http:
            r = await http.get(f"{self.API}/events/segmentation", auth=(key, secret), params=params)
            r.raise_for_status()
            return r.json()

    async def get_user_activity(self, user_id: str) -> dict:
        key, secret = self._creds()
        if not key or not secret:
            return {"error": "AMPLITUDE_API_KEY / AMPLITUDE_SECRET_KEY no configurados"}
        async with httpx.AsyncClient(timeout=15.0) as http:
            r = await http.get(
                f"{self.API}/useractivity",
                auth=(key, secret),
                params={"user": user_id},
            )
            r.raise_for_status()
            return r.json()


class DataDogConnection:
    """DataDog via API key + Application key."""

    API = "https://api.datadoghq.com/api/v1"
    API_V2 = "https://api.datadoghq.com/api/v2"

    def _creds(self) -> tuple[str, str]:
        from apps.core.config import settings

        api_key = getattr(settings, "DATADOG_API_KEY", "") or ""
        app_key = getattr(settings, "DATADOG_APP_KEY", "") or ""
        return api_key, app_key

    def _h(self) -> dict:
        api_key, app_key = self._creds()
        return {"DD-API-KEY": api_key, "DD-APPLICATION-KEY": app_key}

    async def get_metrics(self, query: str, from_ts: int, to_ts: int) -> dict:
        api_key, app_key = self._creds()
        if not api_key:
            return {"error": "DATADOG_API_KEY no configurado"}
        async with httpx.AsyncClient(timeout=15.0) as http:
            r = await http.get(
                f"{self.API}/query",
                headers=self._h(),
                params={"query": query, "from": from_ts, "to": to_ts},
            )
            r.raise_for_status()
            return r.json()

    async def get_monitors(self) -> list[dict]:
        api_key, _ = self._creds()
        if not api_key:
            return [{"error": "DATADOG_API_KEY no configurado"}]
        async with httpx.AsyncClient(timeout=15.0) as http:
            r = await http.get(f"{self.API}/monitor", headers=self._h())
            r.raise_for_status()
            return [
                {
                    "id": m.get("id"),
                    "name": m.get("name"),
                    "status": m.get("overall_state"),
                    "type": m.get("type"),
                }
                for m in r.json()
            ]

    async def get_logs(self, query: str, from_ts: str, to_ts: str, limit: int = 50) -> list[dict]:
        api_key, _ = self._creds()
        if not api_key:
            return [{"error": "DATADOG_API_KEY no configurado"}]
        body = {
            "filter": {"query": query, "from": from_ts, "to": to_ts},
            "page": {"limit": limit},
        }
        async with httpx.AsyncClient(timeout=15.0) as http:
            r = await http.post(
                f"{self.API_V2}/logs/events/search",
                headers={**self._h(), "Content-Type": "application/json"},
                json=body,
            )
            r.raise_for_status()
            return r.json().get("data", [])
