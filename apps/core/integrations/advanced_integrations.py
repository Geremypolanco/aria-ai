"""
advanced_integrations.py — Advanced Integrations System for ARIA.

Provides:
- Full GitHub integration
- External API management
- Database connectivity
- OAuth2 authentication
- Webhooks and events
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import jwt

logger = logging.getLogger("aria.integrations")


class GitHubIntegration:
    """Advanced integration with GitHub."""

    def __init__(self, token: str = None):
        self.token = token
        self.base_url = "https://api.github.com"
        self.headers = {
            "Authorization": f"token {token}" if token else "",
            "Accept": "application/vnd.github.v3+json",
        }

    async def get_user_repos(self) -> dict[str, Any]:
        """Gets the user's repositories."""
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    f"{self.base_url}/user/repos",
                    headers=self.headers,
                    params={"per_page": 100},
                )

                if response.status_code == 200:
                    repos = response.json()
                    return {
                        "success": True,
                        "repositories": repos,
                        "count": len(repos),
                    }
                return {"success": False, "error": f"HTTP {response.status_code}"}

        except Exception as exc:
            logger.error(f"[GitHub] Error getting repositories: {exc}")
            return {"success": False, "error": str(exc)}

    async def create_repository(
        self,
        name: str,
        description: str = "",
        private: bool = True,
        auto_init: bool = True,
    ) -> dict[str, Any]:
        """Creates a new repository."""
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    f"{self.base_url}/user/repos",
                    headers=self.headers,
                    json={
                        "name": name,
                        "description": description,
                        "private": private,
                        "auto_init": auto_init,
                    },
                )

                if response.status_code == 201:
                    repo = response.json()
                    return {
                        "success": True,
                        "repository": repo,
                        "url": repo.get("html_url"),
                    }
                return {"success": False, "error": f"HTTP {response.status_code}"}

        except Exception as exc:
            logger.error(f"[GitHub] Error creating repository: {exc}")
            return {"success": False, "error": str(exc)}

    async def commit_and_push(
        self,
        owner: str,
        repo: str,
        files: dict[str, str],
        message: str,
        branch: str = "main",
    ) -> dict[str, Any]:
        """Performs a commit and push to a repository."""
        try:
            # Get the current branch
            async with httpx.AsyncClient() as client:
                # Get the latest commit
                ref_response = await client.get(
                    f"{self.base_url}/repos/{owner}/{repo}/git/refs/heads/{branch}",
                    headers=self.headers,
                )

                if ref_response.status_code != 200:
                    return {"success": False, "error": "Branch not found"}

                latest_commit_sha = ref_response.json()["object"]["sha"]

                # Create blobs for each file
                blob_shas = {}
                for filename, content in files.items():
                    blob_response = await client.post(
                        f"{self.base_url}/repos/{owner}/{repo}/git/blobs",
                        headers=self.headers,
                        json={
                            "content": content,
                            "encoding": "utf-8",
                        },
                    )
                    if blob_response.status_code == 201:
                        blob_shas[filename] = blob_response.json()["sha"]

                # Get the tree of the latest commit
                commit_response = await client.get(
                    f"{self.base_url}/repos/{owner}/{repo}/git/commits/{latest_commit_sha}",
                    headers=self.headers,
                )
                tree_sha = commit_response.json()["tree"]["sha"]

                # Create new tree
                tree_data = {
                    "base_tree": tree_sha,
                    "tree": [
                        {
                            "path": filename,
                            "mode": "100644",
                            "type": "blob",
                            "sha": blob_shas[filename],
                        }
                        for filename in blob_shas
                    ],
                }

                tree_response = await client.post(
                    f"{self.base_url}/repos/{owner}/{repo}/git/trees",
                    headers=self.headers,
                    json=tree_data,
                )

                if tree_response.status_code != 201:
                    return {"success": False, "error": "Error creating tree"}

                new_tree_sha = tree_response.json()["sha"]

                # Create new commit
                commit_data = {
                    "message": message,
                    "tree": new_tree_sha,
                    "parents": [latest_commit_sha],
                }

                new_commit_response = await client.post(
                    f"{self.base_url}/repos/{owner}/{repo}/git/commits",
                    headers=self.headers,
                    json=commit_data,
                )

                if new_commit_response.status_code != 201:
                    return {"success": False, "error": "Error creating commit"}

                new_commit_sha = new_commit_response.json()["sha"]

                # Update reference
                update_response = await client.patch(
                    f"{self.base_url}/repos/{owner}/{repo}/git/refs/heads/{branch}",
                    headers=self.headers,
                    json={"sha": new_commit_sha},
                )

                if update_response.status_code == 200:
                    return {
                        "success": True,
                        "commit_sha": new_commit_sha,
                        "message": message,
                    }
                return {"success": False, "error": "Error updating reference"}

        except Exception as exc:
            logger.error(f"[GitHub] Error in commit/push: {exc}")
            return {"success": False, "error": str(exc)}


