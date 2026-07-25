"""Regression test: four complete, honest, previously-unwired content/
distribution engines found by a follow-up scouting pass over the trees not
covered by the earlier reconciliation scout (apps/creative, apps/distribution,
apps/infra, and the rest).

- DifferentiationEngine (apps/creative/differentiation/differentiation_engine.py):
  real cliché-phrase detection (a curated list, not fabricated), AI-rewritten
  alternatives with a deterministic non-AI fallback.
- BlogPublisher (apps/distribution/blog/blog_publisher.py),
  LinkedInPublisher (apps/distribution/linkedin/linkedin_publisher.py),
  TwitterEngine (apps/distribution/twitter/twitter_engine.py): real AI-backed
  long-form/social content generation, with engagement/reach/traffic figures
  derived from a disclosed deterministic heuristic (never random, never
  claimed as measured performance).

Also confirms apps/infra/media_workers/media_pipeline.py is gone — it
fabricated "processing" (unchanged source_url, hardcoded status=COMPLETED
and duration_seconds=5.0) and was deleted rather than wired.

Wired into aria_mind.py's tool dispatcher as: analyze_content_originality,
purge_generic_phrases, generate_unique_angles, check_audience_fatigue,
write_blog_post, generate_blog_outline, generate_blog_topic_cluster,
blog_publishing_stats, create_linkedin_post, generate_linkedin_carousel_outline,
generate_linkedin_hooks, linkedin_post_analytics, create_twitter_thread,
generate_tweet, repurpose_to_twitter_thread, twitter_thread_analytics.

Each BlogPublisher/LinkedInPublisher/TwitterEngine test patches the getter
with a fresh instance — these are singletons that accumulate state
(_posts/_threads), so sharing one across tests would make "empty state"
assertions order-dependent.

Exercised through AriaMind._execute_tool exactly as a live conversation
would, not by calling the engines directly.
"""

from __future__ import annotations

import importlib
from unittest.mock import patch

import pytest

from apps.core.cognition.aria_mind import AriaMind
from apps.distribution.blog.blog_publisher import BlogPublisher
from apps.distribution.linkedin.linkedin_publisher import LinkedInPublisher
from apps.distribution.twitter.twitter_engine import TwitterEngine


class _FakeCache:
    def __init__(self):
        self._store = {}

    async def get(self, key):
        return self._store.get(key)

    async def set(self, key, value, ttl_seconds=3600):
        self._store[key] = value
        return True


def test_fabricated_media_pipeline_module_is_gone():
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module("apps.infra.media_workers.media_pipeline")


# ── DifferentiationEngine ─────────────────────────────────────────────
async def test_analyze_content_originality_reachable_from_tool_dispatch():
    mind = AriaMind()
    obs, media = await mind._execute_tool(
        "analyze_content_originality",
        {"content": "In today's fast-paced world, this is a game-changer."},
    )

    assert media == {}
    assert "Originality check" in obs
    assert "game-changer" in obs


async def test_analyze_content_originality_requires_content():
    mind = AriaMind()
    obs, media = await mind._execute_tool("analyze_content_originality", {})

    assert media == {}
    assert "content" in obs.lower()


async def test_purge_generic_phrases_reachable_from_tool_dispatch():
    mind = AriaMind()
    obs, media = await mind._execute_tool(
        "purge_generic_phrases", {"content": "This is a real game-changer for our team."}
    )

    assert media == {}
    assert "Rewritten" in obs
    assert "game-changer" not in obs.lower()


async def test_generate_unique_angles_reachable_from_tool_dispatch():
    mind = AriaMind()
    obs, media = await mind._execute_tool(
        "generate_unique_angles", {"topic": "yoga", "niche": "wellness"}
    )

    assert media == {}
    assert "Unique angles" in obs


async def test_check_audience_fatigue_requires_history():
    mind = AriaMind()
    obs, media = await mind._execute_tool("check_audience_fatigue", {})

    assert media == {}
    assert "content" in obs.lower()


