"""Phase 14 tests — RealAPIPublisher."""
from __future__ import annotations
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


def _mock_cache():
    c = MagicMock()
    c.get = AsyncMock(return_value=None)
    c.set = AsyncMock(return_value=True)
    return c


@pytest.fixture
def publisher():
    with patch("apps.distribution.publishers.api_publisher.get_cache", return_value=_mock_cache()):
        from apps.distribution.publishers.api_publisher import RealAPIPublisher
        return RealAPIPublisher()


# ── PublishResult dataclass ───────────────────────────────────────────────────

def test_publish_result_to_dict_has_required_keys(publisher):
    from apps.distribution.publishers.api_publisher import PublishResult
    r = PublishResult(platform="twitter", content_preview="hello", success=False)
    d = r.to_dict()
    required = {"publish_id", "platform", "content_preview", "success", "post_id",
                "url", "error", "impressions_estimate", "published_at", "retry_count"}
    assert required.issubset(d.keys())


def test_publish_result_default_not_success(publisher):
    from apps.distribution.publishers.api_publisher import PublishResult
    r = PublishResult(platform="twitter", content_preview="test", success=False)
    assert r.success is False


def test_publish_request_to_dict_has_required_keys(publisher):
    from apps.distribution.publishers.api_publisher import PublishRequest
    req = PublishRequest(platforms=["twitter"], content="Hello world")
    d = req.to_dict()
    assert "request_id" in d
    assert "platforms" in d
    assert "content" in d


# ── Twitter publishing ────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_publish_to_twitter_without_credentials(publisher):
    from apps.distribution.publishers.api_publisher import PublishResult
    result = await publisher.publish_to_twitter("Hello world")
    assert isinstance(result, PublishResult)
    assert result.platform == "twitter"
    assert result.success is False
    assert len(result.error) > 0


@pytest.mark.asyncio
async def test_publish_to_twitter_stores_in_log(publisher):
    await publisher._load()
    await publisher.publish_to_twitter("Test tweet")
    assert len(publisher._publish_log) >= 1


@pytest.mark.asyncio
async def test_publish_to_twitter_returns_publish_result(publisher):
    from apps.distribution.publishers.api_publisher import PublishResult
    result = await publisher.publish_to_twitter("Test content")
    assert isinstance(result, PublishResult)


# ── LinkedIn publishing ───────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_publish_to_linkedin_without_credentials(publisher):
    result = await publisher.publish_to_linkedin("LinkedIn post content")
    assert result.platform == "linkedin"
    assert result.success is False


@pytest.mark.asyncio
async def test_publish_to_linkedin_stores_in_log(publisher):
    await publisher._load()
    await publisher.publish_to_linkedin("Post")
    assert len(publisher._publish_log) >= 1


# ── TikTok publishing ─────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_publish_to_tiktok_without_credentials(publisher):
    result = await publisher.publish_to_tiktok("https://example.com/video.mp4", "AI tips")
    assert result.platform == "tiktok"
    assert result.success is False


@pytest.mark.asyncio
async def test_publish_to_tiktok_stores_in_log(publisher):
    await publisher._load()
    await publisher.publish_to_tiktok("https://example.com/video.mp4", "Test caption")
    assert len(publisher._publish_log) >= 1


# ── Thread publishing ─────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_publish_thread_returns_list(publisher):
    tweets = ["First tweet", "Second tweet", "Third tweet"]
    results = await publisher.publish_thread_to_twitter(tweets)
    assert isinstance(results, list)
    assert len(results) >= 1


@pytest.mark.asyncio
async def test_publish_thread_returns_publish_results(publisher):
    from apps.distribution.publishers.api_publisher import PublishResult
    results = await publisher.publish_thread_to_twitter(["Tweet 1", "Tweet 2"])
    assert all(isinstance(r, PublishResult) for r in results)


@pytest.mark.asyncio
async def test_publish_thread_all_twitter_platform(publisher):
    results = await publisher.publish_thread_to_twitter(["T1", "T2"])
    assert all(r.platform == "twitter" for r in results)


# ── Batch publish ─────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_batch_publish_returns_list(publisher):
    from apps.distribution.publishers.api_publisher import PublishRequest
    req = PublishRequest(platforms=["twitter", "linkedin"], content="Test content")
    results = await publisher.batch_publish(req)
    assert isinstance(results, list)
    assert len(results) >= 1


@pytest.mark.asyncio
async def test_batch_publish_covers_all_platforms(publisher):
    from apps.distribution.publishers.api_publisher import PublishRequest
    req = PublishRequest(platforms=["twitter", "linkedin"], content="Multi-platform content")
    results = await publisher.batch_publish(req)
    platforms = {r.platform for r in results}
    assert "twitter" in platforms
    assert "linkedin" in platforms


# ── Stats and history ─────────────────────────────────────────────────────────

def test_publishing_stats_has_required_keys(publisher):
    stats = publisher.publishing_stats()
    assert "total_published" in stats
    assert "success_rate_pct" in stats
    assert "by_platform" in stats
    assert "recent_errors" in stats
    assert "total_impressions_estimate" in stats


@pytest.mark.asyncio
async def test_publishing_stats_updates_after_publish(publisher):
    await publisher._load()
    await publisher.publish_to_twitter("Stats test")
    stats = publisher.publishing_stats()
    assert stats["total_published"] >= 1


def test_recent_publishes_returns_list(publisher):
    result = publisher.recent_publishes(limit=10)
    assert isinstance(result, list)


@pytest.mark.asyncio
async def test_recent_publishes_after_publish(publisher):
    await publisher._load()
    await publisher.publish_to_twitter("Recent test")
    result = publisher.recent_publishes(limit=10)
    assert len(result) >= 1


@pytest.mark.asyncio
async def test_multiple_publishes_accumulate(publisher):
    await publisher._load()
    await publisher.publish_to_twitter("Post 1")
    await publisher.publish_to_linkedin("Post 2")
    assert len(publisher._publish_log) == 2
