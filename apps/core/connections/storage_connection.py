"""
Dropbox + Box file storage connections for ARIA AI.

Requires in Fly.io secrets:
  DROPBOX_CLIENT_ID     → from www.dropbox.com/developers/apps
  DROPBOX_CLIENT_SECRET → same place
  BOX_CLIENT_ID         → from developer.box.com
  BOX_CLIENT_SECRET     → same place
"""

from __future__ import annotations

import logging
from typing import Any
from urllib.parse import urlencode

import httpx

logger = logging.getLogger("aria.connections.storage")


# ── DROPBOX ───────────────────────────────────────────────────────────────────


class DropboxConnection:

    REDIRECT_URI = "https://aria-ai.fly.dev/oauth/callback/dropbox"
    AUTH_URL = "https://www.dropbox.com/oauth2/authorize"
    TOKEN_URL = "https://api.dropbox.com/oauth2/token"

    def _client_id(self) -> str | None:
        from apps.core.config import settings

        return getattr(settings, "DROPBOX_CLIENT_ID", None)

    def _client_secret(self) -> str | None:
        from apps.core.config import settings

        return getattr(settings, "DROPBOX_CLIENT_SECRET", None)

    def get_auth_url(self, chat_id: str) -> str | None:
        cid = self._client_id()
        if not cid:
            return None
        params = {
            "client_id": cid,
            "redirect_uri": self.REDIRECT_URI,
            "response_type": "code",
            "token_access_type": "offline",
            "state": chat_id,
        }
        return f"{self.AUTH_URL}?{urlencode(params)}"

    async def exchange_code(self, code: str, chat_id: str) -> dict | None:
        cid = self._client_id()
        sec = self._client_secret()
        if not cid or not sec:
            raise ValueError("DROPBOX_CLIENT_ID / DROPBOX_CLIENT_SECRET not configured")
        async with httpx.AsyncClient(timeout=15.0) as http:
            r = await http.post(
                self.TOKEN_URL,
                data={
                    "code": code,
                    "client_id": cid,
                    "client_secret": sec,
                    "redirect_uri": self.REDIRECT_URI,
                    "grant_type": "authorization_code",
                },
            )
            r.raise_for_status()
            data = r.json()
            # Get account email
            email = await self._get_account_email(data["access_token"])
            return {
                "access_token": data["access_token"],
                "refresh_token": data.get("refresh_token"),
                "expires_in": data.get("expires_in", 14400),
                "scope": data.get("scope", ""),
                "service_user": email,
            }

    async def refresh_token(self, tokens: dict) -> dict:
        cid = self._client_id()
        sec = self._client_secret()
        async with httpx.AsyncClient(timeout=15.0) as http:
            r = await http.post(
                self.TOKEN_URL,
                data={
                    "refresh_token": tokens["refresh_token"],
                    "client_id": cid,
                    "client_secret": sec,
                    "grant_type": "refresh_token",
                },
            )
            r.raise_for_status()
            data = r.json()
            tokens["access_token"] = data["access_token"]
            return tokens

    async def _get_account_email(self, access_token: str) -> str:
        async with httpx.AsyncClient(timeout=10.0) as http:
            r = await http.post(
                "https://api.dropboxapi.com/2/users/get_current_account",
                headers={"Authorization": f"Bearer {access_token}"},
                content=b"null",
            )
            if r.status_code == 200:
                return r.json().get("email", "unknown")
            return "unknown"

    def _headers(self, tokens: dict) -> dict:
        return {"Authorization": f"Bearer {tokens['access_token']}"}

    async def list_files(self, tokens: dict, path: str = "", limit: int = 20) -> list[dict]:
        """List files and folders at the given Dropbox path."""
        async with httpx.AsyncClient(timeout=15.0) as http:
            r = await http.post(
                "https://api.dropboxapi.com/2/files/list_folder",
                headers={**self._headers(tokens), "Content-Type": "application/json"},
                json={"path": path, "limit": limit},
            )
            if r.status_code != 200:
                raise RuntimeError(f"Dropbox list_folder error {r.status_code}: {r.text[:200]}")
            entries = r.json().get("entries", [])
            return [
                {
                    "name": e.get("name"),
                    "path": e.get("path_display"),
                    "size": e.get("size"),
                    "modified": e.get("client_modified") or e.get("server_modified"),
                    "type": "folder" if e.get(".tag") == "folder" else "file",
                }
                for e in entries
            ]

    async def upload_file(self, tokens: dict, content_bytes: bytes, path: str) -> dict:
        """Upload bytes to the given Dropbox path."""
        import json as _json

        async with httpx.AsyncClient(timeout=30.0) as http:
            r = await http.post(
                "https://content.dropboxapi.com/2/files/upload",
                headers={
                    **self._headers(tokens),
                    "Content-Type": "application/octet-stream",
                    "Dropbox-API-Arg": _json.dumps({"path": path, "mode": "overwrite"}),
                },
                content=content_bytes,
            )
            r.raise_for_status()
            data = r.json()
            return {
                "success": True,
                "path": data.get("path_display"),
                "url": data.get("path_display"),
            }

    async def download_file(self, tokens: dict, path: str) -> bytes:
        """Download file content from Dropbox."""
        import json as _json

        async with httpx.AsyncClient(timeout=30.0) as http:
            r = await http.post(
                "https://content.dropboxapi.com/2/files/download",
                headers={
                    **self._headers(tokens),
                    "Dropbox-API-Arg": _json.dumps({"path": path}),
                },
            )
            r.raise_for_status()
            return r.content

    async def search_files(self, tokens: dict, query: str, path: str = "") -> list[dict]:
        """Search for files matching query in Dropbox."""
        async with httpx.AsyncClient(timeout=15.0) as http:
            body: dict[str, Any] = (
                {"query": query, "options": {"path": path}} if path else {"query": query}
            )
            r = await http.post(
                "https://api.dropboxapi.com/2/files/search_v2",
                headers={**self._headers(tokens), "Content-Type": "application/json"},
                json=body,
            )
            r.raise_for_status()
            matches = r.json().get("matches", [])
            results = []
            for m in matches:
                meta = m.get("metadata", {}).get("metadata", {})
                results.append(
                    {
                        "name": meta.get("name"),
                        "path": meta.get("path_display"),
                        "size": meta.get("size"),
                        "modified": meta.get("client_modified") or meta.get("server_modified"),
                        "type": "folder" if meta.get(".tag") == "folder" else "file",
                    }
                )
            return results

    async def create_shared_link(self, tokens: dict, path: str) -> str:
        """Create a shared link for a Dropbox file, returning the URL."""
        async with httpx.AsyncClient(timeout=15.0) as http:
            r = await http.post(
                "https://api.dropboxapi.com/2/sharing/create_shared_link_with_settings",
                headers={**self._headers(tokens), "Content-Type": "application/json"},
                json={"path": path, "settings": {"requested_visibility": "public"}},
            )
            if r.status_code == 409:
                # Link already exists — fetch it
                r2 = await http.post(
                    "https://api.dropboxapi.com/2/sharing/list_shared_links",
                    headers={**self._headers(tokens), "Content-Type": "application/json"},
                    json={"path": path},
                )
                r2.raise_for_status()
                links = r2.json().get("links", [])
                return links[0].get("url", "") if links else ""
            r.raise_for_status()
            return r.json().get("url", "")


