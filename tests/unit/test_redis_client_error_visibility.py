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