class DatabaseIntegration:
    """Database integration."""

    def __init__(self, connection_string: str = None):
        self.connection_string = connection_string
        self.connection = None

    async def connect(self, db_type: str = "postgresql") -> bool:
        """Connects to the database."""
        try:
            if db_type == "postgresql":
                import asyncpg

                self.connection = await asyncpg.connect(self.connection_string)
            elif db_type == "mysql":
                # Parse connection string
                pass
            else:
                logger.error(f"[Database] Unsupported DB type: {db_type}")
                return False

            logger.info("[Database] Connected to the database")
            return True

        except Exception as exc:
            logger.error(f"[Database] Error connecting: {exc}")
            return False

    async def execute_query(self, query: str, params: list[Any] = None) -> dict[str, Any]:
        """Executes a SQL query."""
        try:
            if not self.connection:
                return {"success": False, "error": "Not connected to the DB"}

            result = await self.connection.fetch(query, *(params or []))

            return {
                "success": True,
                "rows": result,
                "count": len(result),
            }

        except Exception as exc:
            logger.error(f"[Database] Error executing query: {exc}")
            return {"success": False, "error": str(exc)}

    async def execute_mutation(self, query: str, params: list[Any] = None) -> dict[str, Any]:
        """Executes a mutation (INSERT, UPDATE, DELETE)."""
        try:
            if not self.connection:
                return {"success": False, "error": "Not connected to the DB"}

            result = await self.connection.execute(query, *(params or []))

            return {
                "success": True,
                "affected_rows": result,
            }

        except Exception as exc:
            logger.error(f"[Database] Error executing mutation: {exc}")
            return {"success": False, "error": str(exc)}

    async def close(self) -> None:
        """Closes the connection."""
        if self.connection:
            try:
                await self.connection.close()
                logger.info("[Database] Connection closed")
            except Exception as exc:
                logger.error(f"[Database] Error closing connection: {exc}")


