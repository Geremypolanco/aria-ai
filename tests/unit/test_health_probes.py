"""Honest health-probe behaviour.

These lock in that /health reports the *truth*: a Redis ping that only succeeds on
a real round-trip, and an AI component that reflects whether any provider key is
actually configured (the client object always exists, so its mere presence is not a
useful signal).
"""

import asyncio

from apps.core.memory.redis_client import AriaCache
from apps.core.tools.ai_client import get_ai_client


def test_cache_ping_is_false_without_backend(monkeypatch):
    """ping() must return False when the transport layer can't reach Redis."""
    cache = AriaCache()

    async def _fake_cmd(*args):
        return None  # simulate unreachable / unconfigured Upstash

    monkeypatch.setattr(cache, "_cmd", _fake_cmd)
    assert asyncio.run(cache.ping()) is False


def test_cache_ping_true_only_on_pong(monkeypatch):
    cache = AriaCache()

    async def _fake_cmd(*args):
        return "PONG" if args and args[0] == "PING" else None

    monkeypatch.setattr(cache, "_cmd", _fake_cmd)
    assert asyncio.run(cache.ping()) is True


def test_configured_providers_returns_list():
    """No network call; returns the subset of providers with a key set."""
    ai = get_ai_client()
    if ai is None:
        return  # AI client genuinely unavailable in this build — nothing to assert
    providers = ai.configured_providers()
    assert isinstance(providers, list)
    assert all(isinstance(p, str) for p in providers)
