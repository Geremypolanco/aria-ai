"""Regression test: SocialSessionManager (apps/core/tools/social_session.py)
— posts to live social platforms using the owner's own exported browser-
session cookies through unofficial, reverse-engineered endpoints — had zero
live callers. Last item from the full-repo dead-code audit; deliberately the
last one wired, since it carries a materially different risk profile than
everything else this session:

  - real account-ban/ToS risk on the owner's own social accounts
  - an immediately public, effectively irreversible action (a live post)
  - uses a real logged-in session, not a scoped API token

So it gets two safety properties nothing else wired this session needed:

  1. Owner-only (added to AriaMind._OWNER_ONLY_TOOLS), same as github_write /
     execute_code / computer_use.
  2. A CODE-enforced preview-before-post gate, not just a prompt instruction.
     post_to_social's first call always returns a preview + a random
     confirm_token stored server-side (short TTL); only a second call
     supplying that exact token, platform, and text actually posts. A model
     cannot skip straight to posting by setting confirmed=true on a single
     call, because no valid token exists until a prior preview call minted
     one — this is verified directly below, not just asserted in docs.

Wired into aria_mind.py's tool dispatcher as: list_social_sessions,
check_social_session, post_to_social.

Exercised through AriaMind._execute_tool exactly as a live conversation
would, not by calling the manager directly.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from apps.core.cognition.aria_mind import AriaMind

pytestmark = pytest.mark.asyncio

OWNER_EMAIL = "owner@aria.test"
OTHER_EMAIL = "someone-else@example.com"


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


@pytest.fixture(autouse=True)
def _patch_owner_check():
    with patch("apps.core.auth.is_owner_email", side_effect=lambda e: e == OWNER_EMAIL):
        yield


@pytest.mark.parametrize(
    "tool,args",
    [
        ("list_social_sessions", {}),
        ("check_social_session", {"platform": "twitter"}),
        ("post_to_social", {"platform": "twitter", "text": "hi"}),
    ],
)
async def test_social_tools_blocked_for_non_owner(tool, args):
    mind = AriaMind()
    obs, media = await mind._execute_tool(tool, args, email=OTHER_EMAIL)

    assert media == {}
    assert "owner" in obs.lower()


async def test_list_social_sessions_empty_state():
    fake_manager = AsyncMock()
    fake_manager.list_active_sessions = AsyncMock(return_value=[])
    with patch(
        "apps.core.tools.social_session.get_social_session_manager", return_value=fake_manager
    ):
        mind = AriaMind()
        obs, media = await mind._execute_tool("list_social_sessions", {}, email=OWNER_EMAIL)

    assert media == {}
    assert "no social sessions" in obs.lower()


async def test_list_social_sessions_reachable_for_owner():
    fake_manager = AsyncMock()
    fake_manager.list_active_sessions = AsyncMock(
        return_value=[
            {
                "platform": "twitter",
                "display_name": "Twitter / X",
                "emoji": "🐦",
                "cookies_count": 5,
                "age_days": 3,
            }
        ]
    )
    with patch(
        "apps.core.tools.social_session.get_social_session_manager", return_value=fake_manager
    ):
        mind = AriaMind()
        obs, media = await mind._execute_tool("list_social_sessions", {}, email=OWNER_EMAIL)

    assert media == {}
    assert "Twitter / X" in obs


async def test_check_social_session_reachable_for_owner():
    fake_manager = AsyncMock()
    fake_manager.test_session = AsyncMock(return_value={"success": True})
    with patch(
        "apps.core.tools.social_session.get_social_session_manager", return_value=fake_manager
    ):
        mind = AriaMind()
        obs, media = await mind._execute_tool(
            "check_social_session", {"platform": "twitter"}, email=OWNER_EMAIL
        )

    assert media == {}
    assert "session active" in obs.lower()


async def test_post_to_social_first_call_never_posts():
    """The whole point of the gate: a single call, even one that tries to
    claim confirmation, must never actually publish anything."""
    fake_manager = AsyncMock()
    fake_manager.post_to_platform = AsyncMock(
        return_value={"success": True, "url": "should-not-be-called"}
    )
    fake_cache = _FakeCache()
    mind = AriaMind()
    with (
        patch(
            "apps.core.tools.social_session.get_social_session_manager", return_value=fake_manager
        ),
        patch.object(mind, "_cache_client", return_value=fake_cache),
    ):
        obs, media = await mind._execute_tool(
            "post_to_social",
            {"platform": "twitter", "text": "Big announcement!", "confirmed": True},
            email=OWNER_EMAIL,
        )

    assert media == {}
    assert "Preview" in obs
    assert "not yet posted" in obs
    fake_manager.post_to_platform.assert_not_awaited()


async def test_post_to_social_confirm_token_flow_actually_posts():
    fake_manager = AsyncMock()
    fake_manager.post_to_platform = AsyncMock(
        return_value={"success": True, "url": "https://x.com/i/status/123"}
    )
    fake_cache = _FakeCache()
    mind = AriaMind()

    with (
        patch(
            "apps.core.tools.social_session.get_social_session_manager", return_value=fake_manager
        ),
        patch.object(mind, "_cache_client", return_value=fake_cache),
    ):
        preview_obs, _ = await mind._execute_tool(
            "post_to_social",
            {"platform": "twitter", "text": "Big announcement!"},
            email=OWNER_EMAIL,
        )
        assert "confirm_token:" in preview_obs
        token = preview_obs.split("confirm_token:")[1].split()[0].strip()

        confirmed_obs, media = await mind._execute_tool(
            "post_to_social",
            {"platform": "twitter", "text": "Big announcement!", "confirm_token": token},
            email=OWNER_EMAIL,
        )

    assert media == {}
    assert "Posted to twitter" in confirmed_obs
    fake_manager.post_to_platform.assert_awaited_once_with("twitter", "Big announcement!")


async def test_post_to_social_wrong_token_does_not_post():
    fake_manager = AsyncMock()
    fake_manager.post_to_platform = AsyncMock(return_value={"success": True})
    fake_cache = _FakeCache()
    mind = AriaMind()

    with (
        patch(
            "apps.core.tools.social_session.get_social_session_manager", return_value=fake_manager
        ),
        patch.object(mind, "_cache_client", return_value=fake_cache),
    ):
        obs, media = await mind._execute_tool(
            "post_to_social",
            {"platform": "twitter", "text": "Big announcement!", "confirm_token": "made-up-token"},
            email=OWNER_EMAIL,
        )

    assert media == {}
    assert "Preview" in obs
    fake_manager.post_to_platform.assert_not_awaited()


async def test_post_to_social_token_does_not_transfer_to_different_text():
    """A confirm_token minted for one piece of text must not authorize
    posting different text."""
    fake_manager = AsyncMock()
    fake_manager.post_to_platform = AsyncMock(return_value={"success": True})
    fake_cache = _FakeCache()
    mind = AriaMind()

    with (
        patch(
            "apps.core.tools.social_session.get_social_session_manager", return_value=fake_manager
        ),
        patch.object(mind, "_cache_client", return_value=fake_cache),
    ):
        preview_obs, _ = await mind._execute_tool(
            "post_to_social", {"platform": "twitter", "text": "Original text"}, email=OWNER_EMAIL
        )
        token = preview_obs.split("confirm_token:")[1].split()[0].strip()

        obs, media = await mind._execute_tool(
            "post_to_social",
            {"platform": "twitter", "text": "Different text!", "confirm_token": token},
            email=OWNER_EMAIL,
        )

    assert media == {}
    assert "Preview" in obs
    fake_manager.post_to_platform.assert_not_awaited()
