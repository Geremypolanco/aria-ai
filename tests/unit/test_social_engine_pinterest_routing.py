"""Regression test: SocialContentEngine.create_and_post() never routed
"pinterest" to SocialContentTools.post_pinterest() despite that method being
fully implemented — the if/elif chain checked twitter/discord/reddit only,
so pinterest silently fell into the generic OAuth-connected-accounts poster
(a completely different auth path from Pinterest's own access token), making
Pinterest posting via this entry point dead functionality. Also,
_PLATFORM_SPECS had no "pinterest" key, so content generation silently fell
back to Instagram's tone/format for Pinterest requests.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from apps.core.tools.social_engine import _PLATFORM_SPECS, SocialContentEngine, SocialContentTools


def test_platform_specs_has_dedicated_pinterest_entry():
    assert "pinterest" in _PLATFORM_SPECS
    assert _PLATFORM_SPECS["pinterest"] != _PLATFORM_SPECS["instagram"]


@pytest.mark.asyncio
async def test_create_and_post_routes_pinterest_to_post_pinterest():
    engine = SocialContentEngine()
    fake_pack = {
        "success": True,
        "topic": "t",
        "platforms": {"pinterest": {"success": True, "content": "pin content"}},
    }
    with patch.object(
        SocialContentEngine, "create_content_pack", AsyncMock(return_value=fake_pack)
    ), patch.object(
        SocialContentTools, "post_pinterest", AsyncMock(return_value={"success": True, "platform": "pinterest"})
    ) as mock_pin, patch.object(
        SocialContentTools, "post_via_oauth_accounts", AsyncMock(return_value={"success": False})
    ) as mock_oauth:
        result = await engine.create_and_post("t", ["pinterest"])

    mock_pin.assert_awaited_once()
    mock_oauth.assert_not_awaited()
    assert result["posting"]["pinterest"]["success"] is True
