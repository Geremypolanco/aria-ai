"""
github_tools.py — Integración con la API de GitHub via PyGithub.

Permite a ARIA leer repositorios, issues, PRs, commits, releases y workflows.
Requiere: GITHUB_TOKEN en secrets de Fly.io.
PyGithub ya está en requirements.txt (PyGithub==2.4.0).
"""

from __future__ import annotations

import logging
import os
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


def _ok(data: Any, **extra) -> Dict:
    return {"success": True, "data": data, **extra}


def _err(msg: str) -> Dict:
    return {"success": False, "error": msg}


class GitHubTools:
    """Acceso a GitHub para ARIA: repos, issues, PRs, commits, releases."""

    def __init__(self):
        from apps.core.config import settings
        self._token = getattr(settings, "GITHUB_TOKEN", None) or os.getenv("GITHUB_TOKEN")
        self._username = getattr(settings, "GITHUB_USERNAME", "Geremypolanco")
        self._gh = None

    def is_configured(self) -> bool:
        return bool(self._token)

    def _get_gh(self):
        if self._gh is None:
            from github import Github
            self._gh = Github(self._token)
        return self._gh

    def _get_repo(self, repo_name: str):
        gh = self._get_gh()
        if "/" not in repo_name:
            repo_name = f"{self._username}/{repo_name}"
        return gh.get_repo(repo_name)

    # ── Repositorios ──────────────────────────────────────────────────────────

    def list_repos(self, limit: int = 20) -> Dict:
        if not self.is_configured():
            return _err("GITHUB_TOKEN no configurado")
        try:
            gh = self._get_gh()
            user = gh.get_user(self._username)
            repos = []
            for r in user.get_repos()[:limit]:
                repos.append({
                    "name": r.name,
                    "full_name": r.full_name,
                    "description": r.description,
                    "private": r.private,
                    "language": r.language,
                    "stars": r.stargazers_count,
                    "forks": r.forks_count,
                    "open_issues": r.open_issues_count,
                    "updated": str(r.updated_at)[:10],
                    "url": r.html_url,
                })
            return _ok(repos, count=len(repos))
        except Exception as e:
            return _err(str(e))

    def get_repo_summary(self, repo_name: str) -> Dict:
        if not self.is_configured():
            return _err("GITHUB_TOKEN no configurado")
        try:
            r = self._get_repo(repo_name)
            issues = [{"number": i.number, "title": i.title} for i in r.get_issues(state="open")[:5]]
            prs = [{"number": p.number, "title": p.title, "head": p.head.ref, "base": p.base.ref}
                   for p in r.get_pulls(state="open")[:5]]
            commits = [{"sha": c.sha[:7], "message": c.commit.message.split("\n")[0], "author": c.commit.author.name,
                        "date": str(c.commit.author.date)[:10]}
                       for c in r.get_commits()[:5]]
            return {
                "success": True,
                "repo": {
                    "full_name": r.full_name, "description": r.description,
                    "private": r.private, "language": r.language,
                    "stars": r.stargazers_count, "forks": r.forks_count,
                    "open_issues": r.open_issues_count, "url": r.html_url,
                },
                "open_issues": issues,
                "open_prs": prs,
                "recent_commits": commits,
            }
        except Exception as e:
            return _err(str(e))

    # ── Issues ────────────────────────────────────────────────────────────────

    def list_issues(self, repo_name: str, state: str = "open", limit: int = 10) -> Dict:
        if not self.is_configured():
            return _err("GITHUB_TOKEN no configurado")
        try:
            r = self._get_repo(repo_name)
            issues = []
            for i in r.get_issues(state=state)[:limit]:
                issues.append({
                    "number": i.number, "title": i.title, "state": i.state,
                    "labels": [lb.name for lb in i.labels],
                    "assignees": [a.login for a in i.assignees],
                    "created": str(i.created_at)[:10],
                    "url": i.html_url,
                })
            return _ok(issues, count=len(issues))
        except Exception as e:
            return _err(str(e))

    # ── Pull Requests ─────────────────────────────────────────────────────────

    def list_pull_requests(self, repo_name: str, state: str = "open", limit: int = 10) -> Dict:
        if not self.is_configured():
            return _err("GITHUB_TOKEN no configurado")
        try:
            r = self._get_repo(repo_name)
            prs = []
            for p in r.get_pulls(state=state)[:limit]:
                prs.append({
                    "number": p.number, "title": p.title, "state": p.state,
                    "head": p.head.ref, "base": p.base.ref,
                    "author": p.user.login, "created": str(p.created_at)[:10],
                    "url": p.html_url, "mergeable": p.mergeable,
                })
            return _ok(prs, count=len(prs))
        except Exception as e:
            return _err(str(e))

    # ── Commits ───────────────────────────────────────────────────────────────

    def list_commits(self, repo_name: str, limit: int = 10, branch: Optional[str] = None) -> Dict:
        if not self.is_configured():
            return _err("GITHUB_TOKEN no configurado")
        try:
            r = self._get_repo(repo_name)
            kwargs = {"sha": branch} if branch else {}
            commits = []
            for c in r.get_commits(**kwargs)[:limit]:
                commits.append({
                    "sha": c.sha[:7], "message": c.commit.message.split("\n")[0],
                    "author": c.commit.author.name, "date": str(c.commit.author.date)[:10],
                    "url": c.html_url,
                })
            return _ok(commits, count=len(commits))
        except Exception as e:
            return _err(str(e))

    # ── Releases ──────────────────────────────────────────────────────────────

    def list_releases(self, repo_name: str, limit: int = 5) -> Dict:
        if not self.is_configured():
            return _err("GITHUB_TOKEN no configurado")
        try:
            r = self._get_repo(repo_name)
            releases = []
            for rel in r.get_releases()[:limit]:
                releases.append({
                    "tag": rel.tag_name, "name": rel.title,
                    "draft": rel.draft, "prerelease": rel.prerelease,
                    "created": str(rel.created_at)[:10],
                    "url": rel.html_url,
                })
            return _ok(releases, count=len(releases))
        except Exception as e:
            return _err(str(e))

    # ── Archivos ──────────────────────────────────────────────────────────────

    def list_files(self, repo_name: str, path: str = "") -> Dict:
        if not self.is_configured():
            return _err("GITHUB_TOKEN no configurado")
        try:
            r = self._get_repo(repo_name)
            contents = r.get_contents(path)
            if not isinstance(contents, list):
                contents = [contents]
            items = [{"name": c.name, "path": c.path, "type": c.type,
                      "size": c.size if c.type == "file" else None} for c in contents]
            return _ok(items, count=len(items))
        except Exception as e:
            return _err(str(e))

    # ── Workflows (GitHub Actions) ────────────────────────────────────────────

    def list_workflows(self, repo_name: str) -> Dict:
        if not self.is_configured():
            return _err("GITHUB_TOKEN no configurado")
        try:
            r = self._get_repo(repo_name)
            wfs = [{"id": w.id, "name": w.name, "state": w.state, "path": w.path}
                   for w in r.get_workflows()]
            return _ok(wfs, count=len(wfs))
        except Exception as e:
            return _err(str(e))

    def get_workflow_runs(self, repo_name: str, limit: int = 5) -> Dict:
        if not self.is_configured():
            return _err("GITHUB_TOKEN no configurado")
        try:
            r = self._get_repo(repo_name)
            runs = []
            for run in r.get_workflow_runs()[:limit]:
                runs.append({
                    "id": run.id, "name": run.name, "status": run.status,
                    "conclusion": run.conclusion, "branch": run.head_branch,
                    "created_at": str(run.created_at)[:16],
                    "url": run.html_url,
                })
            return _ok(runs, count=len(runs))
        except Exception as e:
            return _err(str(e))


_instance: Optional[GitHubTools] = None


def get_github_tools() -> GitHubTools:
    global _instance
    if _instance is None:
        _instance = GitHubTools()
    return _instance
