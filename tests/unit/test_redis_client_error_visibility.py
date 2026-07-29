"""Regression test: AriaCache._cmd() silently swallowed Upstash REST error
responses. Upstash's REST API returns HTTP 200 with {"error": "..."} in the
body for a rejected command (bad auth, wrong arity) rather than a non-2xx
status — the old code's bare `except Exception` never caught that shape at
all, so every such failure was invisible."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from apps.core.memory.redis_client import AriaCache

pytestmark = pytest.mark.asyncio


async def test_cmd_logs_and_returns_none_on_upstash_error(caplog):
    cache = AriaCache()
    fake_response = MagicMock()
    fake_response.json.return_value = {"error": "WRONGPASS invalid credentials"}
    cache._http.post = AsyncMock(return_value=fake_response)

    with caplog.at_level("WARNING", logger="aria.cache"):
        result = await cache._cmd("GET", "some:key")

    assert result is None
    assert any("WRONGPASS" in r.message for r in caplog.records)


async def test_cmd_logs_on_transport_exception(caplog):
    cache = AriaCache()
    cache._http.post = AsyncMock(side_effect=ConnectionError("network unreachable"))

    with caplog.at_level("WARNING", logger="aria.cache"):
        result = await cache._cmd("GET", "some:key")

    assert result is None
    assert any("network unreachable" in r.message for r in caplog.records)


async def test_cmd_returns_result_on_success():
    cache = AriaCache()
    fake_response = MagicMock()
    fake_response.json.return_value = {"result": "PONG"}
    cache._http.post = AsyncMock(return_value=fake_response)

    assert await cache._cmd("PING") == "PONG"


async def test_compare_and_delete_deletes_on_matching_value():
    """The Lua script's DEL branch returns 1 when the token matched and the
    key was removed — the atomic release path a lock holder actually wants."""
    cache = AriaCache()
    fake_response = MagicMock()
    fake_response.json.return_value = {"result": 1}
    cache._http.post = AsyncMock(return_value=fake_response)

    result = await cache.compare_and_delete("some:lock", "expected-token")

    assert result is True
    sent_body = cache._http.post.call_args.kwargs["json"]
    assert sent_body[0] == "EVAL"
    assert sent_body[-2:] == ["some:lock", "expected-token"]


async def test_compare_and_delete_does_not_delete_on_mismatched_value():
    """The script's else-branch returns 0 without deleting when the stored
    value no longer matches — e.g. a different holder's token — which is
    exactly the race a plain get()-then-delete() couldn't close."""
    cache = AriaCache()
    fake_response = MagicMock()
    fake_response.json.return_value = {"result": 0}
    cache._http.post = AsyncMock(return_value=fake_response)

    result = await cache.compare_and_delete("some:lock", "stale-token")

    assert result is False


async def test_compare_and_delete_returns_false_on_upstash_error():
    cache = AriaCache()
    fake_response = MagicMock()
    fake_response.json.return_value = {"error": "script execution disabled"}
    cache._http.post = AsyncMock(return_value=fake_response)

    assert await cache.compare_and_delete("some:lock", "token") is False
