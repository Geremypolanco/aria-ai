"""
connector_health.py — Connector Health Semaphore.

Periodically health-checks the external APIs ARIA publishes to (Instagram,
YouTube, LinkedIn, X, Facebook, …). If a platform is globally unreachable, its
status flips to "offline" and the app surfaces a preventive banner so queued
posts are held until the service recovers.

Statuses: "online" | "degraded" | "offline" | "unknown".
The checker uses an injectable async HTTP getter so it's fully testable without
network access.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

logger = logging.getLogger("aria.connector_health")

CHECK_INTERVAL_SECONDS = 30 * 60  # 30 minutes
_TIMEOUT = 8.0

# Lightweight, unauthenticated reachability endpoints per connector.
CONNECTOR_ENDPOINTS: dict[str, str] = {
    "instagram": "https://www.instagram.com/",
    "youtube": "https://www.youtube.com/",
    "linkedin": "https://www.linkedin.com/",
    "facebook": "https://graph.facebook.com/",
    "x": "https://api.twitter.com/",
    "tiktok": "https://www.tiktok.com/",
}


@dataclass
class ConnectorStatus:
    name: str
    status: str = "unknown"
    latency_ms: int | None = None
    checked_at: float | None = None
    detail: str = ""

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "status": self.status,
            "latency_ms": self.latency_ms,
            "checked_at": self.checked_at,
            "detail": self.detail,
        }


class HealthStore:
    def __init__(self) -> None:
        self._statuses: dict[str, ConnectorStatus] = {
            name: ConnectorStatus(name=name) for name in CONNECTOR_ENDPOINTS
        }

    def set(self, name: str, status: str, latency_ms: int | None, detail: str = "") -> None:
        self._statuses[name] = ConnectorStatus(
            name=name,
            status=status,
            latency_ms=latency_ms,
            checked_at=time.time(),
            detail=detail,
        )

    def get_all(self) -> dict[str, dict]:
        return {name: s.to_dict() for name, s in self._statuses.items()}

    def offline(self) -> list[str]:
        return [n for n, s in self._statuses.items() if s.status == "offline"]

    def any_offline(self) -> bool:
        return bool(self.offline())


_store: HealthStore | None = None


def get_store() -> HealthStore:
    global _store
    if _store is None:
        _store = HealthStore()
    return _store


def classify(status_code: int | None, error: str | None) -> str:
    """Map a probe result to a connector status."""
    if error is not None:
        return "offline"
    if status_code is None:
        return "offline"
    if status_code < 400 or status_code in (401, 403, 429):
        # 401/403/429 mean the host is UP (just auth/limit) — treat as online.
        return "online"
    if 400 <= status_code < 500:
        return "degraded"
    return "offline"  # 5xx → the platform is down


# An async getter: (url) -> (status_code | None, error | None)
Getter = Callable[[str], Awaitable[tuple[int | None, str | None]]]


async def _default_getter(url: str) -> tuple[int | None, str | None]:
    try:
        import httpx

        async with httpx.AsyncClient(timeout=_TIMEOUT, follow_redirects=True) as c:
            r = await c.get(url)
            return r.status_code, None
    except Exception as exc:  # noqa: BLE001
        return None, f"{type(exc).__name__}: {exc}"


async def _probe_one(name: str, url: str, getter: Getter, store: HealthStore) -> None:
    t0 = time.time()
    status_code, error = await getter(url)
    latency = int((time.time() - t0) * 1000)
    status = classify(status_code, error)
    store.set(
        name, status, latency if error is None else None, detail=error or f"HTTP {status_code}"
    )
    if status == "offline":
        logger.warning("[health] %s is OFFLINE (%s)", name, error or status_code)


async def check_all(
    getter: Getter | None = None, store: HealthStore | None = None
) -> dict[str, dict]:
    """Probe every connector once (concurrently) and update the store.

    Sequential awaits here would mean up to len(CONNECTOR_ENDPOINTS) *
    _TIMEOUT seconds in the worst case — and this can run inline on a request
    (see /api/v1/connectors/health's stale-cache refresh), so a slow/hanging
    host would stall an unrelated user's HTTP response for that whole time.
    """
    import asyncio

    getter = getter or _default_getter
    store = store or get_store()
    await asyncio.gather(
        *(_probe_one(name, url, getter, store) for name, url in CONNECTOR_ENDPOINTS.items())
    )
    return store.get_all()
