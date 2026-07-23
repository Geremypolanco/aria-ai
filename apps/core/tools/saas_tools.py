"""
saas_tools.py — SaaS platform management (Notion, Vercel) for ARIA AI.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from apps.core.config import settings

logger = logging.getLogger("aria.saas_tools")


class NotionTools:
    """Notion workspace management."""

    def __init__(self) -> None:
        self._http = httpx.AsyncClient(timeout=30.0)
        self._token = getattr(settings, "NOTION_TOKEN", None)
        self._headers = (
            {
                "Authorization": f"Bearer {self._token}",
                "Notion-Version": "2022-06-28",
                "Content-Type": "application/json",
            }
            if self._token
            else {}
        )

    def _ok(self) -> bool:
        return bool(self._token)

    async def list_pages(self) -> dict[str, Any]:
        if not self._ok():
            return {"success": False, "error": "NOTION_TOKEN not configured"}
        try:
            res = await self._http.post(
                "https://api.notion.com/v1/search",
                headers=self._headers,
                json={"filter": {"property": "object", "value": "page"}},
            )
            if res.status_code == 200:
                pages = res.json().get("results", [])
                return {
                    "success": True,
                    "pages": [
                        {
                            "id": p["id"],
                            "url": p.get("url"),
                            "title": p.get("properties", {})
                            .get("title", {})
                            .get("title", [{}])[0]
                            .get("plain_text", "Untitled"),
                        }
                        for p in pages
                    ],
                }
            return {"success": False, "error": f"HTTP {res.status_code}"}
        except Exception as exc:
            return {"success": False, "error": str(exc)}

    async def create_page(self, parent_id: str, title: str, content: str = "") -> dict[str, Any]:
        if not self._ok():
            return {"success": False, "error": "NOTION_TOKEN not configured"}
        try:
            body = {
                "parent": {"page_id": parent_id},
                "properties": {"title": [{"text": {"content": title}}]},
                "children": (
                    [
                        {
                            "object": "block",
                            "type": "paragraph",
                            "paragraph": {"rich_text": [{"text": {"content": content}}]},
                        }
                    ]
                    if content
                    else []
                ),
            }
            res = await self._http.post(
                "https://api.notion.com/v1/pages", headers=self._headers, json=body
            )
            if res.status_code == 200:
                return {"success": True, "page_id": res.json()["id"]}
            return {"success": False, "error": res.text}
        except Exception as exc:
            return {"success": False, "error": str(exc)}


class VercelTools:
    """Vercel deployment and project management."""

    def __init__(self) -> None:
        self._http = httpx.AsyncClient(timeout=30.0)
        self._token = settings.VERCEL_TOKEN
        self._headers = {"Authorization": f"Bearer {self._token}"} if self._token else {}

    def _ok(self) -> bool:
        return bool(self._token)

    async def list_projects(self) -> dict[str, Any]:
        if not self._ok():
            return {"success": False, "error": "VERCEL_TOKEN not configured"}
        try:
            res = await self._http.get("https://api.vercel.com/v9/projects", headers=self._headers)
            if res.status_code == 200:
                projects = res.json().get("projects", [])
                return {
                    "success": True,
                    "projects": [
                        {"id": p["id"], "name": p["name"], "url": p.get("link")} for p in projects
                    ],
                }
            return {"success": False, "error": f"HTTP {res.status_code}"}
        except Exception as exc:
            return {"success": False, "error": str(exc)}

    async def get_deployment_status(self, project_id: str) -> dict[str, Any]:
        if not self._ok():
            return {"success": False, "error": "VERCEL_TOKEN not configured"}
        try:
            res = await self._http.get(
                "https://api.vercel.com/v6/deployments",
                headers=self._headers,
                params={"projectId": project_id, "limit": 1},
            )
            if res.status_code == 200:
                deps = res.json().get("deployments", [])
                if not deps:
                    return {"success": False, "error": "No deployments found"}
                return {"success": True, "status": deps[0]["state"], "url": deps[0]["url"]}
            return {"success": False, "error": f"HTTP {res.status_code}"}
        except Exception as exc:
            return {"success": False, "error": str(exc)}
