"""
Project Management connections for ARIA AI.
Covers: Asana, Trello, Linear, Jira, Monday.com

Required secrets (Fly.io):
  ASANA_ACCESS_TOKEN, ASANA_CLIENT_ID, ASANA_CLIENT_SECRET
  TRELLO_API_KEY, TRELLO_TOKEN
  LINEAR_API_KEY, LINEAR_CLIENT_ID, LINEAR_CLIENT_SECRET
  ATLASSIAN_CLIENT_ID, ATLASSIAN_CLIENT_SECRET
  MONDAY_API_KEY, MONDAY_CLIENT_ID, MONDAY_CLIENT_SECRET
"""
from __future__ import annotations

import logging
from typing import Any, Optional
from urllib.parse import urlencode

import httpx

logger = logging.getLogger("aria.connections.pm")


# ── ASANA ─────────────────────────────────────────────────────────────────────

class AsanaConnection:

    REDIRECT_URI = "https://aria-ai.fly.dev/oauth/callback/asana"
    AUTH_URL = "https://app.asana.com/-/oauth_authorize"
    TOKEN_URL = "https://app.asana.com/-/oauth_token"
    BASE = "https://app.asana.com/api/1.0"

    def _token(self) -> Optional[str]:
        from apps.core.config import settings
        return getattr(settings, "ASANA_ACCESS_TOKEN", None)

    def _client_id(self) -> Optional[str]:
        from apps.core.config import settings
        return getattr(settings, "ASANA_CLIENT_ID", None)

    def _client_secret(self) -> Optional[str]:
        from apps.core.config import settings
        return getattr(settings, "ASANA_CLIENT_SECRET", None)

    def get_auth_url(self, chat_id: str) -> Optional[str]:
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

    async def exchange_code(self, code: str, chat_id: str) -> Optional[dict]:
        cid = self._client_id()
        sec = self._client_secret()
        if not cid or not sec:
            raise ValueError("ASANA_CLIENT_ID / ASANA_CLIENT_SECRET not configured")
        async with httpx.AsyncClient(timeout=15.0) as http:
            r = await http.post(self.TOKEN_URL, data={
                "code": code,
                "client_id": cid,
                "client_secret": sec,
                "redirect_uri": self.REDIRECT_URI,
                "grant_type": "authorization_code",
            })
            r.raise_for_status()
            data = r.json()
            return {
                "access_token": data["access_token"],
                "refresh_token": data.get("refresh_token"),
                "expires_in": data.get("expires_in", 3600),
                "scope": data.get("scope", ""),
            }

    def _h(self, tok: str) -> dict:
        return {"Authorization": f"Bearer {tok}"}

    async def list_workspaces(self, tok: str) -> list[dict]:
        """List all Asana workspaces accessible to the user."""
        async with httpx.AsyncClient(timeout=15.0) as http:
            r = await http.get(
                f"{self.BASE}/workspaces",
                headers=self._h(tok),
            )
            r.raise_for_status()
            return r.json().get("data", [])

    async def list_projects(self, tok: str, workspace_gid: Optional[str] = None) -> list[dict]:
        """List projects, optionally filtered by workspace."""
        async with httpx.AsyncClient(timeout=15.0) as http:
            params: dict[str, Any] = {"opt_fields": "gid,name,current_status"}
            if workspace_gid:
                params["workspace"] = workspace_gid
            r = await http.get(
                f"{self.BASE}/projects",
                headers=self._h(tok),
                params=params,
            )
            r.raise_for_status()
            return [
                {
                    "gid": p.get("gid"),
                    "name": p.get("name"),
                    "status": (p.get("current_status") or {}).get("text", ""),
                }
                for p in r.json().get("data", [])
            ]

    async def list_tasks(self, tok: str, project_gid: str, completed: bool = False) -> list[dict]:
        """List tasks for a project."""
        async with httpx.AsyncClient(timeout=15.0) as http:
            r = await http.get(
                f"{self.BASE}/projects/{project_gid}/tasks",
                headers=self._h(tok),
                params={
                    "completed_since": "now" if not completed else "",
                    "opt_fields": "gid,name,due_on,assignee.name",
                },
            )
            r.raise_for_status()
            return [
                {
                    "gid": t.get("gid"),
                    "name": t.get("name"),
                    "due_on": t.get("due_on", ""),
                    "assignee": (t.get("assignee") or {}).get("name", ""),
                }
                for t in r.json().get("data", [])
            ]

    async def create_task(
        self,
        tok: str,
        workspace_gid: str,
        name: str,
        notes: str = "",
        due_on: str = "",
        assignee: str = "me",
    ) -> dict:
        """Create a new Asana task."""
        payload: dict[str, Any] = {
            "data": {
                "workspace": workspace_gid,
                "name": name,
                "notes": notes,
                "assignee": assignee,
            }
        }
        if due_on:
            payload["data"]["due_on"] = due_on
        async with httpx.AsyncClient(timeout=15.0) as http:
            r = await http.post(
                f"{self.BASE}/tasks",
                headers={**self._h(tok), "Content-Type": "application/json"},
                json=payload,
            )
            r.raise_for_status()
            return r.json().get("data", {})

    async def complete_task(self, tok: str, task_gid: str) -> dict:
        """Mark an Asana task as completed."""
        async with httpx.AsyncClient(timeout=15.0) as http:
            r = await http.put(
                f"{self.BASE}/tasks/{task_gid}",
                headers={**self._h(tok), "Content-Type": "application/json"},
                json={"data": {"completed": True}},
            )
            r.raise_for_status()
            return r.json().get("data", {})


