"""
Design connection for ARIA AI.
Supports Figma (OAuth + API) and Canva (OAuth).
"""

from __future__ import annotations

import logging
from urllib.parse import urlencode

import httpx

from apps.core.connections.base import BaseConnector
from apps.core.connections.registry import register_connector

logger = logging.getLogger("aria.connections.design")

FIGMA_AUTH_URL = "https://www.figma.com/oauth"
FIGMA_TOKEN_URL = "https://www.figma.com/api/oauth/token"
FIGMA_API = "https://api.figma.com/v1"
FIGMA_REDIRECT = "https://aria-ai.fly.dev/oauth/callback/figma"
FIGMA_SCOPES = "file_read"

CANVA_AUTH_URL = "https://www.canva.com/api/oauth/authorize"
CANVA_TOKEN_URL = "https://api.canva.com/rest/v1/oauth/token"
CANVA_API = "https://api.canva.com/rest/v1"
CANVA_REDIRECT = "https://aria-ai.fly.dev/oauth/callback/canva"
CANVA_SCOPES = "design:content:read design:meta:read asset:read"


@register_connector("figma", display_name="Figma (UI/UX design, prototypes)")
class FigmaConnection(BaseConnector):

    def _client_id(self) -> str | None:
        from apps.core.config import settings

        return getattr(settings, "FIGMA_CLIENT_ID", None)

    def _client_secret(self) -> str | None:
        from apps.core.config import settings

        return getattr(settings, "FIGMA_CLIENT_SECRET", None)

    def _api_token(self) -> str | None:
        from apps.core.config import settings

        return getattr(settings, "FIGMA_API_TOKEN", None)

    def get_auth_url(self, chat_id: str) -> str | None:
        cid = self._client_id()
        if not cid:
            return None
        params = {
            "client_id": cid,
            "redirect_uri": FIGMA_REDIRECT,
            "scope": FIGMA_SCOPES,
            "state": chat_id,
            "response_type": "code",
        }
        return f"{FIGMA_AUTH_URL}?{urlencode(params)}"

    async def exchange_code(self, code: str, chat_id: str) -> dict | None:
        cid = self._client_id()
        sec = self._client_secret()
        if not cid or not sec:
            raise ValueError("FIGMA_CLIENT_ID / FIGMA_CLIENT_SECRET not configured")
        async with httpx.AsyncClient(timeout=15.0) as http:
            r = await http.post(
                FIGMA_TOKEN_URL,
                data={
                    "client_id": cid,
                    "client_secret": sec,
                    "redirect_uri": FIGMA_REDIRECT,
                    "code": code,
                    "grant_type": "authorization_code",
                },
            )
            r.raise_for_status()
            data = r.json()
            return {
                "access_token": data["access_token"],
                "refresh_token": data.get("refresh_token"),
                "service_user": data.get("user_id", "figma_user"),
            }

    def _h(self, tokens: dict | None = None) -> dict:
        if tokens:
            return {"X-Figma-Token": tokens.get("access_token", "")}
        key = self._api_token()
        return {"X-Figma-Token": key} if key else {}

    async def list_files(self, tokens: dict | None = None, project_id: str = "") -> list[dict]:
        headers = self._h(tokens)
        if not project_id:
            return [{"error": "project_id required to list files"}]
        async with httpx.AsyncClient(timeout=15.0) as http:
            r = await http.get(f"{FIGMA_API}/projects/{project_id}/files", headers=headers)
            r.raise_for_status()
            return [
                {
                    "key": f.get("key"),
                    "name": f.get("name"),
                    "thumbnail_url": f.get("thumbnail_url"),
                }
                for f in r.json().get("files", [])
            ]

    async def get_file(self, tokens: dict | None, file_key: str) -> dict:
        headers = self._h(tokens)
        async with httpx.AsyncClient(timeout=20.0) as http:
            r = await http.get(f"{FIGMA_API}/files/{file_key}", headers=headers)
            r.raise_for_status()
            data = r.json()
            return {
                "name": data.get("name"),
                "lastModified": data.get("lastModified"),
                "version": data.get("version"),
                "thumbnailUrl": data.get("thumbnailUrl"),
                "pages": [p.get("name") for p in data.get("document", {}).get("children", [])],
            }

    async def get_comments(self, tokens: dict | None, file_key: str) -> list[dict]:
        headers = self._h(tokens)
        async with httpx.AsyncClient(timeout=15.0) as http:
            r = await http.get(f"{FIGMA_API}/files/{file_key}/comments", headers=headers)
            r.raise_for_status()
            return [
                {
                    "id": c.get("id"),
                    "message": c.get("message"),
                    "user": c.get("user", {}).get("handle"),
                    "created_at": c.get("created_at"),
                }
                for c in r.json().get("comments", [])
            ]

    async def list_projects(self, tokens: dict | None, team_id: str) -> list[dict]:
        headers = self._h(tokens)
        async with httpx.AsyncClient(timeout=15.0) as http:
            r = await http.get(f"{FIGMA_API}/teams/{team_id}/projects", headers=headers)
            r.raise_for_status()
            return [
                {"id": p.get("id"), "name": p.get("name")} for p in r.json().get("projects", [])
            ]


