"""
Platform cache abstraction — provider-agnostic key-value store.

Wraps any backend (Redis/Upstash REST, in-memory dict for tests) behind a
stable async interface. Tests inject a MemoryCache; production uses Redis.

The interface is intentionally minimal: get/set/delete/exists/increment.
Complex ops (RPUSH/LRANGE) are on the underlying client for modules that
need them explicitly.
"""

from __future__ import annotations

import time
from typing import Any


class CacheProvider:
    """Abstract async cache interface."""

    async def get(self, key: str) -> Any | None:
        raise NotImplementedError

    async def set(self, key: str, value: Any, ttl_seconds: int = 3600) -> bool:
        raise NotImplementedError

    async def delete(self, key: str) -> bool:
        raise NotImplementedError

    async def exists(self, key: str) -> bool:
        raise NotImplementedError

    async def increment(self, key: str) -> int:
        raise NotImplementedError


class MemoryCacheProvider(CacheProvider):
    """In-memory cache for testing and local development without Redis."""

    def __init__(self) -> None:
        self._store: dict[str, tuple[Any, float]] = {}  # (value, expire_at)

    async def get(self, key: str) -> Any | None:
        entry = self._store.get(key)
        if entry is None:
            return None
        value, expire_at = entry
        if expire_at and time.time() > expire_at:
            del self._store[key]
            return None
        return value

    async def set(self, key: str, value: Any, ttl_seconds: int = 3600) -> bool:
        expire_at = time.time() + ttl_seconds if ttl_seconds else 0.0
        self._store[key] = (value, expire_at)
        return True

    async def delete(self, key: str) -> bool:
        return bool(self._store.pop(key, None) is not None)

    async def exists(self, key: str) -> bool:
        return await self.get(key) is not None

    async def increment(self, key: str) -> int:
        current = await self.get(key) or 0
        new_val = int(current) + 1
        await self.set(key, new_val)
        return new_val

    def clear(self) -> None:
        self._store.clear()


class RedisCacheProvider(CacheProvider):
    """Production cache backed by Upstash Redis REST API."""

    async def get(self, key: str) -> Any | None:
        from apps.core.memory.redis_client import get_cache

        return await get_cache().get(key)

    async def set(self, key: str, value: Any, ttl_seconds: int = 3600) -> bool:
        from apps.core.memory.redis_client import get_cache

        return await get_cache().set(key, value, ttl_seconds=ttl_seconds)

    async def delete(self, key: str) -> bool:
        from apps.core.memory.redis_client import get_cache

        return await get_cache().delete(key)

    async def exists(self, key: str) -> bool:
        from apps.core.memory.redis_client import get_cache

        return await get_cache().exists(key)

    async def increment(self, key: str) -> int:
        from apps.core.memory.redis_client import get_cache

        return await get_cache().increment(key)


_cache_provider: CacheProvider | None = None


def get_cache_provider() -> CacheProvider:
    global _cache_provider
    if _cache_provider is None:
        _cache_provider = RedisCacheProvider()
    return _cache_provider


def set_cache_provider(provider: CacheProvider) -> None:
    """Inject a test double or alternative backend."""
    global _cache_provider
    _cache_provider = provider
