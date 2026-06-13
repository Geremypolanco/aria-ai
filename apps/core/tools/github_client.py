"""
AriaGitHubClient — Full GitHub REST API v3 client for ARIA.

ARIA can:
  - Read any public/private repo (with token)
  - List contents, read files, list branches, PRs, issues, commits
  - Create/update files, create branches, open PRs and issues
  - Search code, repos, and issues
  - Read and improve her OWN source code (self-awareness)
"""
from __future__ import annotations

import base64
import logging
from typing import Any, Optional

import httpx

from apps.core.config import settings

logger = logging.getLogger("aria.github")

GITHUB_API = "https://api.github.com"
SELF_OWNER = "Geremypolanco"
SELF_REPO  = "aria-ai"


class AriaGitHubClient:

    def __init__(self) -> None:
        token = settings.GITHUB_TOKEN or ""
        self._headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        if token:
            self._headers["Authorization"] = f"Bearer {token}"
        self._http = httpx.AsyncClient(timeout=30.0, headers=self._headers)

    # ── helpers ───────────────────────────────────────────────────────────

    async def _get(self, path: str, params: dict = None) -> dict:
        try:
            r = await self._http.get(f"{GITHUB_API}{path}", params=params or {})
            if r.status_code == 404:
                return {"error": "No encontrado (404)", "status": 404}
            if r.status_code == 403:
                return {"error": "Acceso denegado (403) — verifica GITHUB_TOKEN", "status": 403}
            if r.status_code not in (200, 201):
                return {"error": f"HTTP {r.status_code}: {r.text[:200]}", "status": r.status_code}
            return r.json()
        except Exception as exc:
            logger.error("[GitHub] GET %s: %s", path, exc)
            return {"error": str(exc)}

    async def _put(self, path: str, body: dict) -> dict:
        try:
            r = await self._http.put(f"{GITHUB_API}{path}", json=body)
            if r.status_code not in (200, 201):
                return {"error": f"HTTP {r.status_code}: {r.text[:300]}", "status": r.status_code}
            return r.json()
        except Exception as exc:
            logger.error("[GitHub] PUT %s: %s", path, exc)
            return {"error": str(exc)}

    async def _post(self, path: str, body: dict) -> dict:
        try:
            r = await self._http.post(f"{GITHUB_API}{path}", json=body)
            if r.status_code not in (200, 201):
                return {"error": f"HTTP {r.status_code}: {r.text[:300]}", "status": r.status_code}
            return r.json()
        except Exception as exc:
            logger.error("[GitHub] POST %s: %s", path, exc)
            return {"error": str(exc)}

    # ── repo info ─────────────────────────────────────────────────────────

    async def get_repo(self, owner: str, repo: str) -> dict:
        return await self._get(f"/repos/{owner}/{repo}")

    async def list_contents(self, owner: str, repo: str, path: str = "",
                             branch: str = "main") -> list | dict:
        p = f"/repos/{owner}/{repo}/contents/{path.lstrip('/')}"
        return await self._get(p, {"ref": branch})

    async def get_file(self, owner: str, repo: str, path: str,
                        branch: str = "main") -> dict:
        """Returns decoded file content + sha."""
        data = await self._get(f"/repos/{owner}/{repo}/contents/{path.lstrip('/')}",
                                {"ref": branch})
        if "error" in data:
            return data
        if data.get("type") != "file":
            return {"error": f"'{path}' no es un archivo (es {data.get('type')})"}
        raw = data.get("content", "")
        try:
            content = base64.b64decode(raw).decode("utf-8", errors="replace")
        except Exception:
            content = raw
        return {"path": path, "content": content, "sha": data.get("sha", ""),
                "size": data.get("size", 0)}

    async def list_branches(self, owner: str, repo: str) -> list | dict:
        return await self._get(f"/repos/{owner}/{repo}/branches")

    async def list_commits(self, owner: str, repo: str, branch: str = "main",
                            per_page: int = 10) -> list | dict:
        return await self._get(f"/repos/{owner}/{repo}/commits",
                                {"sha": branch, "per_page": per_page})

    # ── write ─────────────────────────────────────────────────────────────

    async def create_or_update_file(self, owner: str, repo: str, path: str,
                                     content: str, message: str,
                                     branch: str = "main",
                                     sha: str = None) -> dict:
        """Create (sha=None) or update (sha=existing sha) a file."""
        body: dict = {
            "message": message,
            "content": base64.b64encode(content.encode()).decode(),
            "branch": branch,
        }
        if sha:
            body["sha"] = sha
        return await self._put(f"/repos/{owner}/{repo}/contents/{path.lstrip('/')}", body)

    async def create_branch(self, owner: str, repo: str,
                             new_branch: str, from_branch: str = "main") -> dict:
        ref_data = await self._get(f"/repos/{owner}/{repo}/git/ref/heads/{from_branch}")
        if "error" in ref_data:
            return ref_data
        sha = ref_data.get("object", {}).get("sha", "")
        if not sha:
            return {"error": "No se pudo obtener SHA del branch origen"}
        return await self._post(f"/repos/{owner}/{repo}/git/refs",
                                 {"ref": f"refs/heads/{new_branch}", "sha": sha})

    async def create_pr(self, owner: str, repo: str, title: str, body: str,
                         head: str, base: str = "main") -> dict:
        return await self._post(f"/repos/{owner}/{repo}/pulls",
                                 {"title": title, "body": body, "head": head, "base": base})

    # ── issues ────────────────────────────────────────────────────────────

    async def list_issues(self, owner: str, repo: str, state: str = "open",
                           per_page: int = 10) -> list | dict:
        return await self._get(f"/repos/{owner}/{repo}/issues",
                                {"state": state, "per_page": per_page})

    async def create_issue(self, owner: str, repo: str, title: str,
                            body: str = "", labels: list = None) -> dict:
        payload: dict = {"title": title, "body": body}
        if labels:
            payload["labels"] = labels
        return await self._post(f"/repos/{owner}/{repo}/issues", payload)

    # ── search ────────────────────────────────────────────────────────────

    async def search_code(self, query: str, per_page: int = 5) -> dict:
        return await self._get("/search/code", {"q": query, "per_page": per_page})

    async def search_repos(self, query: str, per_page: int = 5) -> dict:
        return await self._get("/search/repositories",
                                {"q": query, "per_page": per_page, "sort": "stars"})

    async def search_issues(self, query: str, per_page: int = 5) -> dict:
        return await self._get("/search/issues", {"q": query, "per_page": per_page})

    # ── self-awareness (ARIA reads her own code) ──────────────────────────

    async def self_structure(self, path: str = "") -> str:
        """Returns a tree view of ARIA's own repo at the given path."""
        data = await self.list_contents(SELF_OWNER, SELF_REPO, path, branch="main")
        if isinstance(data, dict) and "error" in data:
            return f"Error leyendo estructura: {data['error']}"
        if not isinstance(data, list):
            return "Respuesta inesperada"
        lines = [f"📁 /{path or '(raíz)'}"]
        for item in data:
            icon = "📁" if item.get("type") == "dir" else "📄"
            lines.append(f"  {icon} {item.get('name')} ({item.get('type')})")
        return "\n".join(lines)

    async def self_read(self, path: str) -> str:
        """Read a file from ARIA's own source code."""
        result = await self.get_file(SELF_OWNER, SELF_REPO, path, branch="main")
        if "error" in result:
            return f"No pude leer '{path}': {result['error']}"
        content = result["content"]
        lines   = content.split("\n")
        preview = "\n".join(lines[:80])
        suffix  = f"\n... ({len(lines)} líneas en total)" if len(lines) > 80 else ""
        return f"```python\n# {path}\n{preview}{suffix}\n```"

    async def self_commit(self, path: str, new_content: str,
                           commit_message: str, branch: str = "main") -> str:
        """Write an improvement back to ARIA's own code."""
        existing = await self.get_file(SELF_OWNER, SELF_REPO, path, branch=branch)
        sha = existing.get("sha") if "error" not in existing else None
        result = await self.create_or_update_file(
            SELF_OWNER, SELF_REPO, path, new_content,
            commit_message, branch=branch, sha=sha
        )
        if "error" in result:
            return f"Commit fallido: {result['error']}"
        return (f"✅ Commiteé '{path}' en branch '{branch}'\n"
                f"SHA: {result.get('content', {}).get('sha', '?')[:10]}...")

    async def close(self) -> None:
        await self._http.aclose()


