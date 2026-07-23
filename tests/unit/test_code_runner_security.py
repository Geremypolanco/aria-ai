"""Regression tests for the two fixes to code_runner.py's execute_code path:

1. The subprocess used to inherit the full server environment
   (env={**os.environ, ...}), so `import os; print(os.environ)` from inside
   "sandboxed" user code leaked every configured secret (API keys,
   SESSION_SECRET, ADMIN_PASSWORD, GITHUB_TOKEN, ...). Now runs with a
   minimal explicit env.
2. execute_code was reachable by any signed-up free account — gated
   owner-only in aria_mind.py (test_aria_mind_github_gate.py covers the
   gating mechanism itself; this file adds execute_code to that coverage).
"""

from __future__ import annotations

import pytest

from apps.core.cognition.aria_mind import AriaMind
from apps.core.tools.code_runner import CodeRunner

pytestmark = pytest.mark.asyncio


async def test_subprocess_does_not_inherit_server_secrets(monkeypatch):
    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_live_should_never_leak")
    monkeypatch.setenv("SESSION_SECRET", "super-secret-signing-key")

    runner = CodeRunner()
    result = await runner.run("import os; print(dict(os.environ))", language="python")

    assert result["success"] is True
    assert "sk_live_should_never_leak" not in result["stdout"]
    assert "super-secret-signing-key" not in result["stdout"]
    assert "STRIPE_SECRET_KEY" not in result["stdout"]


async def test_subprocess_env_is_minimal():
    runner = CodeRunner()
    result = await runner.run("import os; print(sorted(os.environ.keys()))", language="python")
    assert result["success"] is True
    visible = eval(result["stdout"])  # noqa: S307 — trusted fixture output, not user input
    # PWD/SHLVL are set automatically by the bash wrapper that applies real
    # ulimit resource limits before exec'ing the interpreter — harmless,
    # not secrets, not inherited from the server's real environment.
    assert set(visible) <= {"HOME", "LANG", "PATH", "PYTHONDONTWRITEBYTECODE", "PWD", "SHLVL"}


async def test_execute_code_is_owner_only():
    mind = AriaMind()
    obs, media = await mind._execute_tool(
        "execute_code", {"code": "print(1)"}, email="random-user@example.com"
    )
    assert "reservada al dueño" in obs
    assert media == {}
