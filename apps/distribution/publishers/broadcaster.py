"""
SocialBroadcaster — one reusable capability for publishing to social channels.

WHY THIS EXISTS
---------------
The "try the platform API, then fall back to stealth-browser automation" pattern
was copy-pasted across ~100 strategy call sites in income_loop.py. Every site
re-implemented: call get_api_publisher().publish_to_X → on failure, log in via
human_browser with ARIA_EMAIL/ARIA_PASSWORD → post again. That is duplication and
technical debt: a change to the fallback logic (or a new channel) meant editing
~100 places.

This module encapsulates that pattern ONCE. Strategies call ``broadcast(text,
channels=[...])`` and get a uniform result per channel. The API→browser fallback,
credential resolution, timeouts and logging all live here.

EXTENDING IT
------------
Adding a new channel (TikTok, Facebook, Threads…) means adding one entry to the
``_CHANNELS`` registry — callers never change. This is a reusable capability, not
a per-case solution.

DESIGN NOTES (decoupling / testability)
---------------------------------------
- Heavy deps (api_publisher, human_browser) are imported lazily inside the channel
  functions so importing this module is cheap and side-effect free.
- Each channel is a small async callable taking (text, creds) → ChannelResult, so
  channels can be tested in isolation by injecting fakes.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

logger = logging.getLogger("aria.broadcaster")

DEFAULT_CHANNELS: tuple[str, ...] = ("linkedin", "twitter")


@dataclass
class ChannelResult:
    """Outcome of publishing to a single channel."""

    channel: str
    success: bool
    url: str = ""
    via: str = "none"  # "api" | "browser" | "none"
    error: str = ""

    def to_dict(self) -> dict:
        return {
            "channel": self.channel,
            "success": self.success,
            "url": self.url,
            "via": self.via,
            "error": self.error,
        }


@dataclass
class _Creds:
    """Credentials resolved once and shared across channels for one broadcast."""

    email: str | None = None
    password: str | None = None


def _resolve_creds(email: str | None, password: str | None) -> _Creds:
    """Fall back to ARIA_EMAIL/ARIA_PASSWORD from settings when not explicitly given."""
    if email and password:
        return _Creds(email, password)
    try:
        from apps.core.config import settings

        return _Creds(
            email or getattr(settings, "ARIA_EMAIL", None),
            password or getattr(settings, "ARIA_PASSWORD", None),
        )
    except Exception:
        return _Creds(email, password)


# ── Channel implementations ─────────────────────────────────────────────────────


async def _publish_linkedin(text: str, creds: _Creds, timeout: float) -> ChannelResult:
    # 1. Official API
    try:
        from apps.distribution.publishers.api_publisher import get_api_publisher

        res = await asyncio.wait_for(
            get_api_publisher().publish_to_linkedin(text[:3000]), timeout=timeout
        )
        if res and res.success:
            return ChannelResult("linkedin", True, url=res.url or "", via="api")
    except Exception as exc:
        logger.warning("[broadcast] linkedin API failed: %s", exc)

    # 2. Stealth-browser fallback
    if creds.email and creds.password:
        try:
            from apps.core.tools.human_browser import get_platform_login

            plat = await get_platform_login()
            page = await plat.linkedin(creds.email, creds.password)
            if await plat.linkedin_create_post(page, text[:3000]):
                return ChannelResult(
                    "linkedin", True, url="https://www.linkedin.com/feed/", via="browser"
                )
        except Exception as exc:
            logger.warning("[broadcast] linkedin browser failed: %s", exc)

    return ChannelResult("linkedin", False, error="all linkedin methods failed")


async def _publish_twitter(text: str, creds: _Creds, timeout: float) -> ChannelResult:
    # 1. Official API
    try:
        from apps.distribution.publishers.api_publisher import get_api_publisher

        res = await asyncio.wait_for(
            get_api_publisher().publish_to_twitter(text[:280]), timeout=timeout
        )
        if res and res.success:
            return ChannelResult("twitter", True, url=res.url or "", via="api")
    except Exception as exc:
        logger.warning("[broadcast] twitter API failed: %s", exc)

    # 2. Stealth-browser fallback
    if creds.email and creds.password:
        try:
            from apps.core.tools.human_browser import get_platform_login

            plat = await get_platform_login()
            page = await plat.twitter(creds.email, creds.password)
            url = await plat.twitter_thread_post(page, [text[:280]])
            if url:
                return ChannelResult(
                    "twitter", True, url=url if isinstance(url, str) else "", via="browser"
                )
        except Exception as exc:
            logger.warning("[broadcast] twitter browser failed: %s", exc)

    return ChannelResult("twitter", False, error="all twitter methods failed")


# Channel registry — add a new channel here and every caller gains it for free.
_CHANNELS: dict[str, Callable[[str, _Creds, float], Awaitable[ChannelResult]]] = {
    "linkedin": _publish_linkedin,
    "twitter": _publish_twitter,
}


def available_channels() -> list[str]:
    """List the channels broadcast() can publish to."""
    return list(_CHANNELS)


async def broadcast(
    text: str,
    channels: list[str] | tuple[str, ...] = DEFAULT_CHANNELS,
    *,
    email: str | None = None,
    password: str | None = None,
    timeout: float = 20.0,
) -> dict[str, ChannelResult]:
    """
    Publish ``text`` to each requested channel, API-first with a browser fallback.

    Returns a mapping ``{channel: ChannelResult}``. Never raises — a failing channel
    yields a ChannelResult(success=False) so one bad channel can't break the others.
    Channels run concurrently.
    """
    if not text or not text.strip():
        return {}
    creds = _resolve_creds(email, password)
    wanted = [c.lower() for c in channels if c.lower() in _CHANNELS]

    async def _run(ch: str) -> ChannelResult:
        try:
            return await _CHANNELS[ch](text, creds, timeout)
        except Exception as exc:  # defensive — channels already swallow their own errors
            logger.warning("[broadcast] %s raised: %s", ch, exc)
            return ChannelResult(ch, False, error=str(exc)[:200])

    results = await asyncio.gather(*[_run(c) for c in wanted])
    return {r.channel: r for r in results}


@dataclass
class BroadcastSummary:
    """Convenience aggregate over a broadcast() result."""

    results: dict[str, ChannelResult] = field(default_factory=dict)

    @property
    def posted(self) -> list[str]:
        return [c for c, r in self.results.items() if r.success]

    @property
    def urls(self) -> list[str]:
        return [r.url for r in self.results.values() if r.success and r.url]

    @property
    def any_success(self) -> bool:
        return any(r.success for r in self.results.values())
