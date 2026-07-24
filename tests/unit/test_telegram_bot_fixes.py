"""Regression tests for bugs found auditing telegram_bot.py:

1. The "/limpiar" command called mind._clear_history(chat_id) — AriaMind has
   no such method (the real one is _clear_conversation). Silently swallowed
   by a bare except, so the bot told the user "history cleared" when it
   never was.
2. _describe_user_photo() imported and called set_image_context from
   aria_mind — a name that has never existed anywhere in the codebase. This
   raised ImportError on every single photo message, caught by the
   function's own except-and-return-"" — meaning ALL photo handling
   (VQA and image description) was permanently dead code, never reachable.
3. _send_message()/_send_photo() are called by deep_think.py, task_manager.py,
   and orchestrator.py, but only _send()/_send_photo_bytes() existed on this
   class — every one of those callers' notifications silently failed via
   their own except-and-pass.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from apps.core.tools.telegram_bot import AriaTelegramBot

pytestmark = pytest.mark.asyncio


async def test_limpiar_command_calls_the_real_clear_method(monkeypatch):
    monkeypatch.setattr("apps.core.tools.telegram_bot.settings.TELEGRAM_TOKEN", "fake-token")
    bot = AriaTelegramBot()
    mock_mind = AsyncMock()

    with patch(
        "apps.core.cognition.aria_mind.get_aria_mind", return_value=mock_mind
    ), patch.object(bot, "_send_placeholder", AsyncMock(return_value=1)), patch.object(
        bot, "_edit_or_send", AsyncMock()
    ), patch.object(bot, "_is_authorized", return_value=True):
        await bot._handle_message({"text": "/limpiar", "chat": {"id": 1}})

    mock_mind._clear_conversation.assert_awaited_once_with("1")


async def test_describe_user_photo_does_not_crash_on_import():
    bot = AriaTelegramBot()
    with patch.object(bot, "_download_file", AsyncMock(return_value=b"fake image bytes")), patch(
        "apps.core.tools.huggingface_suite.HuggingFaceSuite"
    ) as mock_hf_cls:
        mock_hf_cls.return_value.describe_image = AsyncMock(
            return_value={"success": True, "description": "a cat"}
        )
        result = await bot._describe_user_photo(
            {"photo": [{"file_id": "abc"}], "caption": ""}, "1"
        )

    assert "a cat" in result


async def test_send_message_alias_delegates_to_send():
    bot = AriaTelegramBot()
    with patch.object(bot, "_send", AsyncMock(return_value=True)) as mock_send:
        ok = await bot._send_message(123, "hello")
    assert ok is True
    mock_send.assert_awaited_once_with(123, "hello", already_html=False)


async def test_send_photo_alias_delegates_to_send_photo_bytes_for_bytes():
    bot = AriaTelegramBot()
    with patch.object(bot, "_send_photo_bytes", AsyncMock(return_value=True)) as mock_send:
        ok = await bot._send_photo(123, b"fake bytes", caption="hi")
    assert ok is True
    mock_send.assert_awaited_once_with(123, b"fake bytes", caption="hi")


async def test_send_photo_alias_handles_url_directly(monkeypatch):
    monkeypatch.setattr("apps.core.tools.telegram_bot.settings.TELEGRAM_TOKEN", "fake-token")
    bot = AriaTelegramBot()

    fake_resp = AsyncMock()
    fake_resp.status_code = 200

    async def fake_post(url, json=None, **kwargs):
        assert json["photo"] == "https://example.com/x.png"
        return fake_resp

    with patch.object(bot._http, "post", fake_post):
        ok = await bot._send_photo(123, "https://example.com/x.png")
    assert ok is True