# ── TRELLO ────────────────────────────────────────────────────────────────────

class TrelloConnection:
    """Trello uses API key + token query params — no OAuth flow needed."""

    BASE = "https://api.trello.com/1"

    def _key(self) -> Optional[str]:
        from apps.core.config import settings
        return getattr(settings, "TRELLO_API_KEY", None)

    def _token(self) -> Optional[str]:
        from apps.core.config import settings
        return getattr(settings, "TRELLO_TOKEN", None)

    def _auth_params(self) -> dict:
        return {"key": self._key(), "token": self._token()}

    async def list_boards(self) -> list[dict]:
        """List all Trello boards for the authenticated member."""
        async with httpx.AsyncClient(timeout=15.0) as http:
            r = await http.get(
                f"{self.BASE}/members/me/boards",
                params={**self._auth_params(), "fields": "id,name,url"},
            )
            r.raise_for_status()
            return [
                {"id": b.get("id"), "name": b.get("name"), "url": b.get("url")}
                for b in r.json()
            ]

    async def list_lists(self, board_id: str) -> list[dict]:
        """List all lists on a board."""
        async with httpx.AsyncClient(timeout=15.0) as http:
            r = await http.get(
                f"{self.BASE}/boards/{board_id}/lists",
                params=self._auth_params(),
            )
            r.raise_for_status()
            return r.json()

    async def list_cards(self, list_id: str) -> list[dict]:
        """List all cards in a Trello list."""
        async with httpx.AsyncClient(timeout=15.0) as http:
            r = await http.get(
                f"{self.BASE}/lists/{list_id}/cards",
                params={**self._auth_params(), "fields": "id,name,desc,due,url"},
            )
            r.raise_for_status()
            return [
                {
                    "id": c.get("id"),
                    "name": c.get("name"),
                    "desc": c.get("desc", ""),
                    "due": c.get("due", ""),
                    "url": c.get("url", ""),
                }
                for c in r.json()
            ]

    async def create_card(
        self,
        list_id: str,
        name: str,
        desc: str = "",
        due: Optional[str] = None,
    ) -> dict:
        """Create a new card in a Trello list."""
        payload = {**self._auth_params(), "idList": list_id, "name": name, "desc": desc}
        if due:
            payload["due"] = due
        async with httpx.AsyncClient(timeout=15.0) as http:
            r = await http.post(f"{self.BASE}/cards", params=payload)
            r.raise_for_status()
            return r.json()

    async def move_card(self, card_id: str, list_id: str) -> dict:
        """Move a card to a different list."""
        async with httpx.AsyncClient(timeout=15.0) as http:
            r = await http.put(
                f"{self.BASE}/cards/{card_id}",
                params={**self._auth_params(), "idList": list_id},
            )
            r.raise_for_status()
            return r.json()

    async def create_list(self, board_id: str, name: str, pos: str = "bottom") -> dict:
        """Create a new list on a Trello board."""
        async with httpx.AsyncClient(timeout=15.0) as http:
            r = await http.post(
                f"{self.BASE}/lists",
                params={**self._auth_params(), "idBoard": board_id, "name": name, "pos": pos},
            )
            r.raise_for_status()
            return r.json()


# ── LINEAR ────────────────────────────────────────────────────────────────────

