"""Regression test: computer_agent.py (BrowserComputer + ComputerUseAgent) —
a complete Anthropic Computer Use implementation with a real agentic loop and
its own run_mock() test path — had zero live callers.

Wired into aria_mind.py's tool dispatcher as computer_use, owner-only (like
github_write/execute_code): it drives a real, credential-free headless
Chromium via coordinate-based clicks, which is real-world-side-effect
capable and must not be reachable by a non-owner account.

Exercised through AriaMind._execute_tool exactly as a live conversation
would, with BrowserComputer/ComputerUseAgent mocked out so no real browser
or Anthropic API call happens in CI.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from unittest.mock import patch

import pytest

from apps.core.cognition.aria_mind import AriaMind

pytestmark = pytest.mark.asyncio

OWNER_EMAIL = "owner@aria.test"
OTHER_EMAIL = "someone-else@example.com"


@dataclass
class _FakeAgentRun:
    final_text: str = "done"
    steps: list = field(default_factory=list)
    stop_reason: str | None = "end_turn"


class _FakeComputer:
    def __init__(self, *args, **kwargs):
        self.started = False
        self.closed = False

    async def start(self):
        self.started = True

    async def close(self):
        self.closed = True

    async def screenshot_b64(self):
        return "aGVsbG8="  # b"hello"


class _FakeAgent:
    def __init__(self, computer, **kwargs):
        self.computer = computer

    async def run(self, task, max_steps=15):
        return _FakeAgentRun(final_text=f"finished: {task}")


@pytest.fixture(autouse=True)
def _patch_owner_check():
    with patch("apps.core.auth.is_owner_email", side_effect=lambda e: e == OWNER_EMAIL):
        yield


async def test_computer_use_blocked_for_non_owner():
    mind = AriaMind()
    obs, media = await mind._execute_tool(
        "computer_use", {"task": "check a page"}, email=OTHER_EMAIL
    )

    assert media == {}
    assert "owner" in obs.lower()


async def test_computer_use_requires_task():
    mind = AriaMind()
    obs, media = await mind._execute_tool("computer_use", {}, email=OWNER_EMAIL)

    assert media == {}
    assert "task" in obs.lower()


async def test_computer_use_requires_api_key():
    from apps.core.config import settings

    with patch.object(settings, "ANTHROPIC_API_KEY", None):
        mind = AriaMind()
        obs, media = await mind._execute_tool(
            "computer_use", {"task": "check a page"}, email=OWNER_EMAIL
        )

    assert media == {}
    assert "ANTHROPIC_API_KEY" in obs


async def test_computer_use_runs_for_owner_and_returns_screenshot():
    from apps.core.config import settings

    with (
        patch.object(settings, "ANTHROPIC_API_KEY", "fake-key-for-test"),
        patch("apps.core.integrations.computer_agent.BrowserComputer", _FakeComputer),
        patch("apps.core.integrations.computer_agent.ComputerUseAgent", _FakeAgent),
    ):
        mind = AriaMind()
        obs, media = await mind._execute_tool(
            "computer_use",
            {"task": "find the pricing page", "start_url": "https://example.com"},
            email=OWNER_EMAIL,
        )

    assert "finished: find the pricing page" in obs
    assert media.get("image_bytes") == b"hello"
