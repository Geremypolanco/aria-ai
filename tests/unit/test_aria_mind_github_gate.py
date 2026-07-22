"""Regression test for the most severe finding in this audit: github_write /
github_pr / github_issues / github_self (which can commit to ARIA's own
production repo via sub="commit") had zero authorization check — any
signed-up free account could direct ARIA to write to any GitHub repo the
configured token could reach. Now owner-only."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from apps.core.cognition.aria_mind import AriaMind

pytestmark = pytest.mark.asyncio


@pytest.mark.parametrize("tool", ["github_write", "github_pr", "github_issues", "github_self"])
async def test_github_write_tools_reject_non_owner(tool, monkeypatch):
    monkeypatch.setattr("apps.core.config.settings.OWNER_EMAIL", "owner@example.com")
    mind = AriaMind()
    obs, media = await mind._execute_tool(tool, {}, email="random-user@example.com")
    assert "reservada al dueño" in obs
    assert media == {}


@pytest.mark.parametrize("tool", ["github_write", "github_pr", "github_issues", "github_self"])
async def test_github_write_tools_allow_owner(tool, monkeypatch):
    monkeypatch.setattr("apps.core.config.settings.OWNER_EMAIL", "owner@example.com")
    dispatched = {}

    async def fake_dispatch(action, args):
        dispatched["action"] = action
        return "ok"

    with patch("apps.core.tools.github_client.github_dispatch", fake_dispatch):
        mind = AriaMind()
        obs, media = await mind._execute_tool(tool, {}, email="owner@example.com")
    assert obs == "ok"
    assert "action" in dispatched  # actually reached github_dispatch


async def test_github_view_and_search_remain_open_read_only(monkeypatch):
    """Read-only GitHub tools are intentionally not gated — only the
    write-capable ones are."""
    monkeypatch.setattr("apps.core.config.settings.OWNER_EMAIL", "owner@example.com")

    async def fake_dispatch(action, args):
        return "read result"

    with patch("apps.core.tools.github_client.github_dispatch", fake_dispatch):
        mind = AriaMind()
        obs, _ = await mind._execute_tool("github_view", {}, email="random-user@example.com")
    assert obs == "read result"


async def test_handle_threads_email_through_to_the_gate(monkeypatch):
    """End-to-end: handle(..., email=...) must actually reach the gate, not
    just the internal _execute_tool signature."""
    monkeypatch.setattr("apps.core.config.settings.OWNER_EMAIL", "owner@example.com")

    async def fake_reason(*a, **k):
        return {"tool": "github_self", "tool_args": {"sub": "commit"}, "reply": ""}

    mind = AriaMind()
    with patch.object(mind, "_reason", fake_reason), patch.object(
        mind, "_load_history", AsyncMock(return_value=[])
    ), patch.object(mind, "_load_state", AsyncMock(return_value={})), patch.object(
        mind, "_load_goals", AsyncMock(return_value=[])
    ), patch.object(mind, "_load_learned", AsyncMock(return_value=[])), patch.object(
        mind, "_store_interaction", AsyncMock()
    ), patch.object(mind, "_evolve_state", AsyncMock()), patch.object(
        mind, "_record_exec", AsyncMock()
    ):
        resp = await mind.handle("mejora tu propio código", "chat-1", email="random-user@example.com")

    assert resp.caption is not None and "reservada al dueño" in resp.caption
