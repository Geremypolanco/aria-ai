"""
deps.py — Reusable FastAPI auth + rate-limit dependencies.

Lets the modular routers (clipper, voice-profile, …) share the exact same
signed-session auth as the rest of the app without duplicating logic or
importing from main.py (avoids a circular import).

- `current_user(request)`   → the verified session dict, or None
- `require_user`            → dependency that 401s unauthenticated callers
- `rate_limit(bucket, ...)` → sliding-window limiter dependency factory
"""

from __future__ import annotations

import time
from collections import defaultdict, deque
from collections.abc import Callable

from fastapi import Header, HTTPException, Request, status


def current_user(request: Request, authorization: str | None = None) -> dict | None:
    """Verify the caller's identity from the session cookie or a Bearer token.

    Browser extensions can't always send the site cookie, so we also accept the
    same signed token as `Authorization: Bearer <token>`.
    """
    from apps.core import auth

    token = request.cookies.get(auth.USER_COOKIE)
    if not token and authorization and authorization.lower().startswith("bearer "):
        token = authorization.split(" ", 1)[1].strip()
    try:
        return auth.verify_user(token)
    except Exception:
        return None


async def require_user(request: Request, authorization: str | None = Header(default=None)) -> dict:
    """Dependency: return the signed-in user or raise 401."""
    user = current_user(request, authorization)
    if not user or not user.get("email"):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="authentication required"
        )
    return user


# ── in-process sliding-window rate limiter ────────────────────────
_HITS: dict[str, deque] = defaultdict(deque)


def _client_ip(request: Request) -> str:
    fwd = request.headers.get("x-forwarded-for", "")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def rate_limit(bucket: str, limit: int, window: float) -> Callable:
    """Return a dependency that 429s a client exceeding `limit` per `window`s."""

    async def _dep(request: Request) -> None:
        key = f"{bucket}:{_client_ip(request)}"
        now = time.time()
        hits = _HITS[key]
        while hits and hits[0] <= now - window:
            hits.popleft()
        if len(hits) >= limit:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="rate limit exceeded"
            )
        hits.append(now)

    return _dep