class LinearConnection:

    REDIRECT_URI = "https://aria-ai.fly.dev/oauth/callback/linear"
    AUTH_URL = "https://linear.app/oauth/authorize"
    TOKEN_URL = "https://api.linear.app/oauth/token"
    GRAPHQL_URL = "https://api.linear.app/graphql"

    def _key(self) -> Optional[str]:
        from apps.core.config import settings
        return getattr(settings, "LINEAR_API_KEY", None)

    def _client_id(self) -> Optional[str]:
        from apps.core.config import settings
        return getattr(settings, "LINEAR_CLIENT_ID", None)

    def _client_secret(self) -> Optional[str]:
        from apps.core.config import settings
        return getattr(settings, "LINEAR_CLIENT_SECRET", None)

    def get_auth_url(self, chat_id: str) -> Optional[str]:
        cid = self._client_id()
        if not cid:
            return None
        params = {
            "client_id": cid,
            "redirect_uri": self.REDIRECT_URI,
            "response_type": "code",
            "scope": "read write",
            "state": chat_id,
        }
        return f"{self.AUTH_URL}?{urlencode(params)}"

    async def exchange_code(self, code: str, chat_id: str) -> Optional[dict]:
        cid = self._client_id()
        sec = self._client_secret()
        if not cid or not sec:
            raise ValueError("LINEAR_CLIENT_ID / LINEAR_CLIENT_SECRET not configured")
        async with httpx.AsyncClient(timeout=15.0) as http:
            r = await http.post(self.TOKEN_URL, data={
                "code": code,
                "client_id": cid,
                "client_secret": sec,
                "redirect_uri": self.REDIRECT_URI,
                "grant_type": "authorization_code",
            })
            r.raise_for_status()
            data = r.json()
            return {
                "access_token": data["access_token"],
                "expires_in": data.get("expires_in", 3600),
                "scope": data.get("scope", ""),
            }

    def _h(self, tok: str) -> dict:
        # Linear does not use "Bearer" prefix
        return {"Authorization": tok, "Content-Type": "application/json"}

    async def graphql(self, tok: str, query: str, variables: Optional[dict] = None) -> dict:
        """Execute a GraphQL query against the Linear API."""
        payload: dict[str, Any] = {"query": query}
        if variables:
            payload["variables"] = variables
        async with httpx.AsyncClient(timeout=15.0) as http:
            r = await http.post(self.GRAPHQL_URL, headers=self._h(tok), json=payload)
            r.raise_for_status()
            return r.json()

    async def list_issues(self, tok: str, limit: int = 20, state: str = "") -> list[dict]:
        """List Linear issues, optionally filtered by state name."""
        filter_clause = f'filter: {{ state: {{ name: {{ eq: "{state}" }} }} }}' if state else ""
        query = f"""
        query {{
          issues(first: {limit} {filter_clause}) {{
            nodes {{
              id title
              state {{ name }}
              priority
              assignee {{ name }}
            }}
          }}
        }}
        """
        data = await self.graphql(tok, query)
        return [
            {
                "id": i.get("id"),
                "title": i.get("title"),
                "state": (i.get("state") or {}).get("name", ""),
                "priority": i.get("priority", 0),
                "assignee": (i.get("assignee") or {}).get("name", ""),
            }
            for i in data.get("data", {}).get("issues", {}).get("nodes", [])
        ]

    async def create_issue(
        self,
        tok: str,
        team_id: str,
        title: str,
        description: str = "",
        priority: int = 0,
    ) -> dict:
        """Create a new Linear issue."""
        query = """
        mutation CreateIssue($teamId: String!, $title: String!, $description: String, $priority: Int) {
          issueCreate(input: {
            teamId: $teamId
            title: $title
            description: $description
            priority: $priority
          }) {
            success
            issue { id title url }
          }
        }
        """
        variables = {
            "teamId": team_id,
            "title": title,
            "description": description,
            "priority": priority,
        }
        data = await self.graphql(tok, query, variables)
        return data.get("data", {}).get("issueCreate", {})

    async def list_teams(self, tok: str) -> list[dict]:
        """List all Linear teams."""
        query = "query { teams { nodes { id name key } } }"
        data = await self.graphql(tok, query)
        return data.get("data", {}).get("teams", {}).get("nodes", [])

    async def list_projects(self, tok: str) -> list[dict]:
        """List all Linear projects."""
        query = "query { projects { nodes { id name description state } } }"
        data = await self.graphql(tok, query)
        return data.get("data", {}).get("projects", {}).get("nodes", [])


# ── JIRA ──────────────────────────────────────────────────────────────────────

