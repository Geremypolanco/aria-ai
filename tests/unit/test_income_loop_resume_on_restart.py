"""Regression/feature test: the 24/7 IncomeLoop (apps/core/tools/income_loop.py)
only ever starts when the owner asks ARIA to in chat (start_income_loop), and
lives only as a bare asyncio.create_task with no supervisor — self._running
is in-process memory only. Every restart (including the routine ones
deploy.yml triggers on every merge to main) silently stops the loop with no
automatic way for the owner to notice short of asking income_loop_status.
This is a direct, verified cause of "why is there no traffic": the one
mechanism that autonomously publishes content/SEO/social activity can be
dead for hours or days after any deploy, with nothing surfacing that fact.

start() now persists a "should be running" flag to Redis, and
resume_if_previously_running() (called once from main.py's lifespan on
boot) checks it and auto-resumes the loop if it was running before the
restart — so a deploy no longer silently halts autonomous activity.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from apps.core.tools.income_loop import _SHOULD_RUN_KEY, IncomeLoop

pytestmark = pytest.mark.asyncio


def _bare_loop() -> IncomeLoop:
    """Bypass __init__'s real ThompsonBandit construction; stub out the
    parts of start() unrelated to the should-run flag under test."""
    loop = IncomeLoop.__new__(IncomeLoop)
    loop._running = False
    loop._task = None
    loop._bandit = MagicMock()
    loop._bandit.load = AsyncMock()
    loop._run_forever = AsyncMock()
    loop._notify_startup = AsyncMock()
    return loop


async def test_start_persists_should_run_flag():
    loop = _bare_loop()
    fake_cache = AsyncMock()

    with patch("apps.core.memory.redis_client.get_cache", return_value=fake_cache):
        await loop.start()

    fake_cache.set.assert_awaited_once_with(_SHOULD_RUN_KEY, "1")
    assert loop.is_running


async def test_start_does_not_raise_when_cache_unavailable():
    loop = _bare_loop()

    with patch("apps.core.memory.redis_client.get_cache", return_value=None):
        await loop.start()  # must not raise

    assert loop.is_running


async def test_start_does_not_raise_when_cache_set_fails():
    loop = _bare_loop()
    fake_cache = AsyncMock()
    fake_cache.set = AsyncMock(side_effect=RuntimeError("redis down"))

    with patch("apps.core.memory.redis_client.get_cache", return_value=fake_cache):
        await loop.start()  # must not raise — a broken flag-persist must never block starting

    assert loop.is_running


async def test_resume_starts_the_loop_when_flag_was_set():
    loop = _bare_loop()
    fake_cache = AsyncMock()
    fake_cache.get = AsyncMock(return_value="1")

    with patch("apps.core.memory.redis_client.get_cache", return_value=fake_cache):
        await loop.resume_if_previously_running()

    fake_cache.get.assert_awaited_once_with(_SHOULD_RUN_KEY)
    assert loop.is_running


async def test_resume_does_nothing_when_flag_was_never_set():
    loop = _bare_loop()
    fake_cache = AsyncMock()
    fake_cache.get = AsyncMock(return_value=None)

    with patch("apps.core.memory.redis_client.get_cache", return_value=fake_cache):
        await loop.resume_if_previously_running()

    assert not loop.is_running


async def test_resume_does_not_raise_when_cache_unavailable():
    loop = _bare_loop()

    with patch("apps.core.memory.redis_client.get_cache", return_value=None):
        await loop.resume_if_previously_running()  # must not raise

    assert not loop.is_running


async def test_resume_does_not_raise_when_cache_get_fails():
    loop = _bare_loop()
    fake_cache = AsyncMock()
    fake_cache.get = AsyncMock(side_effect=RuntimeError("redis down"))

    with patch("apps.core.memory.redis_client.get_cache", return_value=fake_cache):
        await loop.resume_if_previously_running()  # must not raise

    assert not loop.is_running
