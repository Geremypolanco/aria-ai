"""Regression test: telegram_bot.py's AriaMind.handle() calls never passed
`email` at all (always defaulting to ""), which meant:

  1. The Telegram owner could never reach any owner-only tool (execute_code,
     computer_use, the Shopify/finance tools, ...) from Telegram, since
     auth.is_owner_email("") is always False.
  2. Telegram got none of the long-term memory (episodic recall +
     user_facts — see apps/core/memory/context_loader.py) that the web
     chat entrypoints (apps/core/main.py) already had.

Fixed via AriaTelegramBot._owner_email(), which resolves the configured
owner identity — but ONLY when TELEGRAM_CHAT_ID is actually set.
_is_authorized() falls back to "allow anyone" when TELEGRAM_CHAT_ID is
unset, so _owner_email() must return "" in that case too — otherwise an
unconfigured, wide-open bot would grant owner-level identity (and thus
owner-only tool access) to any random Telegram user who finds it, which
would be a much worse vulnerability than today's "open but unprivileged"
behavior.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from apps.core.tools.telegram_bot import AriaTelegramBot


def test_owner_email_is_empty_when_telegram_chat_id_not_configured(monkeypatch):
    monkeypatch.setattr("apps.core.tools.telegram_bot.settings.TELEGRAM_CHAT_ID", "")
    monkeypatch.setattr("apps.core.tools.telegram_bot.settings.OWNER_EMAIL", "owner@aria.test")
    assert AriaTelegramBot._owner_email() == ""


def test_owner_email_prefers_settings_owner_email_when_chat_id_configured(monkeypatch):
    monkeypatch.setattr("apps.core.tools.telegram_bot.settings.TELEGRAM_CHAT_ID", "12345")
    monkeypatch.setattr("apps.core.tools.telegram_bot.settings.OWNER_EMAIL", "owner@aria.test")
    assert AriaTelegramBot._owner_email() == "owner@aria.test"


def test_owner_email_falls_back_to_auth_owner_emails(monkeypatch):
    monkeypatch.setattr("apps.core.tools.telegram_bot.settings.TELEGRAM_CHAT_ID", "12345")
    monkeypatch.setattr("apps.core.tools.telegram_bot.settings.OWNER_EMAIL", "")
    result = AriaTelegramBot._owner_email()
    from apps.core import auth

    assert result in auth.owner_emails()
    assert result != ""


@pytest.mark.asyncio
async def test_handle_message_threads_owner_email_and_loads_memory_when_configured(monkeypatch):
    monkeypatch.setattr("apps.core.tools.telegram_bot.settings.TELEGRAM_TOKEN", "fake-token")
    monkeypatch.setattr("apps.core.tools.telegram_bot.settings.TELEGRAM_CHAT_ID", "1")
    monkeypatch.setattr("apps.core.tools.telegram_bot.settings.OWNER_EMAIL", "owner@aria.test")

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
    fake_load_context = AsyncMock(return_value="[remembered: likes concise replies]")
    fake_episodic = AsyncMock()
    fake_episodic.store_conversation = AsyncMock()

    with (
        patch("apps.core.cognition.aria_mind.get_aria_mind", return_value=mock_mind),
        patch("apps.core.memory.context_loader.load_user_context", fake_load_context),
        patch(
            "apps.core.cognition.episodic_memory.get_episodic_memory",
            return_value=fake_episodic,
        ),
        patch.object(bot, "_send_placeholder", AsyncMock(return_value=1)),
        patch.object(bot, "_edit_or_send", AsyncMock()),
        patch.object(bot, "_delete_message", AsyncMock()),
        patch.object(bot, "_send_action", AsyncMock()),
    ):
        await bot._handle_message({"text": "what do you know about me", "chat": {"id": 1}})
        # give the fire-and-forget store_conversation task a chance to run
        import asyncio

        await asyncio.sleep(0)

    fake_load_context.assert_awaited_once_with("owner@aria.test", "what do you know about me")
    mock_mind.handle.assert_awaited_once_with(
        "what do you know about me",
        "1",
        user_context="[remembered: likes concise replies]",
        email="owner@aria.test",
    )
    fake_episodic.store_conversation.assert_awaited_once_with(
        "owner@aria.test", "what do you know about me", "hi there"
    )


@pytest.mark.asyncio
async def test_handle_message_stays_anonymous_when_bot_is_unconfigured_and_open(monkeypatch):
    """The critical security case: TELEGRAM_CHAT_ID unset means the bot is
    open to anyone (see _is_authorized) — this must NOT also grant owner
    identity/memory to whoever that anyone is."""
    monkeypatch.setattr("apps.core.tools.telegram_bot.settings.TELEGRAM_TOKEN", "fake-token")
    monkeypatch.setattr("apps.core.tools.telegram_bot.settings.TELEGRAM_CHAT_ID", "")
    monkeypatch.setattr("apps.core.tools.telegram_bot.settings.OWNER_EMAIL", "owner@aria.test")

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
    fake_load_context = AsyncMock()

    with (
        patch("apps.core.cognition.aria_mind.get_aria_mind", return_value=mock_mind),
        patch("apps.core.memory.context_loader.load_user_context", fake_load_context),
        patch.object(bot, "_send_placeholder", AsyncMock(return_value=1)),
        patch.object(bot, "_edit_or_send", AsyncMock()),
        patch.object(bot, "_delete_message", AsyncMock()),
        patch.object(bot, "_send_action", AsyncMock()),
    ):
        await bot._handle_message({"text": "run execute_code", "chat": {"id": 999}})

    fake_load_context.assert_not_called()
    mock_mind.handle.assert_awaited_once_with(
        "run execute_code", "999", user_context=None, email=""
    )
