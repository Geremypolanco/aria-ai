"""
ARIA AI — pytest fixtures and configuration.

Design principles:
  - All external services (Redis, Supabase, AI providers) are mocked by default.
  - Tests NEVER make real network calls.
  - Each fixture is documented with what it provides and what it replaces.
  - Async tests use pytest-asyncio with asyncio_mode="auto".
"""
from __future__ import annotations

import asyncio
import json
import os
from typing import Any, AsyncGenerator, Generator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio

# ── Environment isolation ─────────────────────────────────────────────────

os.environ.setdefault("ENVIRONMENT", "test")
os.environ.setdefault("SUPABASE_URL", "https://test.supabase.co")
os.environ.setdefault("SUPABASE_KEY", "test-key-xxxxxxxx")
os.environ.setdefault("UPSTASH_REDIS_REST_URL", "https://test-redis.upstash.io")
os.environ.setdefault("UPSTASH_REDIS_REST_TOKEN", "test-token")
os.environ.setdefault("HF_TOKEN", "hf_test_token")


# ── Event loop ────────────────────────────────────────────────────────────

@pytest.fixture(scope="session")
def event_loop_policy():
    return asyncio.DefaultEventLoopPolicy()


# ── Redis mock ────────────────────────────────────────────────────────────

class MockRedisClient:
    """
    In-memory Redis mock that implements the subset of commands used by ARIA.

    Supported: GET, SET, DEL, INCR, RPUSH, LPOP, LRANGE, LTRIM, EXISTS, EXPIRE
    """

    def __init__(self) -> None:
        self._store: dict[str, Any] = {}
        self._lists: dict[str, list] = {}

    async def get(self, key: str) -> Any:
        return self._store.get(key)

    async def set(self, key: str, value: Any, ttl_seconds: int = 3600) -> bool:
        self._store[key] = value
        return True

    async def delete(self, *keys: str) -> int:
        count = 0
        for key in keys:
            if key in self._store:
                del self._store[key]
                count += 1
            if key in self._lists:
                del self._lists[key]
                count += 1
        return count

    async def incr(self, key: str) -> int:
        current = int(self._store.get(key, 0))
        self._store[key] = current + 1
        return current + 1

    async def rpush(self, key: str, *values: Any) -> int:
        if key not in self._lists:
            self._lists[key] = []
        for v in values:
            self._lists[key].append(v)
        return len(self._lists[key])

    def lrange(self, key: str, start: int, end: int) -> list:
        lst = self._lists.get(key, [])
        if end == -1:
            return lst[start:]
        return lst[start:end + 1]

    async def ltrim(self, key: str, start: int, end: int) -> bool:
        if key in self._lists:
            if end == -1:
                self._lists[key] = self._lists[key][start:]
            else:
                self._lists[key] = self._lists[key][start:end + 1]
        return True

    async def acquire_lock(self, name: str, ttl_seconds: int = 300) -> bool:
        lock_key = f"lock:{name}"
        if await self.get(lock_key):
            return False
        await self.set(lock_key, "1", ttl_seconds)
        return True

    async def release_lock(self, name: str) -> None:
        await self.delete(f"lock:{name}")

    async def set_agent_heartbeat(self, agent_name: str) -> None:
        await self.set(f"agent:{agent_name}:heartbeat", "ok", ttl_seconds=300)

    async def get_agent_heartbeat(self, agent_name: str) -> Any:
        return await self.get(f"agent:{agent_name}:heartbeat")


@pytest.fixture
def mock_redis() -> MockRedisClient:
    """Provides an in-memory Redis mock pre-populated with empty state."""
    return MockRedisClient()


@pytest.fixture
def mock_redis_patched(mock_redis: MockRedisClient):
    """Patches get_cache() globally to return the in-memory mock."""
    with patch("apps.core.memory.redis_client.get_cache", return_value=mock_redis):
        yield mock_redis


# ── AI Client mock ────────────────────────────────────────────────────────

@pytest.fixture
def mock_ai_response():
    """Factory for creating mock AIResponse objects."""
    def _factory(
        content: str = "Mock AI response",
        success: bool = True,
        provider: str = "mock",
        model: str = "mock-model",
        tokens: int = 100,
    ):
        mock = MagicMock()
        mock.content = content
        mock.success = success
        mock.provider = provider
        mock.model = model
        mock.tokens_used = tokens
        mock.error = None if success else "Mock error"
        return mock
    return _factory


@pytest.fixture
def mock_ai_client(mock_ai_response):
    """
    Patches get_ai_client() to return a mock that never makes real LLM calls.

    Default behavior: returns a canned "Mock AI response".
    Override in individual tests via mock_ai.complete.return_value = ...
    """
    mock = AsyncMock()
    mock.complete = AsyncMock(return_value=mock_ai_response())
    mock.complete_json = AsyncMock(return_value={
        "thought": "Mock reasoning",
        "tool": "none",
        "tool_args": {},
        "reply": "Mock reply",
    })
    mock.stream_complete = AsyncMock(return_value=iter(["Mock", " ", "stream"]))
    mock.get_health_summary = MagicMock(return_value={
        "huggingface": {"available": True, "success_rate_pct": 100.0},
    })

    with patch("apps.core.tools.ai_client.get_ai_client", return_value=mock):
        yield mock


# ── FastAPI test client ───────────────────────────────────────────────────

@pytest.fixture
def app():
    """Return the FastAPI application instance without running startup events."""
    from fastapi.testclient import TestClient

    # Patch lifespan to be a no-op so we don't start real background tasks
    with patch("apps.core.main.lifespan") as _mock_lifespan:
        _mock_lifespan.return_value.__aenter__ = AsyncMock(return_value=None)
        _mock_lifespan.return_value.__aexit__ = AsyncMock(return_value=False)

        from apps.core.main import app as _app
        return _app


@pytest.fixture
def client(app):
    """HTTP test client for the ARIA FastAPI application."""
    from fastapi.testclient import TestClient
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


# ── Supabase mock ─────────────────────────────────────────────────────────

@pytest.fixture
def mock_supabase():
    """Patches Supabase client to record calls without making real DB operations."""
    mock = MagicMock()
    mock.table.return_value.insert.return_value.execute.return_value = {"data": [], "error": None}
    mock.table.return_value.select.return_value.execute.return_value = {"data": [], "error": None}
    mock.table.return_value.update.return_value.eq.return_value.execute.return_value = {"data": [], "error": None}

    with patch("apps.core.memory.supabase_client.get_db", return_value=mock):
        yield mock


# ── Telegram mock ─────────────────────────────────────────────────────────

@pytest.fixture
def mock_telegram():
    """Patches send_telegram to capture messages without real Telegram API calls."""
    sent: list[str] = []

    async def _capture(message: str) -> bool:
        sent.append(message)
        return True

    with patch("apps.core.main.send_telegram", side_effect=_capture):
        yield sent


# ── Metrics isolation ─────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def reset_metrics():
    """Reset AriaMetrics singleton state between tests."""
    from apps.core.observability.metrics import AriaMetrics
    AriaMetrics._instance = None
    yield
    AriaMetrics._instance = None
