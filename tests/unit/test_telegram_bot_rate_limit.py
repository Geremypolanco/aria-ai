"""Regression test: telegram_bot.py had no rate limit at all — unlike the
web chat entrypoints (apps/core/main.py's _rate_ok/_consume_free_quota/cost
ledger checks), a Telegram chat could send unlimited messages, each one
triggering a real AI call. This is a real cost/abuse vector, especially
combined with _is_authorized() intentionally allowing anyone through when
TELEGRAM_CHAT_ID isn't configured yet (a friendlier first-run experience,
kept as-is) — without a rate limit, "wide open until configured" meant
"unlimited free AI spend until configured".

AriaTelegramBot._rate_ok() bounds this via the same AriaCache.check_rate_limit()
primitive user_facts.py's write rate limit uses, and fails OPEN if Redis is
unavailable — this is an abuse guard, not a correctness guarantee.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from apps.core.tools.telegram_bot import AriaTelegramBot

pytestmark = pytest.mark.asyncio


async def test_rate_ok_true_under_the_limit():
    fake_cache = AsyncMock()
    fake_cache.check_rate_limit = AsyncMock(return_value=True)

    with patch("apps.core.memory.redis_client.get_cache", return_value=fake_cache):
        allowed = await AriaTelegramBot._rate_ok("12345")

    assert allowed is True
    fake_cache.check_rate_limit.assert_awaited_once_with("telegram_msg:12345", 20, 60)


async def test_rate_ok_false_once_over_the_limit():
    fake_cache = AsyncMock()
    fake_cache.check_rate_limit = AsyncMock(return_value=False)

    with patch("apps.core.memory.redis_client.get_cache", return_value=fake_cache):
        allowed = await AriaTelegramBot._rate_ok("12345")

    assert allowed is False


async def test_rate_ok_fails_open_when_cache_unavailable():
    with patch("apps.core.memory.redis_client.get_cache", return_value=None):
        allowed = await AriaTelegramBot._rate_ok("12345")

    assert allowed is True


async def test_rate_ok_fails_open_on_unexpected_error():
    with patch("apps.core.memory.redis_client.get_cache", side_effect=RuntimeError("boom")):
        allowed = await AriaTelegramBot._rate_ok("12345")

    assert allowed is True


async def test_handle_message_stops_when_rate_limited(monkeypatch):
    monkeypatch.setattr("apps.core.tools.telegram_bot.settings.TELEGRAM_TOKEN", "fake-token")
    bot = AriaTelegramBot()
    mock_mind = AsyncMock()

    with (
        patch.object(bot, "_is_authorized", return_value=True),
        patch.object(AriaTelegramBot, "_rate_ok", AsyncMock(return_value=False)),
        patch("apps.core.cognition.aria_mind.get_aria_mind", return_value=mock_mind),
    ):
        await bot._handle_message({"text": "hello", "chat": {"id": 1}})

    mock_mind.handle.assert_not_called()


async def test_handle_message_proceeds_when_not_rate_limited(monkeypatch):
    monkeypatch.setattr("apps.core.tools.telegram_bot.settings.TELEGRAM_TOKEN", "fake-token")
    bot = AriaTelegramBot()

    class _Resp:
        text = "hi there"
        caption = ""
        image_bytes = None
        video_bytes = None
        audio_bytes = None
        document_bytes = None
        silent = False

    mock_mind = AsyncMock()
    mock_mind.handle = AsyncMock(return_value=_Resp())

    with (
        patch.object(bot, "_is_authorized", return_value=True),
        patch.object(AriaTelegramBot, "_rate_ok", AsyncMock(return_value=True)),
        patch("apps.core.cognition.aria_mind.get_aria_mind", return_value=mock_mind),
        patch.object(bot, "_send_placeholder", AsyncMock(return_value=1)),
        patch.object(bot, "_edit_or_send", AsyncMock()),
        patch.object(bot, "_delete_message", AsyncMock()),
        patch.object(bot, "_send_action", AsyncMock()),
    ):
        await bot._handle_message({"text": "hello", "chat": {"id": 1}})

    mock_mind.handle.assert_awaited_once()