async def test_check_audience_fatigue_reachable_from_tool_dispatch():
    mind = AriaMind()
    obs, media = await mind._execute_tool(
        "check_audience_fatigue",
        {
            "content_history": [
                "leverage synergies to leverage synergies today",
                "leverage synergies once more",
            ]
        },
    )

    assert media == {}
    assert "Audience fatigue risk" in obs


# ── BlogPublisher ──────────────────────────────────────────────────────
async def test_write_blog_post_reachable_from_tool_dispatch():
    engine = BlogPublisher()
    with (
        patch("apps.distribution.blog.blog_publisher.get_cache", return_value=_FakeCache()),
        patch("apps.distribution.blog.blog_publisher.get_blog_publisher", return_value=engine),
    ):
        mind = AriaMind()
        obs, media = await mind._execute_tool(
            "write_blog_post",
            {"topic": "yoga for beginners", "target_keyword": "yoga for beginners"},
        )

    assert media == {}
    assert "yoga" in obs.lower()
    assert "est." in obs.lower()


async def test_write_blog_post_requires_topic_and_keyword():
    mind = AriaMind()
    obs, media = await mind._execute_tool("write_blog_post", {"topic": "yoga"})

    assert media == {}
    assert "keyword" in obs.lower()


async def test_generate_blog_outline_reachable_from_tool_dispatch():
    engine = BlogPublisher()
    with (
        patch("apps.distribution.blog.blog_publisher.get_cache", return_value=_FakeCache()),
        patch("apps.distribution.blog.blog_publisher.get_blog_publisher", return_value=engine),
    ):
        mind = AriaMind()
        obs, media = await mind._execute_tool(
            "generate_blog_outline", {"topic": "yoga", "keyword": "yoga for beginners"}
        )

    assert media == {}
    assert "Blog outline" in obs


async def test_generate_blog_topic_cluster_reachable_from_tool_dispatch():
    engine = BlogPublisher()
    with (
        patch("apps.distribution.blog.blog_publisher.get_cache", return_value=_FakeCache()),
        patch("apps.distribution.blog.blog_publisher.get_blog_publisher", return_value=engine),
    ):
        mind = AriaMind()
        obs, media = await mind._execute_tool(
            "generate_blog_topic_cluster", {"pillar_topic": "yoga"}
        )

    assert media == {}
    assert "Topic cluster" in obs


async def test_blog_publishing_stats_empty_state():
    engine = BlogPublisher()
    with (
        patch("apps.distribution.blog.blog_publisher.get_cache", return_value=_FakeCache()),
        patch("apps.distribution.blog.blog_publisher.get_blog_publisher", return_value=engine),
    ):
        mind = AriaMind()
        obs, media = await mind._execute_tool("blog_publishing_stats", {})

    assert media == {}
    assert "no blog posts" in obs.lower()


# ── LinkedInPublisher ──────────────────────────────────────────────────
async def test_create_linkedin_post_reachable_from_tool_dispatch():
    engine = LinkedInPublisher()
    with (
        patch("apps.distribution.linkedin.linkedin_publisher.get_cache", return_value=_FakeCache()),
        patch(
            "apps.distribution.linkedin.linkedin_publisher.get_linkedin_publisher",
            return_value=engine,
        ),
    ):
        mind = AriaMind()
        obs, media = await mind._execute_tool("create_linkedin_post", {"topic": "remote work"})

    assert media == {}
    assert "LinkedIn post" in obs


async def test_create_linkedin_post_requires_topic():
    mind = AriaMind()
    obs, media = await mind._execute_tool("create_linkedin_post", {})

    assert media == {}
    assert "topic" in obs.lower()