# ── BOX ───────────────────────────────────────────────────────────────────────


class BoxConnection:

    REDIRECT_URI = "https://aria-ai.fly.dev/oauth/callback/box"
    AUTH_URL = "https://account.box.com/api/oauth2/authorize"
    TOKEN_URL = "https://api.box.com/oauth2/token"

    def _client_id(self) -> str | None:
        from apps.core.config import settings

        return getattr(settings, "BOX_CLIENT_ID", None)

    def _client_secret(self) -> str | None:
        from apps.core.config import settings

        return getattr(settings, "BOX_CLIENT_SECRET", None)

    def get_auth_url(self, chat_id: str) -> str | None:
        cid = self._client_id()
        if not cid:
            return None
        params = {
            "client_id": cid,
            "redirect_uri": self.REDIRECT_URI,
            "response_type": "code",
            "state": chat_id,
        }
        return f"{self.AUTH_URL}?{urlencode(params)}"

    async def exchange_code(self, code: str, chat_id: str) -> dict | None:
        cid = self._client_id()
        sec = self._client_secret()
        if not cid or not sec:
            raise ValueError("BOX_CLIENT_ID / BOX_CLIENT_SECRET not configured")
        async with httpx.AsyncClient(timeout=15.0) as http:
            r = await http.post(
                self.TOKEN_URL,
                data={
                    "code": code,
                    "client_id": cid,
                    "client_secret": sec,
                    "redirect_uri": self.REDIRECT_URI,
                    "grant_type": "authorization_code",
                },
            )
            r.raise_for_status()
            data = r.json()
            # Get user email from token introspection
            email = await self._get_user_email(data["access_token"])
            return {
                "access_token": data["access_token"],
                "refresh_token": data.get("refresh_token"),
                "expires_in": data.get("expires_in", 3600),
                "scope": data.get("scope", ""),
                "service_user": email,
            }

    async def _get_user_email(self, access_token: str) -> str:
        async with httpx.AsyncClient(timeout=10.0) as http:
            r = await http.get(
                "https://api.box.com/2.0/users/me",
                headers={"Authorization": f"Bearer {access_token}"},
            )
            if r.status_code == 200:
                return r.json().get("login", "unknown")
            return "unknown"

    def _headers(self, tokens: dict) -> dict:
        return {"Authorization": f"Bearer {tokens['access_token']}"}

    async def list_folder(self, tokens: dict, folder_id: str = "0", limit: int = 20) -> list[dict]:
        """List items in a Box folder."""
        async with httpx.AsyncClient(timeout=15.0) as http:
            r = await http.get(
                f"https://api.box.com/2.0/folders/{folder_id}/items",
                headers=self._headers(tokens),
                params={"limit": limit, "fields": "id,name,type,size,modified_at"},
            )
            if r.status_code != 200:
                raise RuntimeError(f"Box folder error {r.status_code}: {r.text[:200]}")
            entries = r.json().get("entries", [])
            return [
                {
                    "id": e.get("id"),
                    "name": e.get("name"),
                    "type": e.get("type"),
                    "size": e.get("size"),
                    "modified": e.get("modified_at"),
                }
                for e in entries
            ]

    async def search_files(self, tokens: dict, query: str, limit: int = 10) -> list[dict]:
        """Search for files in Box."""
        async with httpx.AsyncClient(timeout=15.0) as http:
            r = await http.get(
                "https://api.box.com/2.0/search",
                headers=self._headers(tokens),
                params={"query": query, "limit": limit, "fields": "id,name,type,size,modified_at"},
            )
            r.raise_for_status()
            entries = r.json().get("entries", [])
            return [
                {
                    "id": e.get("id"),
                    "name": e.get("name"),
                    "type": e.get("type"),
                    "size": e.get("size"),
                    "modified": e.get("modified_at"),
                }
                for e in entries
            ]

    async def get_file_info(self, tokens: dict, file_id: str) -> dict:
        """Get metadata for a specific Box file."""
        async with httpx.AsyncClient(timeout=15.0) as http:
            r = await http.get(
                f"https://api.box.com/2.0/files/{file_id}",
                headers=self._headers(tokens),
            )
            r.raise_for_status()
            d = r.json()
            return {
                "id": d.get("id"),
                "name": d.get("name"),
                "size": d.get("size"),
                "modified": d.get("modified_at"),
                "created": d.get("created_at"),
                "owner": d.get("owned_by", {}).get("login"),
            }

    async def create_shared_link(self, tokens: dict, file_id: str) -> str:
        """Create a shared link for a Box file, returning the URL."""
        async with httpx.AsyncClient(timeout=15.0) as http:
            r = await http.put(
                f"https://api.box.com/2.0/files/{file_id}",
                headers={**self._headers(tokens), "Content-Type": "application/json"},
                json={"shared_link": {"access": "open"}},
                params={"fields": "shared_link"},
            )
            r.raise_for_status()
            return r.json().get("shared_link", {}).get("url", "")
