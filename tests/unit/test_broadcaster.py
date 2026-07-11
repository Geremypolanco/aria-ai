"""
Unit tests for the reusable SocialBroadcaster capability.

Channels are exercised in isolation by patching the lazily-imported publisher,
so these tests never touch the network or a real browser.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from apps.distribution.publishers import broadcaster
from apps.distribution.publishers.broadcaster import (
    BroadcastSummary,
    ChannelResult,
    available_channels,
    broadcast,
)


def _fake_publisher(success: bool, url: str = "https://x/post"):
    pub = MagicMock()
    pub.publish_to_linkedin = AsyncMock(return_value=MagicMock(success=success, url=url))
    pub.publish_to_twitter = AsyncMock(return_value=MagicMock(success=success, url=url))
    return pub


class TestRegistry:
    def test_available_channels(self):
        chans = available_channels()
        assert "linkedin" in chans
        assert "twitter" in chans


class TestBroadcast:
    async def test_empty_text_returns_empty(self):
        assert await broadcast("   ") == {}

    async def test_unknown_channel_is_ignored(self):
        with patch(
            "apps.distribution.publishers.api_publisher.get_api_publisher",
            return_value=_fake_publisher(True),
        ):
            res = await broadcast("hello", channels=["does-not-exist"])
        assert res == {}

    async def test_api_success_marks_via_api(self):
        with patch(
            "apps.distribution.publishers.api_publisher.get_api_publisher",
            return_value=_fake_publisher(True, url="https://li/123"),
        ):
            res = await broadcast("hello world", channels=["linkedin"])
        assert res["linkedin"].success is True
        assert res["linkedin"].via == "api"
        assert res["linkedin"].url == "https://li/123"

    async def test_api_failure_without_creds_fails_soft(self):
        # API returns not-success, and no ARIA_EMAIL/PASSWORD → channel fails, no raise
        with (
            patch(
                "apps.distribution.publishers.api_publisher.get_api_publisher",
                return_value=_fake_publisher(False),
            ),
            patch.object(
                broadcaster, "_resolve_creds", return_value=broadcaster._Creds(None, None)
            ),
        ):
            res = await broadcast("hello world", channels=["linkedin", "twitter"])
        assert res["linkedin"].success is False
        assert res["twitter"].success is False

    async def test_multiple_channels_run(self):
        with patch(
            "apps.distribution.publishers.api_publisher.get_api_publisher",
            return_value=_fake_publisher(True),
        ):
            res = await broadcast("hello", channels=["linkedin", "twitter"])
        assert set(res.keys()) == {"linkedin", "twitter"}
        assert all(r.success for r in res.values())


class TestSummary:
    def test_summary_aggregates(self):
        results = {
            "linkedin": ChannelResult("linkedin", True, url="https://li/1", via="api"),
            "twitter": ChannelResult("twitter", False, error="nope"),
        }
        s = BroadcastSummary(results)
        assert s.posted == ["linkedin"]
        assert s.urls == ["https://li/1"]
        assert s.any_success is True

    def test_summary_all_failed(self):
        s = BroadcastSummary({"twitter": ChannelResult("twitter", False)})
        assert s.posted == []
        assert s.any_success is False


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