async def test_generate_linkedin_carousel_outline_reachable_from_tool_dispatch():
    engine = LinkedInPublisher()
    with (
        patch("apps.distribution.linkedin.linkedin_publisher.get_cache", return_value=_FakeCache()),
        patch(
            "apps.distribution.linkedin.linkedin_publisher.get_linkedin_publisher",
            return_value=engine,
        ),
    ):
        mind = AriaMind()
        obs, media = await mind._execute_tool(
            "generate_linkedin_carousel_outline", {"topic": "remote work", "num_slides": 5}
        )

    assert media == {}
    assert "Carousel" in obs


async def test_generate_linkedin_hooks_reachable_from_tool_dispatch():
    engine = LinkedInPublisher()
    with (
        patch("apps.distribution.linkedin.linkedin_publisher.get_cache", return_value=_FakeCache()),
        patch(
            "apps.distribution.linkedin.linkedin_publisher.get_linkedin_publisher",
            return_value=engine,
        ),
    ):
        mind = AriaMind()
        obs, media = await mind._execute_tool("generate_linkedin_hooks", {"topic": "remote work"})

    assert media == {}
    assert "Hook variants" in obs


async def test_linkedin_post_analytics_empty_state():
    engine = LinkedInPublisher()
    with (
        patch("apps.distribution.linkedin.linkedin_publisher.get_cache", return_value=_FakeCache()),
        patch(
            "apps.distribution.linkedin.linkedin_publisher.get_linkedin_publisher",
            return_value=engine,
        ),
    ):
        mind = AriaMind()
        obs, media = await mind._execute_tool("linkedin_post_analytics", {})

    assert media == {}
    assert "no linkedin posts" in obs.lower()


# ── TwitterEngine ───────────────────────────────────────────────────────
async def test_create_twitter_thread_reachable_from_tool_dispatch():
    engine = TwitterEngine()
    with (
        patch("apps.distribution.twitter.twitter_engine.get_cache", return_value=_FakeCache()),
        patch("apps.distribution.twitter.twitter_engine.get_twitter_engine", return_value=engine),
    ):
        mind = AriaMind()
        obs, media = await mind._execute_tool(
            "create_twitter_thread", {"topic": "productivity", "num_tweets": 5}
        )

    assert media == {}
    assert "Thread:" in obs


async def test_create_twitter_thread_requires_topic():
    mind = AriaMind()
    obs, media = await mind._execute_tool("create_twitter_thread", {})

    assert media == {}
    assert "topic" in obs.lower()


async def test_generate_tweet_reachable_from_tool_dispatch():
    engine = TwitterEngine()
    with (
        patch("apps.distribution.twitter.twitter_engine.get_cache", return_value=_FakeCache()),
        patch("apps.distribution.twitter.twitter_engine.get_twitter_engine", return_value=engine),
    ):
        mind = AriaMind()
        obs, media = await mind._execute_tool(
            "generate_tweet", {"topic": "productivity", "tweet_type": "tip"}
        )

    assert media == {}
    assert "Tweet:" in obs


async def test_repurpose_to_twitter_thread_reachable_from_tool_dispatch():
    engine = TwitterEngine()
    with (
        patch("apps.distribution.twitter.twitter_engine.get_cache", return_value=_FakeCache()),
        patch("apps.distribution.twitter.twitter_engine.get_twitter_engine", return_value=engine),
    ):
        mind = AriaMind()
        obs, media = await mind._execute_tool(
            "repurpose_to_twitter_thread",
            {
                "long_content": "A long article about productivity tips" * 20,
                "topic": "productivity",
            },
        )

    assert media == {}
    assert "Repurposed thread" in obs


async def test_twitter_thread_analytics_empty_state():
    engine = TwitterEngine()
    with (
        patch("apps.distribution.twitter.twitter_engine.get_cache", return_value=_FakeCache()),
        patch("apps.distribution.twitter.twitter_engine.get_twitter_engine", return_value=engine),
    ):
        mind = AriaMind()
        obs, media = await mind._execute_tool("twitter_thread_analytics", {})

    assert media == {}
    assert "no twitter" in obs.lower()
