"""
ARIA public site URL — env-parametrizable with honest degradation.

``ARIA_BASE_URL`` used to default to the hardcoded domain
``https://aria-ai.fly.dev``, which no longer exists. Traffic-driving work
(the income loop's traffic strategies, published content footers,
OAuth/Zapier callbacks) then pointed at a dead domain — 404 spam and broken
callbacks.

The variable is now honestly optional:

- ``get_aria_base_url()`` → the configured URL, or ``""`` when unconfigured.
  No default domain is invented.
- ``is_aria_site_live()`` → cached liveness probe (TTL 15 min); ``False``
  when unconfigured OR unreachable. The income loop consults it before
  running traffic-driving strategies, and published content omits the site
  link when the site is not live — no 404 spam, ever.
- ``site_link(path)`` → absolute URL for a site path, or ``""`` when there
  is no configured site.

No network I/O happens at import time; the probe only runs when
``is_aria_site_live()`` is called.
"""

from __future__ import annotations

import time

from apps.core.config import settings

#: How long a liveness probe result is trusted before re-probing.
PROBE_TTL_S = 900

_probe_at: float = 0.0
_probe_live: bool = False


def get_aria_base_url() -> str:
    """Configured public base URL of this deployment, or ``""``.

    Set the ``ARIA_BASE_URL`` env var to the deployment's public URL
    (e.g. ``https://aria.example.com``). Empty means "no public site
    configured" — callers must degrade honestly instead of inventing one.
    """
    return (getattr(settings, "ARIA_BASE_URL", "") or "").strip().rstrip("/")


def site_link(path: str = "") -> str:
    """Absolute URL for ``path`` on the configured site, or ``""``.

    Returns ``""`` when no site is configured so published content can
    simply omit the link instead of pointing readers at a dead domain.
    """
    base = get_aria_base_url()
    if not base:
        return ""
    if not path:
        return base
    return base + (path if path.startswith("/") else f"/{path}")


def is_aria_site_live(*, timeout_s: float = 5.0, force: bool = False) -> bool:
    """True when the configured site answers HTTP 2xx/3xx.

    Result is cached for :data:`PROBE_TTL_S` so a tight loop never spams
    the site. ``False`` when unconfigured or on any network error — callers
    treat that as "degrade traffic-driving work", never as fatal.
    """
    global _probe_at, _probe_live
    base = get_aria_base_url()
    if not base:
        return False
    now = time.monotonic()
    if not force and (now - _probe_at) < PROBE_TTL_S:
        return _probe_live
    live = False
    try:
        import httpx

        resp = httpx.get(base, timeout=timeout_s, follow_redirects=True)
        live = resp.status_code < 400
    except Exception:
        live = False
    _probe_at = now
    _probe_live = live
    return live


def reset_probe_cache() -> None:
    """Forget the cached probe result (tests / forced re-check)."""
    global _probe_at, _probe_live
    _probe_at = 0.0
    _probe_live = False


def describe_site_status() -> str:
    """One-line human/operator summary of the site configuration."""
    base = get_aria_base_url()
    if not base:
        return "ARIA_BASE_URL not configured — traffic-driving work is parked"
    if is_aria_site_live():
        return f"site live at {base}"
    return f"site configured ({base}) but NOT reachable — traffic work parked"
