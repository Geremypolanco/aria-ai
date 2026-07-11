"""
rate_limiter.py — Smart outbound rate limiting (token bucket).

A central dispatcher every outbound 3rd-party call (Anthropic, OpenAI, …) passes
through. It uses a **token-bucket** so bursts up to `capacity` are allowed and
the sustained rate never exceeds `refill_per_sec`. Excess calls are *paced*
(awaited) rather than rejected — so we respect provider quotas transparently
instead of throwing overflow errors.

Two backends:
- `TokenBucket`       — in-process (per-worker), deterministic + testable.
- `RedisTokenBucket`  — distributed across workers via an atomic Lua script.

`clock` and `sleep` are injectable so tests run instantly.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable

logger = logging.getLogger("aria.rate_limiter")

# Per-provider (refill tokens/sec, bucket capacity). Tune to contracted quotas.
PROVIDER_LIMITS: dict[str, tuple[float, int]] = {
    "anthropic": (8.0, 16),
    "openai": (8.0, 16),
    "groq": (25.0, 40),
    "huggingface": (5.0, 10),
    "default": (10.0, 20),
}


class TokenBucket:
    """Classic token bucket. `acquire()` paces callers instead of failing."""

    def __init__(
        self,
        refill_per_sec: float,
        capacity: int,
        *,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ):
        self.rate = float(refill_per_sec)
        self.capacity = float(capacity)
        self._tokens = float(capacity)
        self._clock = clock
        self._sleep = sleep
        self._last = clock()
        self._lock = asyncio.Lock()

    def _refill(self) -> None:
        now = self._clock()
        elapsed = max(0.0, now - self._last)
        self._tokens = min(self.capacity, self._tokens + elapsed * self.rate)
        self._last = now

    def try_acquire(self, tokens: float = 1.0) -> bool:
        """Non-blocking: consume if available, else False."""
        self._refill()
        if self._tokens >= tokens:
            self._tokens -= tokens
            return True
        return False

    async def acquire(self, tokens: float = 1.0) -> float:
        """Block (paced) until `tokens` are available. Returns seconds waited."""
        waited = 0.0
        async with self._lock:
            while True:
                self._refill()
                if self._tokens >= tokens:
                    self._tokens -= tokens
                    return waited
                deficit = tokens - self._tokens
                delay = deficit / self.rate if self.rate > 0 else 0.05
                waited += delay
                await self._sleep(delay)


class RedisTokenBucket:
    """Distributed token bucket shared across all workers (atomic via Lua)."""

    _LUA = """
    local key = KEYS[1]
    local rate = tonumber(ARGV[1])
    local capacity = tonumber(ARGV[2])
    local now = tonumber(ARGV[3])
    local requested = tonumber(ARGV[4])
    local data = redis.call('HMGET', key, 'tokens', 'ts')
    local tokens = tonumber(data[1])
    local ts = tonumber(data[2])
    if tokens == nil then tokens = capacity; ts = now end
    tokens = math.min(capacity, tokens + (now - ts) * rate)
    local allowed = 0
    local wait = 0
    if tokens >= requested then
        tokens = tokens - requested
        allowed = 1
    else
        wait = (requested - tokens) / rate
    end
    redis.call('HMSET', key, 'tokens', tokens, 'ts', now)
    redis.call('EXPIRE', key, 3600)
    return {allowed, tostring(wait)}
    """

    def __init__(self, redis: object, key: str, refill_per_sec: float, capacity: int):
        self._r = redis
        self._key = f"aria:bucket:{key}"
        self.rate = float(refill_per_sec)
        self.capacity = int(capacity)

    async def acquire(self, tokens: float = 1.0) -> float:
        waited = 0.0
        while True:
            allowed, wait = await self._r.eval(  # type: ignore[attr-defined]
                self._LUA, 1, self._key, self.rate, self.capacity, time.time(), tokens
            )
            if int(allowed) == 1:
                return waited
            delay = max(0.01, float(wait))
            waited += delay
            await asyncio.sleep(delay)


class RateLimitDispatcher:
    """One bucket per provider; every outbound call acquires a slot first."""

    def __init__(self) -> None:
        self._buckets: dict[str, TokenBucket] = {}

    def _bucket(self, provider: str) -> TokenBucket:
        key = provider if provider in PROVIDER_LIMITS else "default"
        if key not in self._buckets:
            rate, cap = PROVIDER_LIMITS[key]
            self._buckets[key] = TokenBucket(rate, cap)
        return self._buckets[key]

    async def acquire(self, provider: str, tokens: float = 1.0) -> float:
        waited = await self._bucket(provider).acquire(tokens)
        if waited > 0.01:
            logger.debug("[ratelimit] paced %s by %.2fs", provider, waited)
        return waited


_dispatcher: RateLimitDispatcher | None = None


def get_dispatcher() -> RateLimitDispatcher:
    global _dispatcher
    if _dispatcher is None:
        _dispatcher = RateLimitDispatcher()
    return _dispatcher
