"""Regression tests for bugs found while auditing self_improvement.py and its
two callers:

1. SelfImprovementEngine had no push_file()/_push_file() method at all — only
   push_improvement() (which requires a pre-fetched original_sha). Both
   developer_agent.py's _push_to_github() (calling engine.push_file(path=...,
   message=...)) and evolution_agent.py's implement_feature_code() (calling
   engine._push_file(file_path=..., commit_message=...)) referenced a
   nonexistent method — guaranteed AttributeError, silently swallowed by the
   caller's own except Exception, so neither GitHub-push feature has ever
   actually pushed anything.
2. Fixing that crash would have activated a live vulnerability: the
   deploy+github_path push path in DeveloperAgent._execute() had no owner
   check, unlike the code-execution path right above it in the same method.
   run_business_agent is not in _OWNER_ONLY_TOOLS and passes `context`
   straight from LLM/user tool-call args, so any signed-up user could have
   asked ARIA to push generated content to the live repo (and trigger an
   automatic Fly.io deploy) via context={"deploy": true, "github_path": ...}.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from apps.core.agents.business.developer_agent import DeveloperAgent
from apps.core.tools.self_improvement import SelfImprovementEngine

pytestmark = pytest.mark.asyncio


async def test_push_file_method_exists_and_creates_new_file(monkeypatch):
    monkeypatch.setattr(SelfImprovementEngine, "_last_push_time", 0.0)
    engine = SelfImprovementEngine()
    engine._token = "fake-token"

    async def fake_read_file(path):
        return {"success": False, "error": "404"}

    put_response = MagicMock()
    put_response.status_code = 201
    put_response.json.return_value = {"commit": {"sha": "abcdef1234567890"}}

    with patch.object(engine, "read_file", fake_read_file), patch.object(
        engine._http, "put", AsyncMock(return_value=put_response)
    ):
        result = await engine.push_file(
            file_path="apps/core/tools/new_feature.py",
            content="print('hi')",
            commit_message="feat: new feature",
        )
    assert result["success"] is True
    assert result["commit_sha"] == "abcdef12"


async def test_push_file_refuses_protected_files():
    engine = SelfImprovementEngine()
    engine._token = "fake-token"
    SelfImprovementEngine._last_push_time = 0.0
    result = await engine.push_file(
        file_path="apps/core/main.py", content="x", commit_message="msg"
    )
    assert result["success"] is False
    assert "protegido" in result["error"]


async def test_developer_agent_push_to_github_calls_real_method():
    """Would previously raise AttributeError: 'SelfImprovementEngine' object
    has no attribute 'push_file', caught and returned as a generic error."""
    agent = DeveloperAgent()
    with patch(
        "apps.core.tools.self_improvement.SelfImprovementEngine.push_file",
        AsyncMock(return_value={"success": True, "commit_sha": "abc123"}),
    ) as mock_push:
        result = await agent._push_to_github("some/file.py", "content", "message")
    assert result["success"] is True
    mock_push.assert_awaited_once()


async def test_deploy_skipped_for_non_owner():
    agent = DeveloperAgent()
    with patch.object(DeveloperAgent, "_design_solution", AsyncMock(return_value="design")), \
         patch.object(DeveloperAgent, "_generate_code", AsyncMock(return_value="print('hi')")), \
         patch.object(DeveloperAgent, "_generate_tests", AsyncMock(return_value="")), \
         patch.object(DeveloperAgent, "_push_to_github", AsyncMock(return_value={"success": True})) as mock_push:
        result = await agent.run(
            {
                "mission": "do something",
                "is_owner": False,
                "auto_run": False,
                "deploy": True,
                "github_path": "apps/core/tools/some_file.py",
            }
        )
    assert result.get("deploy_skipped")
    assert "github" not in result
    mock_push.assert_not_awaited()


async def test_deploy_runs_for_owner():
    agent = DeveloperAgent()
    with patch.object(DeveloperAgent, "_design_solution", AsyncMock(return_value="design")), \
         patch.object(DeveloperAgent, "_generate_code", AsyncMock(return_value="print('hi')")), \
         patch.object(DeveloperAgent, "_generate_tests", AsyncMock(return_value="")), \
         patch.object(
             DeveloperAgent, "_push_to_github", AsyncMock(return_value={"success": True, "commit_sha": "abc"})
         ) as mock_push:
        result = await agent.run(
            {
                "mission": "do something",
                "is_owner": True,
                "auto_run": False,
                "deploy": True,
                "github_path": "apps/core/tools/some_file.py",
            }
        )
    assert result.get("github", {}).get("success") is True
    mock_push.assert_awaited_once()
