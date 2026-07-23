"""
code_sandbox.py — Client for a self-hosted Piston code-execution instance.

This lets ARIA (or a user, via the Artifacts panel's "Run" button) actually
execute code and see real stdout/stderr/exit codes, instead of only ever
producing code as text nobody has run.

Why Piston, and why self-hosted: Piston (github.com/engineer-man/piston) is
the well-established open-source engine used by most "run this code" Discord
bots and similar tools — sandboxed via isolated per-language containers with
resource/time limits on ITS OWN infrastructure. As of writing, Piston's public
API requires manual, non-commercial-only authorization from its maintainer;
ARIA is a paid product, so it doesn't qualify. Self-hosting (see
infra/piston/) is therefore the only available path, and it has a genuine
safety upside for us specifically: submitted code never runs inside ARIA's
own container — it's shipped over HTTP to a separate sandboxed instance,
same arrangement as the Zapier/Activepieces MCP integrations. If
PISTON_API_URL isn't set, execution is simply unavailable (never silently
faked as succeeding).
"""

from __future__ import annotations

import time
from typing import Any

import httpx

from apps.core.config import settings

_RUNTIME_CACHE_TTL = 300.0  # runtimes rarely change; avoid a round trip per call


class PistonSandbox:
    def __init__(self, base_url: str | None = None, timeout: float = 20.0) -> None:
        self.base_url = (base_url or getattr(settings, "PISTON_API_URL", None) or "").rstrip("/")
        self.timeout = timeout
        self._runtimes: list[dict[str, Any]] | None = None
        self._runtimes_at = 0.0

    @property
    def configured(self) -> bool:
        return bool(self.base_url)

    async def list_runtimes(self) -> list[dict[str, Any]]:
        """Languages/versions/aliases this instance actually supports — never
        hardcoded, since a self-hosted instance can install a different set."""
        if not self.configured:
            return []
        now = time.monotonic()
        if self._runtimes is not None and (now - self._runtimes_at) < _RUNTIME_CACHE_TTL:
            return self._runtimes
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.get(f"{self.base_url}/api/v2/runtimes")
            resp.raise_for_status()
            self._runtimes = resp.json()
            self._runtimes_at = now
            return self._runtimes

    async def _resolve(self, language: str) -> tuple[str, str] | None:
        """Match a user-given name ("js", "py3", "node") against the instance's
        real language/alias list. Returns (language, version) or None."""
        wanted = language.strip().lower()
        for rt in await self.list_runtimes():
            names = {rt.get("language", "").lower(), *[a.lower() for a in rt.get("aliases", [])]}
            if wanted in names:
                return rt["language"], rt["version"]
        return None

    async def execute(
        self,
        language: str,
        code: str,
        stdin: str = "",
        args: list[str] | None = None,
        run_timeout_ms: int = 10000,
    ) -> dict[str, Any]:
        """Run code on the sandboxed instance. Always returns a normalized dict:
        {"success": bool, "stdout": str, "stderr": str, "exit_code": int|None,
        "error": str|None} — never raises for ordinary failures (bad code,
        unsupported language, unreachable instance)."""
        if not self.configured:
            return {
                "success": False,
                "stdout": "",
                "stderr": "",
                "exit_code": None,
                "error": "PISTON_API_URL not configured — no code sandbox is available. "
                "See infra/piston/README.md to self-host one.",
            }

        resolved = await self._resolve(language)
        if not resolved:
            return {
                "success": False,
                "stdout": "",
                "stderr": "",
                "exit_code": None,
                "error": f"Language '{language}' isn't installed on this sandbox instance.",
            }
        lang_name, version = resolved

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.post(
                    f"{self.base_url}/api/v2/execute",
                    json={
                        "language": lang_name,
                        "version": version,
                        "files": [{"content": code}],
                        "stdin": stdin,
                        "args": args or [],
                        "run_timeout": run_timeout_ms,
                    },
                )
                resp.raise_for_status()
                data = resp.json()
        except Exception as exc:  # noqa: BLE001 - surface transport errors as data
            return {
                "success": False,
                "stdout": "",
                "stderr": "",
                "exit_code": None,
                "error": f"Sandbox unreachable: {exc}",
            }

        run = data.get("run") or {}
        compile_ = data.get("compile")
        if compile_ and compile_.get("code") not in (0, None):
            return {
                "success": False,
                "stdout": compile_.get("stdout", ""),
                "stderr": compile_.get("stderr", ""),
                "exit_code": compile_.get("code"),
                "error": "Compilation failed.",
            }
        return {
            "success": run.get("code") == 0,
            "stdout": run.get("stdout", ""),
            "stderr": run.get("stderr", ""),
            "exit_code": run.get("code"),
            "error": None,
        }


_sandbox: PistonSandbox | None = None


def get_code_sandbox() -> PistonSandbox:
    global _sandbox
    if _sandbox is None:
        _sandbox = PistonSandbox()
    return _sandbox
