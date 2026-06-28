"""
Reusable Redis-backed rate-limit dependency for public HTTP endpoints.

One capability, used everywhere — instead of hand-rolling limits per endpoint.
Add ``dependencies=[Depends(rate_limit(max_calls, window_seconds, "bucket"))]`` to
any route. Keyed by client IP. Fails OPEN (never blocks legit traffic) if Redis is
unavailable or the limiter errors — availability over strictness for a revenue app.
"""

from __future__ import annotations

import logging

from fastapi import HTTPException, Request

logger = logging.getLogger("aria.ratelimit")


def _client_ip(request: Request) -> str:
    """Real client IP, honoring proxy headers.

    Behind Fly.io (and any load balancer) ``request.client.host`` is the PROXY's IP,
    so keying on it would put every user in one shared bucket. Prefer the
    edge-provided client IP, then the first X-Forwarded-For hop, then the socket peer.
    """
    fly = request.headers.get("fly-client-ip")
    if fly:
        return fly.strip()
    xff = request.headers.get("x-forwarded-for")
    if xff:
        return xff.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def rate_limit(max_calls: int, window_seconds: int, bucket: str):
    """Build a FastAPI dependency enforcing ``max_calls`` per ``window_seconds`` per IP."""

    async def _dependency(request: Request) -> None:
        try:
            from apps.core.memory.redis_client import get_cache

            cache = get_cache()
            if not cache:
                return  # fail-open: no limiter backend
            ip = _client_ip(request)
            allowed = await cache.check_rate_limit(f"{bucket}:{ip}", max_calls, window_seconds)
        except Exception as exc:  # never let the limiter take down the endpoint
            logger.debug("[ratelimit] check failed (fail-open): %s", exc)
            return
        if not allowed:
            raise HTTPException(
                status_code=429,
                detail="Too many requests — please slow down and try again shortly.",
            )

    return _dependency
