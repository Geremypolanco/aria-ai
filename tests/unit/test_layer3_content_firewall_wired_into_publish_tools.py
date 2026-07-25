"""Regression test: Guardrails Layer 3 (apps/core/safety/guardrails.py
check_content_safety, deterministic phishing/credential-harvesting pattern
matching) was built with real callers already existing (check_code_safety
is wired into execute_code), but check_content_safety itself had zero
callers — nothing stopped ARIA from publishing a phishing-shaped article,
newsletter, landing page, or social post, since Layer 1 only screens the
raw chat request text, not AI-generated output derived from an innocuous
prompt.

Wired into aria_mind.py's tool dispatcher for the four tools that produce
externally-visible content: publish_article, send_email, create_landing_page,
post_to_social. Each blocks before the real side effect (API call / preview
token mint) when the generated content matches a _PHISHING_MARKERS pattern,
and passes ordinary content through unchanged.

Also covers a second bug found while wiring this in: publish_article called
PublishingTools.publish_to_devto/_medium/_hashnode(title, content, tags),
methods that don't exist — the real methods are publish_devto/_medium/_hashnode
taking a single `article` dict. Every publish_article call raised
AttributeError before this fix.

Exercised through AriaMind._execute_tool exactly as a live conversation
would, not by calling check_content_safety directly.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from apps.conversion.landing_pages.landing_page_engine import LandingPage
from apps.core.cognition.aria_mind import AriaMind

pytestmark = pytest.mark.asyncio

OWNER_EMAIL = "owner@aria.test"
PHISHING_TEXT = "Please verify your account now, click here to continue or it will be suspended."


@pytest.fixture(autouse=True)
def _patch_owner():
    with patch("apps.core.auth.is_owner_email", side_effect=lambda e: e == OWNER_EMAIL):
        yield


class _FakeCache:
    def __init__(self):
        self._store = {}

    async def get(self, key):
        return self._store.get(key)

    async def set(self, key, value, ttl_seconds=3600):
        self._store[key] = value
        return True

    async def delete(self, key):
        self._store.pop(key, None)
        return True


# ── publish_article ────────────────────────────────────────────────────
async def test_publish_article_blocked_for_phishing_content():
    mind = AriaMind()
    obs, media = await mind._execute_tool(
        "publish_article",
        {"title": "Account Alert", "content": PHISHING_TEXT, "platforms": ["devto"]},
    )

    assert media == {}
    assert "blocked pattern" in obs.lower()


async def test_publish_article_reaches_publishing_tools_for_safe_content():
    fake_pt = AsyncMock()
    fake_pt.publish_devto = AsyncMock(
        return_value={"success": True, "platform": "devto", "url": "https://dev.to/x"}
    )
    with patch("apps.core.tools.publishing_tools.PublishingTools", return_value=fake_pt):
        mind = AriaMind()
        obs, media = await mind._execute_tool(
            "publish_article",
            {"title": "Yoga Tips", "content": "Ten tips for better yoga.", "platforms": ["devto"]},
        )

    assert media == {}
    assert "published on: devto" in obs.lower()
    fake_pt.publish_devto.assert_awaited_once_with(
        {
            "title": "Yoga Tips",
            "body": "Ten tips for better yoga.",
            "body_html": "Ten tips for better yoga.",
            "tags": [],
        }
    )


# ── send_email ──────────────────────────────────────────────────────────
async def test_send_email_blocked_for_phishing_content():
    mind = AriaMind()
    obs, media = await mind._execute_tool(
        "send_email",
        {"subject": "Account Alert", "body": PHISHING_TEXT, "to": "user@example.com"},
    )

    assert media == {}
    assert "blocked pattern" in obs.lower()


async def test_send_email_reaches_publishing_tools_for_safe_content():
    with patch(
        "apps.core.tools.publishing_tools.PublishingTools.send_newsletter",
        AsyncMock(return_value={"success": True, "provider": "resend"}),
    ):
        mind = AriaMind()
        obs, media = await mind._execute_tool(
            "send_email",
            {"subject": "Weekly digest", "body": "Here's what's new.", "to": "user@example.com"},
        )

    assert media == {}
    assert "email sent via resend" in obs.lower()


# ── create_landing_page ──────────────────────────────────────────────────
async def test_create_landing_page_blocked_for_phishing_content():
    phishing_page = LandingPage(
        product="Course",
        offer="50% off",
        target_audience="students",
        headline="Verify your account now, click here",
        subheadline="ok",
        hero_copy="ok",
        bullet_points=["a"],
        cta_primary="Get Course Now",
    )
    with patch(
        "apps.conversion.landing_pages.landing_page_engine.get_landing_page_engine"
    ) as mock_get_engine:
        mock_get_engine.return_value.create_page = AsyncMock(return_value=phishing_page)
        mind = AriaMind()
        obs, media = await mind._execute_tool(
            "create_landing_page",
            {"product": "Course", "offer": "50% off", "target_audience": "students"},
        )

    assert media == {}
    assert "blocked pattern" in obs.lower()


async def test_create_landing_page_returns_page_for_safe_content():
    safe_page = LandingPage(
        product="Course",
        offer="50% off",
        target_audience="students",
        headline="Master Yoga in 30 Days",
        subheadline="Proven system",
        hero_copy="Join thousands of students.",
        bullet_points=["Flexibility", "Strength"],
        cta_primary="Get Course Now",
    )
    with patch(
        "apps.conversion.landing_pages.landing_page_engine.get_landing_page_engine"
    ) as mock_get_engine:
        mock_get_engine.return_value.create_page = AsyncMock(return_value=safe_page)
        mind = AriaMind()
        obs, media = await mind._execute_tool(
            "create_landing_page",
            {"product": "Course", "offer": "50% off", "target_audience": "students"},
        )

    assert media == {}
    assert "Master Yoga in 30 Days" in obs


# ── post_to_social ────────────────────────────────────────────────────────
async def test_post_to_social_blocked_for_phishing_content_before_preview():
    cache = _FakeCache()
    with patch.object(AriaMind, "_cache_client", return_value=cache):
        mind = AriaMind()
        obs, media = await mind._execute_tool(
            "post_to_social",
            {"platform": "twitter", "text": PHISHING_TEXT},
            email=OWNER_EMAIL,
        )

    assert media == {}
    assert "blocked pattern" in obs.lower()
    # Must never mint a preview/confirm token for blocked content.
    assert cache._store == {}


async def test_post_to_social_preview_and_confirm_flow_for_safe_content():
    cache = _FakeCache()
    fake_session_mgr = AsyncMock()
    fake_session_mgr.post_to_platform = AsyncMock(
        return_value={"success": True, "url": "https://twitter.com/x/status/1"}
    )
    with (
        patch.object(AriaMind, "_cache_client", return_value=cache),
        patch(
            "apps.core.tools.social_session.get_social_session_manager",
            return_value=fake_session_mgr,
        ),
    ):
        mind = AriaMind()
        preview_obs, _ = await mind._execute_tool(
            "post_to_social",
            {"platform": "twitter", "text": "Check out our new yoga mats!"},
            email=OWNER_EMAIL,
        )
        assert "preview" in preview_obs.lower()
        token = preview_obs.split("confirm_token: ")[1].split(" ")[0]

        confirm_obs, media = await mind._execute_tool(
            "post_to_social",
            {
                "platform": "twitter",
                "text": "Check out our new yoga mats!",
                "confirm_token": token,
            },
            email=OWNER_EMAIL,
        )

    assert media == {}
    assert "posted to twitter" in confirm_obs.lower()
    fake_session_mgr.post_to_platform.assert_awaited_once_with(
        "twitter", "Check out our new yoga mats!"
    )
