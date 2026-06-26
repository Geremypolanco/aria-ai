"""
CMS connection para ARIA AI.
Soporta WordPress (REST API), Webflow (API token), Contentful (API key), Sanity (API key).
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

logger = logging.getLogger("aria.connections.cms")


class WordPressConnection:
    """WordPress via Application Password (no OAuth needed for self-hosted)."""

    def _creds(self) -> tuple[str, str, str]:
        from apps.core.config import settings

        url = getattr(settings, "WORDPRESS_URL", "") or ""
        user = getattr(settings, "WORDPRESS_USERNAME", "") or ""
        password = getattr(settings, "WORDPRESS_APP_PASSWORD", "") or ""
        return url.rstrip("/"), user, password

    def _h(self, user: str, password: str) -> dict:
        import base64

        creds = base64.b64encode(f"{user}:{password}".encode()).decode()
        return {"Authorization": f"Basic {creds}", "Content-Type": "application/json"}

    async def list_posts(self, status: str = "publish", per_page: int = 10) -> list[dict]:
        url, user, password = self._creds()
        if not url or not user or not password:
            return [
                {
                    "error": "WORDPRESS_URL / WORDPRESS_USERNAME / WORDPRESS_APP_PASSWORD no configurados"
                }
            ]
        async with httpx.AsyncClient(timeout=15.0) as http:
            r = await http.get(
                f"{url}/wp-json/wp/v2/posts",
                headers=self._h(user, password),
                params={"status": status, "per_page": per_page},
            )
            r.raise_for_status()
            return [
                {
                    "id": p.get("id"),
                    "title": p.get("title", {}).get("rendered", ""),
                    "status": p.get("status"),
                    "link": p.get("link"),
                    "date": p.get("date"),
                }
                for p in r.json()
            ]

    async def create_post(
        self,
        title: str,
        content: str,
        status: str = "draft",
        categories: list = None,
        tags: list = None,
    ) -> dict:
        if tags is None:
            tags = []
        if categories is None:
            categories = []
        url, user, password = self._creds()
        if not url or not user or not password:
            return {
                "error": "WORDPRESS_URL / WORDPRESS_USERNAME / WORDPRESS_APP_PASSWORD no configurados"
            }
        payload: dict[str, Any] = {"title": title, "content": content, "status": status}
        if categories:
            payload["categories"] = categories
        if tags:
            payload["tags"] = tags
        async with httpx.AsyncClient(timeout=15.0) as http:
            r = await http.post(
                f"{url}/wp-json/wp/v2/posts",
                headers=self._h(user, password),
                json=payload,
            )
            if r.status_code in (200, 201):
                data = r.json()
                return {
                    "success": True,
                    "id": data.get("id"),
                    "link": data.get("link"),
                    "status": data.get("status"),
                }
            return {"success": False, "status": r.status_code}

    async def update_post(self, post_id: int, updates: dict) -> dict:
        url, user, password = self._creds()
        if not url or not user or not password:
            return {
                "error": "WORDPRESS_URL / WORDPRESS_USERNAME / WORDPRESS_APP_PASSWORD no configurados"
            }
        async with httpx.AsyncClient(timeout=15.0) as http:
            r = await http.put(
                f"{url}/wp-json/wp/v2/posts/{post_id}",
                headers=self._h(user, password),
                json=updates,
            )
            return {"success": r.status_code in (200, 201), "data": r.json()}

    async def list_pages(self, per_page: int = 10) -> list[dict]:
        url, user, password = self._creds()
        if not url or not user or not password:
            return [
                {
                    "error": "WORDPRESS_URL / WORDPRESS_USERNAME / WORDPRESS_APP_PASSWORD no configurados"
                }
            ]
        async with httpx.AsyncClient(timeout=15.0) as http:
            r = await http.get(
                f"{url}/wp-json/wp/v2/pages",
                headers=self._h(user, password),
                params={"per_page": per_page},
            )
            r.raise_for_status()
            return [
                {
                    "id": p.get("id"),
                    "title": p.get("title", {}).get("rendered", ""),
                    "link": p.get("link"),
                }
                for p in r.json()
            ]


class WebflowConnection:
    """Webflow via API token (v2)."""

    API = "https://api.webflow.com/v2"

    def _token(self) -> str | None:
        from apps.core.config import settings

        return getattr(settings, "WEBFLOW_API_TOKEN", None)

    def _h(self) -> dict:
        tok = self._token() or ""
        return {
            "Authorization": f"Bearer {tok}",
            "Accept": "application/json",
        }

    async def list_sites(self) -> list[dict]:
        token = self._token()
        if not token:
            return [{"error": "WEBFLOW_API_TOKEN no configurado"}]
        async with httpx.AsyncClient(timeout=15.0) as http:
            r = await http.get(f"{self.API}/sites", headers=self._h())
            r.raise_for_status()
            return [
                {
                    "id": s.get("id"),
                    "displayName": s.get("displayName"),
                    "shortName": s.get("shortName"),
                    "lastPublished": s.get("lastPublished"),
                }
                for s in r.json().get("sites", [])
            ]

    async def list_collections(self, site_id: str) -> list[dict]:
        token = self._token()
        if not token:
            return [{"error": "WEBFLOW_API_TOKEN no configurado"}]
        async with httpx.AsyncClient(timeout=15.0) as http:
            r = await http.get(f"{self.API}/sites/{site_id}/collections", headers=self._h())
            r.raise_for_status()
            return [
                {
                    "id": c.get("id"),
                    "displayName": c.get("displayName"),
                    "singularName": c.get("singularName"),
                }
                for c in r.json().get("collections", [])
            ]

    async def list_items(self, collection_id: str, limit: int = 20) -> list[dict]:
        token = self._token()
        if not token:
            return [{"error": "WEBFLOW_API_TOKEN no configurado"}]
        async with httpx.AsyncClient(timeout=15.0) as http:
            r = await http.get(
                f"{self.API}/collections/{collection_id}/items",
                headers=self._h(),
                params={"limit": limit},
            )
            r.raise_for_status()
            return r.json().get("items", [])

    async def publish_site(self, site_id: str) -> dict:
        token = self._token()
        if not token:
            return {"error": "WEBFLOW_API_TOKEN no configurado"}
        async with httpx.AsyncClient(timeout=20.0) as http:
            r = await http.post(f"{self.API}/sites/{site_id}/publish", headers=self._h(), json={})
            return {"success": r.status_code in (200, 202), "data": r.json()}


class ContentfulConnection:
    """Contentful via Content Delivery API + Management API."""

    CDA = "https://cdn.contentful.com"
    CMA = "https://api.contentful.com"

    def _creds(self) -> tuple[str, str, str]:
        from apps.core.config import settings

        space = getattr(settings, "CONTENTFUL_SPACE_ID", "") or ""
        delivery_token = getattr(settings, "CONTENTFUL_DELIVERY_TOKEN", "") or ""
        mgmt_token = getattr(settings, "CONTENTFUL_MANAGEMENT_TOKEN", "") or ""
        return space, delivery_token, mgmt_token

    async def get_entries(self, content_type: str = "", limit: int = 10) -> list[dict]:
        space, delivery_token, _ = self._creds()
        if not space or not delivery_token:
            return [{"error": "CONTENTFUL_SPACE_ID / CONTENTFUL_DELIVERY_TOKEN no configurados"}]
        params: dict[str, Any] = {"access_token": delivery_token, "limit": limit}
        if content_type:
            params["content_type"] = content_type
        async with httpx.AsyncClient(timeout=15.0) as http:
            r = await http.get(f"{self.CDA}/spaces/{space}/entries", params=params)
            r.raise_for_status()
            return r.json().get("items", [])

    async def get_content_types(self) -> list[dict]:
        space, delivery_token, _ = self._creds()
        if not space or not delivery_token:
            return [{"error": "CONTENTFUL_SPACE_ID / CONTENTFUL_DELIVERY_TOKEN no configurados"}]
        async with httpx.AsyncClient(timeout=15.0) as http:
            r = await http.get(
                f"{self.CDA}/spaces/{space}/content_types",
                params={"access_token": delivery_token},
            )
            r.raise_for_status()
            return [
                {
                    "id": ct.get("sys", {}).get("id"),
                    "name": ct.get("name"),
                    "description": ct.get("description", ""),
                }
                for ct in r.json().get("items", [])
            ]

    async def create_entry(self, content_type_id: str, fields: dict) -> dict:
        space, _, mgmt_token = self._creds()
        if not space or not mgmt_token:
            return {"error": "CONTENTFUL_SPACE_ID / CONTENTFUL_MANAGEMENT_TOKEN no configurados"}
        async with httpx.AsyncClient(timeout=15.0) as http:
            r = await http.post(
                f"{self.CMA}/spaces/{space}/environments/master/entries",
                headers={
                    "Authorization": f"Bearer {mgmt_token}",
                    "Content-Type": "application/vnd.contentful.management.v1+json",
                    "X-Contentful-Content-Type": content_type_id,
                },
                json={"fields": fields},
            )
            if r.status_code in (200, 201):
                return {"success": True, "id": r.json().get("sys", {}).get("id")}
            return {"success": False, "status": r.status_code}


class SanityConnection:
    """Sanity via API token."""

    def _creds(self) -> tuple[str, str, str]:
        from apps.core.config import settings

        project_id = getattr(settings, "SANITY_PROJECT_ID", "") or ""
        dataset = getattr(settings, "SANITY_DATASET", "production") or "production"
        token = getattr(settings, "SANITY_API_TOKEN", "") or ""
        return project_id, dataset, token

    def _api(self, project_id: str, dataset: str) -> str:
        return f"https://{project_id}.api.sanity.io/v2021-10-21/data"

    def _h(self, token: str) -> dict:
        return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

    async def query(self, groq_query: str, params: dict = None) -> dict:
        if params is None:
            params = {}
        project_id, dataset, token = self._creds()
        if not project_id:
            return {"error": "SANITY_PROJECT_ID no configurado"}
        query_params: dict = {"query": groq_query}
        if params:
            for k, v in params.items():
                query_params[f"${k}"] = v
        headers = self._h(token) if token else {}
        async with httpx.AsyncClient(timeout=15.0) as http:
            r = await http.get(
                f"{self._api(project_id, dataset)}/query/{dataset}",
                headers=headers,
                params=query_params,
            )
            r.raise_for_status()
            return {"result": r.json().get("result", [])}

    async def create_document(self, doc_type: str, fields: dict) -> dict:
        project_id, dataset, token = self._creds()
        if not project_id or not token:
            return {"error": "SANITY_PROJECT_ID / SANITY_API_TOKEN no configurados"}
        mutation = {"mutations": [{"create": {"_type": doc_type, **fields}}]}
        async with httpx.AsyncClient(timeout=15.0) as http:
            r = await http.post(
                f"{self._api(project_id, dataset)}/mutate/{dataset}",
                headers=self._h(token),
                json=mutation,
            )
            if r.status_code in (200, 201):
                results = r.json().get("results", [{}])
                return {"success": True, "id": results[0].get("id")}
            return {"success": False, "status": r.status_code}