class OAuth2Integration:
    """OAuth2 integration for authentication."""

    def __init__(self, client_id: str, client_secret: str, redirect_uri: str):
        self.client_id = client_id
        self.client_secret = client_secret
        self.redirect_uri = redirect_uri
        self.tokens: dict[str, dict[str, Any]] = {}

    def generate_auth_url(self, provider: str, scope: list[str]) -> str:
        """Generates authorization URL."""
        auth_urls = {
            "github": "https://github.com/login/oauth/authorize",
            "google": "https://accounts.google.com/o/oauth2/v2/auth",
            "microsoft": "https://login.microsoftonline.com/common/oauth2/v2.0/authorize",
        }

        base_url = auth_urls.get(provider, "")
        if not base_url:
            return ""

        params = {
            "client_id": self.client_id,
            "redirect_uri": self.redirect_uri,
            "scope": " ".join(scope),
            "response_type": "code",
        }

        query_string = "&".join([f"{k}={v}" for k, v in params.items()])
        return f"{base_url}?{query_string}"

    async def exchange_code(self, provider: str, code: str) -> dict[str, Any]:
        """Exchanges a code for a token."""
        token_urls = {
            "github": "https://github.com/login/oauth/access_token",
            "google": "https://oauth2.googleapis.com/token",
            "microsoft": "https://login.microsoftonline.com/common/oauth2/v2.0/token",
        }

        token_url = token_urls.get(provider, "")
        if not token_url:
            return {"success": False, "error": "Provider not supported"}

        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    token_url,
                    data={
                        "client_id": self.client_id,
                        "client_secret": self.client_secret,
                        "code": code,
                        "redirect_uri": self.redirect_uri,
                    },
                    headers={"Accept": "application/json"},
                )

                if response.status_code == 200:
                    token_data = response.json()
                    self.tokens[provider] = token_data
                    return {"success": True, "token": token_data}
                return {"success": False, "error": f"HTTP {response.status_code}"}

        except Exception as exc:
            logger.error(f"[OAuth2] Error exchanging code: {exc}")
            return {"success": False, "error": str(exc)}

    def generate_jwt(self, payload: dict[str, Any], secret: str, expires_in: int = 3600) -> str:
        """Generates a JWT."""
        payload["exp"] = datetime.now(UTC) + timedelta(seconds=expires_in)
        payload["iat"] = datetime.now(UTC)

        return jwt.encode(payload, secret, algorithm="HS256")

    def verify_jwt(self, token: str, secret: str) -> dict[str, Any] | None:
        """Verifies a JWT."""
        try:
            return jwt.decode(token, secret, algorithms=["HS256"])
        except jwt.InvalidTokenError:
            return None


class WebhookIntegration:
    """Webhook integration for events."""

    def __init__(self):
        self.webhooks: dict[str, list[str]] = {}
        self.event_history: list[dict[str, Any]] = []

    def register_webhook(self, event_type: str, url: str) -> bool:
        """Registers a webhook for an event type."""
        try:
            if event_type not in self.webhooks:
                self.webhooks[event_type] = []

            self.webhooks[event_type].append(url)
            logger.info(f"[Webhooks] Webhook registered: {event_type} -> {url}")
            return True

        except Exception as exc:
            logger.error(f"[Webhooks] Error registering webhook: {exc}")
            return False

    async def trigger_event(self, event_type: str, payload: dict[str, Any]) -> dict[str, Any]:
        """Triggers an event and notifies registered webhooks."""
        try:
            urls = self.webhooks.get(event_type, [])

            if not urls:
                logger.warning(f"[Webhooks] No webhooks registered for {event_type}")
                return {"success": True, "webhooks_triggered": 0}

            # Log event
            self.event_history.append(
                {
                    "event_type": event_type,
                    "payload": payload,
                    "timestamp": datetime.now(UTC).isoformat(),
                }
            )

            # Trigger webhooks
            tasks = [self._call_webhook(url, event_type, payload) for url in urls]
            results = await asyncio.gather(*tasks, return_exceptions=True)

            successful = sum(1 for r in results if isinstance(r, dict) and r.get("success"))

            return {
                "success": True,
                "event_type": event_type,
                "webhooks_triggered": len(urls),
                "successful": successful,
            }

        except Exception as exc:
            logger.error(f"[Webhooks] Error triggering event: {exc}")
            return {"success": False, "error": str(exc)}

    async def _call_webhook(
        self, url: str, event_type: str, payload: dict[str, Any]
    ) -> dict[str, Any]:
        """Calls a webhook."""
        try:
            # HMAC signature — the key comes from configuration (environment variable).
            from apps.core.config import settings

            secret = getattr(settings, "WEBHOOK_SECRET", None) or "webhook_secret_unset"
            signature = hmac.new(
                secret.encode(),
                json.dumps(payload).encode(),
                hashlib.sha256,
            ).hexdigest()

            async with httpx.AsyncClient() as client:
                response = await client.post(
                    url,
                    json=payload,
                    headers={
                        "X-Event-Type": event_type,
                        "X-Signature": signature,
                    },
                    timeout=10,
                )

                return {
                    "success": response.status_code == 200,
                    "url": url,
                    "status_code": response.status_code,
                }

        except Exception as exc:
            logger.error(f"[Webhooks] Error calling webhook: {exc}")
            return {"success": False, "url": url, "error": str(exc)}