class JiraConnection:

    REDIRECT_URI = "https://aria-ai.fly.dev/oauth/callback/jira"
    AUTH_URL = "https://auth.atlassian.com/authorize"
    TOKEN_URL = "https://auth.atlassian.com/oauth/token"
    SCOPES = "read:jira-user read:jira-work write:jira-work offline_access"

    def _client_id(self) -> Optional[str]:
        from apps.core.config import settings
        return getattr(settings, "ATLASSIAN_CLIENT_ID", None)

    def _client_secret(self) -> Optional[str]:
        from apps.core.config import settings
        return getattr(settings, "ATLASSIAN_CLIENT_SECRET", None)

    def get_auth_url(self, chat_id: str) -> Optional[str]:
        cid = self._client_id()
        if not cid:
            return None
        params = {
            "client_id": cid,
            "redirect_uri": self.REDIRECT_URI,
            "response_type": "code",
            "scope": self.SCOPES,
            "audience": "api.atlassian.com",
            "prompt": "consent",
            "state": chat_id,
        }
        return f"{self.AUTH_URL}?{urlencode(params)}"

    async def exchange_code(self, code: str, chat_id: str) -> Optional[dict]:
        cid = self._client_id()
        sec = self._client_secret()
        if not cid or not sec:
            raise ValueError("ATLASSIAN_CLIENT_ID / ATLASSIAN_CLIENT_SECRET not configured")
        async with httpx.AsyncClient(timeout=15.0) as http:
            r = await http.post(self.TOKEN_URL, json={
                "code": code,
                "client_id": cid,
                "client_secret": sec,
                "redirect_uri": self.REDIRECT_URI,
                "grant_type": "authorization_code",
            })
            r.raise_for_status()
            data = r.json()
            # Retrieve cloud_id from accessible resources
            res = await http.get(
                "https://api.atlassian.com/oauth/token/accessible-resources",
                headers={"Authorization": f"Bearer {data['access_token']}"},
            )
            cloud_id = ""
            if res.status_code == 200 and res.json():
                cloud_id = res.json()[0].get("id", "")
            return {
                "access_token": data["access_token"],
                "refresh_token": data.get("refresh_token"),
                "expires_in": data.get("expires_in", 3600),
                "scope": data.get("scope", ""),
                "cloud_id": cloud_id,
            }

    def _base(self, tokens: dict) -> str:
        return f"https://api.atlassian.com/ex/jira/{tokens['cloud_id']}/rest/api/3"

    def _h(self, tokens: dict) -> dict:
        return {
            "Authorization": f"Bearer {tokens['access_token']}",
            "Content-Type": "application/json",
        }

    async def list_projects(self, tokens: dict) -> list[dict]:
        """List all Jira projects."""
        async with httpx.AsyncClient(timeout=15.0) as http:
            r = await http.get(f"{self._base(tokens)}/project", headers=self._h(tokens))
            r.raise_for_status()
            return r.json()

    async def search_issues(self, tokens: dict, jql: str = "", max_results: int = 20) -> list[dict]:
        """Search Jira issues using JQL."""
        async with httpx.AsyncClient(timeout=15.0) as http:
            r = await http.post(
                f"{self._base(tokens)}/search",
                headers=self._h(tokens),
                json={"jql": jql or "ORDER BY updated DESC", "maxResults": max_results},
            )
            r.raise_for_status()
            return r.json().get("issues", [])

    async def create_issue(
        self,
        tokens: dict,
        project_key: str,
        summary: str,
        description: str = "",
        issue_type: str = "Task",
    ) -> dict:
        """Create a new Jira issue."""
        async with httpx.AsyncClient(timeout=15.0) as http:
            r = await http.post(
                f"{self._base(tokens)}/issue",
                headers=self._h(tokens),
                json={
                    "fields": {
                        "project": {"key": project_key},
                        "summary": summary,
                        "description": {
                            "type": "doc",
                            "version": 1,
                            "content": [
                                {
                                    "type": "paragraph",
                                    "content": [{"type": "text", "text": description}],
                                }
                            ],
                        },
                        "issuetype": {"name": issue_type},
                    }
                },
            )
            r.raise_for_status()
            return r.json()

    async def update_issue_status(self, tokens: dict, issue_key: str, transition_id: str) -> dict:
        """Transition a Jira issue to a new status."""
        async with httpx.AsyncClient(timeout=15.0) as http:
            r = await http.post(
                f"{self._base(tokens)}/issue/{issue_key}/transitions",
                headers=self._h(tokens),
                json={"transition": {"id": transition_id}},
            )
            r.raise_for_status()
            return {"success": True, "issue_key": issue_key, "transition_id": transition_id}

    async def list_transitions(self, tokens: dict, issue_key: str) -> list[dict]:
        """List available transitions for a Jira issue."""
        async with httpx.AsyncClient(timeout=15.0) as http:
            r = await http.get(
                f"{self._base(tokens)}/issue/{issue_key}/transitions",
                headers=self._h(tokens),
            )
            r.raise_for_status()
            return r.json().get("transitions", [])