@register_connector("canva", display_name="Canva (graphic design)")
class CanvaConnection(BaseConnector):

    def _client_id(self) -> str | None:
        from apps.core.config import settings

        return getattr(settings, "CANVA_CLIENT_ID", None)

    def _client_secret(self) -> str | None:
        from apps.core.config import settings

        return getattr(settings, "CANVA_CLIENT_SECRET", None)

    def get_auth_url(self, chat_id: str) -> str | None:
        cid = self._client_id()
        if not cid:
            return None
        params = {
            "client_id": cid,
            "response_type": "code",
            "redirect_uri": CANVA_REDIRECT,
            "scope": CANVA_SCOPES,
            "state": chat_id,
        }
        return f"{CANVA_AUTH_URL}?{urlencode(params)}"

    async def exchange_code(self, code: str, chat_id: str) -> dict | None:
        cid = self._client_id()
        sec = self._client_secret()
        if not cid or not sec:
            raise ValueError("CANVA_CLIENT_ID / CANVA_CLIENT_SECRET not configured")
        import base64

        credentials = base64.b64encode(f"{cid}:{sec}".encode()).decode()
        async with httpx.AsyncClient(timeout=15.0) as http:
            r = await http.post(
                CANVA_TOKEN_URL,
                data={
                    "grant_type": "authorization_code",
                    "code": code,
                    "redirect_uri": CANVA_REDIRECT,
                    "code_verifier": "",
                },
                headers={"Authorization": f"Basic {credentials}"},
            )
            r.raise_for_status()
            data = r.json()
            return {
                "access_token": data["access_token"],
                "refresh_token": data.get("refresh_token"),
                "service_user": "canva_user",
            }

    def _h(self, tokens: dict) -> dict:
        return {"Authorization": f"Bearer {tokens['access_token']}"}

    async def list_designs(self, tokens: dict, query: str = "", limit: int = 20) -> list[dict]:
        params: dict = {"limit": limit}
        if query:
            params["query"] = query
        async with httpx.AsyncClient(timeout=15.0) as http:
            r = await http.get(f"{CANVA_API}/designs", headers=self._h(tokens), params=params)
            r.raise_for_status()
            return [
                {
                    "id": d.get("id"),
                    "title": d.get("title"),
                    "url": d.get("urls", {}).get("view_url", ""),
                    "thumbnail": d.get("thumbnail", {}).get("url", ""),
                    "created_at": d.get("created_at"),
                }
                for d in r.json().get("items", [])
            ]

    async def get_design(self, tokens: dict, design_id: str) -> dict:
        async with httpx.AsyncClient(timeout=15.0) as http:
            r = await http.get(f"{CANVA_API}/designs/{design_id}", headers=self._h(tokens))
            r.raise_for_status()
            d = r.json().get("design", {})
            return {
                "id": d.get("id"),
                "title": d.get("title"),
                "view_url": d.get("urls", {}).get("view_url", ""),
                "edit_url": d.get("urls", {}).get("edit_url", ""),
                "thumbnail": d.get("thumbnail", {}).get("url", ""),
            }