# ── singleton ──────────────────────────────────────────────────────────────

_client: Optional[AriaGitHubClient] = None

def get_github_client() -> AriaGitHubClient:
    global _client
    if _client is None:
        _client = AriaGitHubClient()
    return _client


# ── high-level tool dispatcher ─────────────────────────────────────────────

async def github_dispatch(action: str, args: dict) -> str:
    """
    Single entry point called from aria_mind._execute_tool().
    Returns a human-readable string (observation for the LLM).
    """
    gh = get_github_client()

    # -- view / read --
    if action == "view":
        owner  = args.get("owner", SELF_OWNER)
        repo   = args.get("repo", SELF_REPO)
        path   = args.get("path", "")
        sub    = args.get("sub", "list")   # list | read | info

        if sub == "read":
            return await gh.self_read(path) if owner == SELF_OWNER and repo == SELF_REPO \
                else (await gh.get_file(owner, repo, path)).get("content", "Sin contenido")[:3000]

        if sub == "info":
            data = await gh.get_repo(owner, repo)
            if "error" in data:
                return f"Error: {data['error']}"
            return (f"**{data.get('full_name')}**\n"
                    f"{data.get('description','')}\n"
                    f"⭐ {data.get('stargazers_count',0)} | "
                    f"🍴 {data.get('forks_count',0)} | "
                    f"🐛 {data.get('open_issues_count',0)} issues\n"
                    f"Lang: {data.get('language','?')} | "
                    f"Default branch: {data.get('default_branch','main')}")

        # default: list contents
        data = await gh.list_contents(owner, repo, path)
        if isinstance(data, dict) and "error" in data:
            return f"Error: {data['error']}"
        lines = [f"📁 {owner}/{repo}/{path or '(raíz)'}"]
        for item in (data if isinstance(data, list) else []):
            icon = "📁" if item.get("type") == "dir" else "📄"
            size = f" ({item['size']}B)" if item.get("type") == "file" and item.get("size") else ""
            lines.append(f"  {icon} {item['name']}{size}")
        return "\n".join(lines)

    # -- branches --
    elif action == "branches":
        owner = args.get("owner", SELF_OWNER)
        repo  = args.get("repo", SELF_REPO)
        data  = await gh.list_branches(owner, repo)
        if isinstance(data, dict) and "error" in data:
            return f"Error: {data['error']}"
        names = [b.get("name", "") for b in (data if isinstance(data, list) else [])]
        return f"Branches en {owner}/{repo}:\n" + "\n".join(f"  • {n}" for n in names)

    # -- commits --
    elif action == "commits":
        owner  = args.get("owner", SELF_OWNER)
        repo   = args.get("repo", SELF_REPO)
        branch = args.get("branch", "main")
        data   = await gh.list_commits(owner, repo, branch)
        if isinstance(data, dict) and "error" in data:
            return f"Error: {data['error']}"
        lines = [f"Últimos commits en {owner}/{repo}@{branch}:"]
        for c in (data if isinstance(data, list) else [])[:10]:
            sha  = c.get("sha","")[:7]
            msg  = c.get("commit",{}).get("message","").split("\n")[0][:80]
            date = c.get("commit",{}).get("author",{}).get("date","")[:10]
            lines.append(f"  • [{sha}] {msg} ({date})")
        return "\n".join(lines)

    # -- prs --
    elif action == "prs":
        owner = args.get("owner", SELF_OWNER)
        repo  = args.get("repo", SELF_REPO)
        state = args.get("state", "open")
        data  = await gh.list_issues(owner, repo, state=state)
        if isinstance(data, dict) and "error" in data:
            return f"Error: {data['error']}"
        prs = [i for i in (data if isinstance(data, list) else []) if "pull_request" in i]
        if not prs:
            return f"No hay PRs {state}s en {owner}/{repo}"
        lines = [f"PRs {state}s en {owner}/{repo}:"]
        for pr in prs[:8]:
            lines.append(f"  #{pr['number']} {pr['title']} — @{pr['user']['login']}")
        return "\n".join(lines)

    # -- issues --
    elif action == "issues":
        owner = args.get("owner", SELF_OWNER)
        repo  = args.get("repo", SELF_REPO)
        state = args.get("state", "open")
        data  = await gh.list_issues(owner, repo, state=state)
        if isinstance(data, dict) and "error" in data:
            return f"Error: {data['error']}"
        issues = [i for i in (data if isinstance(data, list) else []) if "pull_request" not in i]
        if not issues:
            return f"No hay issues {state}s en {owner}/{repo}"
        lines = [f"Issues {state}s en {owner}/{repo}:"]
        for i in issues[:8]:
            lines.append(f"  #{i['number']} {i['title']} — @{i['user']['login']}")
        return "\n".join(lines)

    # -- write file --
    elif action == "write":
        owner   = args.get("owner", SELF_OWNER)
        repo    = args.get("repo", SELF_REPO)
        path    = args.get("path", "")
        content = args.get("content", "")
        message = args.get("message", "feat: update via ARIA")
        branch  = args.get("branch", "main")
        if not path or not content:
            return "Necesito 'path' y 'content' para escribir en GitHub."
        # fetch existing sha if updating
        existing = await gh.get_file(owner, repo, path, branch=branch)
        sha = existing.get("sha") if "error" not in existing else None
        result = await gh.create_or_update_file(owner, repo, path, content, message, branch, sha)
        if "error" in result:
            return f"No pude escribir '{path}': {result['error']}"
        return (f"✅ Archivo '{path}' {'actualizado' if sha else 'creado'} en {owner}/{repo}@{branch}\n"
                f"Commit: {message}")

    # -- create branch --
    elif action == "create_branch":
        owner      = args.get("owner", SELF_OWNER)
        repo       = args.get("repo", SELF_REPO)
        new_branch = args.get("branch", "")
        from_b     = args.get("from_branch", "main")
        if not new_branch:
            return "Necesito el nombre del nuevo branch."
        result = await gh.create_branch(owner, repo, new_branch, from_b)
        if "error" in result:
            return f"No pude crear branch '{new_branch}': {result['error']}"
        return f"✅ Branch '{new_branch}' creado desde '{from_b}' en {owner}/{repo}"

    # -- create pr --
    elif action == "create_pr":
        owner = args.get("owner", SELF_OWNER)
        repo  = args.get("repo", SELF_REPO)
        title = args.get("title", "")
        body  = args.get("body", "")
        head  = args.get("head", "")
        base  = args.get("base", "main")
        if not title or not head:
            return "Necesito 'title' y 'head' para crear un PR."
        result = await gh.create_pr(owner, repo, title, body, head, base)
        if "error" in result:
            return f"No pude crear PR: {result['error']}"
        return f"✅ PR #{result.get('number')} creado: {result.get('html_url','')}"

    # -- create issue --
    elif action == "create_issue":
        owner  = args.get("owner", SELF_OWNER)
        repo   = args.get("repo", SELF_REPO)
        title  = args.get("title", "")
        body   = args.get("body", "")
        labels = args.get("labels", [])
        if not title:
            return "Necesito un 'title' para crear el issue."
        result = await gh.create_issue(owner, repo, title, body, labels)
        if "error" in result:
            return f"No pude crear issue: {result['error']}"
        return f"✅ Issue #{result.get('number')} creado: {result.get('html_url','')}"

    # -- search --
    elif action == "search":
        query   = args.get("query", "")
        kind    = args.get("type", "repos")  # repos | code | issues
        if not query:
            return "Necesito una query para buscar en GitHub."
        if kind == "code":
            data = await gh.search_code(query)
            items = data.get("items", [])
            lines = [f"Resultados de código para '{query}':"]
            for item in items[:5]:
                lines.append(f"  📄 {item.get('repository',{}).get('full_name')}/{item.get('name')} — {item.get('html_url','')}")
            return "\n".join(lines) if len(lines) > 1 else "Sin resultados."
        elif kind == "issues":
            data = await gh.search_issues(query)
            items = data.get("items", [])
            lines = [f"Issues para '{query}':"]
            for item in items[:5]:
                lines.append(f"  #{item.get('number')} {item.get('title')} — {item.get('html_url','')}")
            return "\n".join(lines) if len(lines) > 1 else "Sin resultados."
        else:
            data = await gh.search_repos(query)
            items = data.get("items", [])
            if isinstance(data, dict) and "error" in data:
                return f"Error: {data['error']}"
            lines = [f"Repos para '{query}':"]
            for item in items[:5]:
                lines.append(f"  ⭐{item.get('stargazers_count',0):,} {item.get('full_name')} — {item.get('description','')[:80]}")
            return "\n".join(lines) if len(lines) > 1 else "Sin resultados."

    # -- self awareness --
    elif action == "self":
        sub  = args.get("sub", "structure")
        path = args.get("path", "")

        if sub == "read":
            return await gh.self_read(path)
        elif sub == "commit":
            new_content = args.get("content", "")
            message     = args.get("message", "refactor: ARIA self-improvement")
            branch      = args.get("branch", "main")
            return await gh.self_commit(path, new_content, message, branch)
        else:
            return await gh.self_structure(path)

    return "Acción GitHub desconocida. Usa: view, branches, commits, prs, issues, write, create_branch, create_pr, create_issue, search, self"