# ── MONDAY ────────────────────────────────────────────────────────────────────

class MondayConnection:

    REDIRECT_URI = "https://aria-ai.fly.dev/oauth/callback/monday"
    AUTH_URL = "https://auth.monday.com/oauth2/authorize"
    TOKEN_URL = "https://auth.monday.com/oauth2/token"
    GRAPHQL_URL = "https://api.monday.com/v2"

    def _token(self) -> Optional[str]:
        from apps.core.config import settings
        return getattr(settings, "MONDAY_API_KEY", None)

    def _client_id(self) -> Optional[str]:
        from apps.core.config import settings
        return getattr(settings, "MONDAY_CLIENT_ID", None)

    def _client_secret(self) -> Optional[str]:
        from apps.core.config import settings
        return getattr(settings, "MONDAY_CLIENT_SECRET", None)

    def get_auth_url(self, chat_id: str) -> Optional[str]:
        cid = self._client_id()
        if not cid:
            return None
        params = {
            "client_id": cid,
            "redirect_uri": self.REDIRECT_URI,
            "response_type": "code",
            "scope": "boards:read boards:write",
            "state": chat_id,
        }
        return f"{self.AUTH_URL}?{urlencode(params)}"

    async def exchange_code(self, code: str, chat_id: str) -> Optional[dict]:
        cid = self._client_id()
        sec = self._client_secret()
        if not cid or not sec:
            raise ValueError("MONDAY_CLIENT_ID / MONDAY_CLIENT_SECRET not configured")
        async with httpx.AsyncClient(timeout=15.0) as http:
            r = await http.post(self.TOKEN_URL, data={
                "code": code,
                "client_id": cid,
                "client_secret": sec,
                "redirect_uri": self.REDIRECT_URI,
                "grant_type": "authorization_code",
            })
            r.raise_for_status()
            data = r.json()
            return {
                "access_token": data["access_token"],
                "expires_in": data.get("expires_in", 3600),
                "scope": data.get("scope", ""),
            }

    def _h(self, tok: str) -> dict:
        return {"Authorization": tok, "Content-Type": "application/json"}

    async def graphql(self, tok: str, query: str) -> dict:
        """Execute a GraphQL query against the Monday.com API."""
        async with httpx.AsyncClient(timeout=15.0) as http:
            r = await http.post(
                self.GRAPHQL_URL,
                headers=self._h(tok),
                json={"query": query},
            )
            r.raise_for_status()
            return r.json()

    async def list_boards(self, tok: str, limit: int = 20) -> list[dict]:
        """List Monday.com boards."""
        query = f"query {{ boards (limit: {limit}) {{ id name description }} }}"
        data = await self.graphql(tok, query)
        return data.get("data", {}).get("boards", [])

    async def list_items(self, tok: str, board_id: str, limit: int = 20) -> list[dict]:
        """List items on a Monday.com board."""
        query = f"""
        query {{
          boards (ids: [{board_id}]) {{
            items_page (limit: {limit}) {{
              items {{
                id name state
                column_values {{ id text }}
              }}
            }}
          }}
        }}
        """
        data = await self.graphql(tok, query)
        boards = data.get("data", {}).get("boards", [])
        if not boards:
            return []
        return boards[0].get("items_page", {}).get("items", [])

    async def create_item(
        self,
        tok: str,
        board_id: str,
        group_id: str,
        item_name: str,
        column_values: Optional[dict] = None,
    ) -> dict:
        """Create a new item on a Monday.com board."""
        import json as _json
        cv_str = _json.dumps(_json.dumps(column_values or {}))
        query = f"""
        mutation {{
          create_item (
            board_id: {board_id}
            group_id: "{group_id}"
            item_name: "{item_name}"
            column_values: {cv_str}
          ) {{ id name }}
        }}
        """
        data = await self.graphql(tok, query)
        return data.get("data", {}).get("create_item", {})

    async def update_item_status(
        self,
        tok: str,
        board_id: str,
        item_id: str,
        column_id: str,
        value: str,
    ) -> dict:
        """Update the status column of a Monday.com item."""
        import json as _json
        col_val = _json.dumps(_json.dumps({column_id: {"label": value}}))
        query = f"""
        mutation {{
          change_multiple_column_values (
            board_id: {board_id}
            item_id: {item_id}
            column_values: {col_val}
          ) {{ id name }}
        }}
        """
        data = await self.graphql(tok, query)
        return data.get("data", {}).get("change_multiple_column_values", {})
