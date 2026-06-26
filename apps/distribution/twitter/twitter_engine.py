"""
ARIA AI — Twitter/X Thread Engine
Phase 13: Viral thread creation, tweet optimization, and X distribution.
Drives traffic, followers, and brand authority.
"""

from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass, field

from apps.core.memory.redis_client import get_cache
from apps.core.tools.ai_client import AIModel, get_ai_client

logger = logging.getLogger("aria.distribution.twitter")

_KEY = "distribution:twitter:v1"
_TTL = 86400 * 30


@dataclass
class Tweet:
    tweet_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    content: str = ""
    thread_position: int = 0
    hashtags: list = field(default_factory=list)
    has_cta: bool = False

    def to_dict(self) -> dict:
        return {
            "tweet_id": self.tweet_id,
            "content": self.content,
            "thread_position": self.thread_position,
            "hashtags": self.hashtags,
            "has_cta": self.has_cta,
        }


@dataclass
class TwitterThread:
    thread_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    topic: str = ""
    tweets: list = field(default_factory=list)
    hook: str = ""
    total_tweets: int = 0
    estimated_reach: int = 0
    viral_score: float = 0.0
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            "thread_id": self.thread_id,
            "topic": self.topic,
            "tweets": self.tweets,
            "hook": self.hook,
            "total_tweets": self.total_tweets,
            "estimated_reach": self.estimated_reach,
            "viral_score": self.viral_score,
            "created_at": self.created_at,
        }


class TwitterEngine:

    def __init__(self) -> None:
        self._threads: list[dict] = []
        self._loaded = False

    async def _load(self) -> None:
        if self._loaded:
            return
        try:
            cache = get_cache()
            data = await cache.get(_KEY)
            if isinstance(data, list):
                self._threads = data
        except Exception as exc:
            logger.warning("TwitterEngine._load failed: %s", exc)
        self._loaded = True

    async def _save(self) -> None:
        try:
            cache = get_cache()
            await cache.set(_KEY, self._threads[-1000:], ttl_seconds=_TTL)
        except Exception as exc:
            logger.warning("TwitterEngine._save failed: %s", exc)

    def _parse_tweets_from_text(self, text: str, topic: str) -> list[Tweet]:
        paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
        if not paragraphs:
            paragraphs = [p.strip() for p in text.split("\n") if p.strip()]

        tweets: list[Tweet] = []
        for i, para in enumerate(paragraphs):
            content = para[:280]
            hashtags = [w for w in content.split() if w.startswith("#")]
            is_cta = i == len(paragraphs) - 1
            tweets.append(
                Tweet(
                    content=content,
                    thread_position=i,
                    hashtags=hashtags,
                    has_cta=is_cta,
                )
            )
        return tweets

    def _build_fallback_thread(self, topic: str, num_tweets: int) -> list[Tweet]:
        items = [
            Tweet(
                content=f"🧵 {num_tweets} things about {topic} that will change how you think:\n\n(thread)",
                thread_position=0,
            ),
        ]
        for i in range(1, num_tweets - 1):
            items.append(
                Tweet(
                    content=f"{i}/ Key insight about {topic}: understanding this will save you months of trial and error.",
                    thread_position=i,
                )
            )
        items.append(
            Tweet(
                content=f"If this thread on {topic} helped you, follow me for more.\n\nRetweet the first tweet to help others too. 🙏",
                thread_position=num_tweets - 1,
                has_cta=True,
            )
        )
        return items

    async def create_thread(
        self,
        topic: str,
        angle: str = "educational",
        num_tweets: int = 7,
    ) -> TwitterThread:
        await self._load()

        tweets: list[Tweet] = []

        try:
            ai = get_ai_client()
            resp = await ai.complete(
                system=(
                    f"You are a viral Twitter/X thread writer. Write a {num_tweets}-tweet thread.\n"
                    "Rules:\n"
                    f"- Tweet 1 (hook): ≤240 chars, grabs attention immediately, ends with (thread) or 🧵\n"
                    "- Tweets 2 to N-1 (body): ≤260 chars each, one insight per tweet, numbered e.g. '2/'\n"
                    "- Last tweet (CTA): ask followers, retweet request, or follow CTA\n"
                    "- Separate each tweet with a blank line\n"
                    "- No hashtags except on the last tweet (max 2)\n"
                    "Output only the tweets, nothing else."
                ),
                user=f"Topic: {topic}\nAngle: {angle}",
                model=AIModel.CREATIVE,
                max_tokens=900,
            )
            if resp.success:
                tweets = self._parse_tweets_from_text(resp.content, topic)
        except Exception as exc:
            logger.warning("TwitterEngine.create_thread AI call failed: %s", exc)

        if not tweets:
            tweets = self._build_fallback_thread(topic, num_tweets)

        tweet_dicts = [t.to_dict() for t in tweets]
        viral_score = min(0.4 + len(tweets) * 0.05, 0.95)
        estimated_reach = int(viral_score * 10000)
        hook = tweets[0].content if tweets else topic

        thread = TwitterThread(
            topic=topic,
            tweets=tweet_dicts,
            hook=hook,
            total_tweets=len(tweets),
            estimated_reach=estimated_reach,
            viral_score=round(viral_score, 3),
        )
        self._threads.append(thread.to_dict())
        await self._save()
        return thread

    async def optimize_hook(self, topic: str) -> str:
        await self._load()

        try:
            ai = get_ai_client()
            resp = await ai.complete(
                system=(
                    "You are a Twitter hook specialist. Write the single best opening tweet "
                    "for a thread on the given topic.\n"
                    "Rules: ≤240 chars, creates immediate curiosity, ends with (thread) or 🧵.\n"
                    "Output only the hook text, nothing else."
                ),
                user=f"Topic: {topic}",
                model=AIModel.CREATIVE,
                max_tokens=100,
            )
            if resp.success:
                hook = resp.content.strip()[:240]
                if hook:
                    return hook
        except Exception as exc:
            logger.warning("TwitterEngine.optimize_hook AI call failed: %s", exc)

        num = 7
        return f"🧵 {num} things about {topic} that will change how you think:"

    async def generate_tweet(self, topic: str, tweet_type: str = "insight") -> Tweet:
        await self._load()

        content = ""

        type_instructions = {
            "insight": "Share one sharp, non-obvious insight. Confident, punchy. No fluff.",
            "question": "Ask a thought-provoking question that sparks debate or reflection.",
            "stat": "Lead with a surprising statistic or data point, then explain why it matters.",
            "tip": "Give one actionable tip. Start with a verb. Make it immediately usable.",
            "cta": "Write a clear call-to-action tweet. Tell the reader exactly what to do next.",
        }
        instruction = type_instructions.get(tweet_type, type_instructions["insight"])

        try:
            ai = get_ai_client()
            resp = await ai.complete(
                system=(
                    f"You are a Twitter content expert. Write a single tweet about the given topic.\n"
                    f"Type: {tweet_type}. {instruction}\n"
                    "Rules: ≤280 characters. Include 1-2 hashtags if natural. Output only the tweet."
                ),
                user=f"Topic: {topic}",
                model=AIModel.FAST,
                max_tokens=120,
            )
            if resp.success:
                content = resp.content.strip()[:280]
        except Exception as exc:
            logger.warning("TwitterEngine.generate_tweet AI call failed: %s", exc)

        if not content:
            content = f"The most underrated thing about {topic}: most people skip the fundamentals. Don't. #{topic.replace(' ', '')}"

        hashtags = [w for w in content.split() if w.startswith("#")]
        has_cta = tweet_type == "cta"

        return Tweet(
            content=content,
            thread_position=0,
            hashtags=hashtags,
            has_cta=has_cta,
        )

    async def repurpose_to_thread(self, long_content: str, topic: str) -> TwitterThread:
        await self._load()

        tweets: list[Tweet] = []

        try:
            ai = get_ai_client()
            resp = await ai.complete(
                system=(
                    "You are a Twitter content repurposer. Break long-form content into a tweet thread.\n"
                    "Rules:\n"
                    "- First tweet: hook ≤240 chars ending with 🧵 or (thread)\n"
                    "- Body tweets: ≤260 chars, one key point per tweet, numbered '2/', '3/' etc.\n"
                    "- Final tweet: CTA or summary ≤280 chars\n"
                    "- Separate tweets with a blank line\n"
                    "- Preserve the most impactful insights from the source content\n"
                    "Output only the tweets."
                ),
                user=f"Topic: {topic}\n\nContent to repurpose:\n{long_content[:3000]}",
                model=AIModel.STRATEGY,
                max_tokens=1000,
            )
            if resp.success:
                tweets = self._parse_tweets_from_text(resp.content, topic)
        except Exception as exc:
            logger.warning("TwitterEngine.repurpose_to_thread AI call failed: %s", exc)

        if not tweets:
            tweets = self._build_fallback_thread(topic, 7)

        tweet_dicts = [t.to_dict() for t in tweets]
        viral_score = min(0.4 + len(tweets) * 0.05, 0.95)
        estimated_reach = int(viral_score * 10000)
        hook = tweets[0].content if tweets else topic

        thread = TwitterThread(
            topic=topic,
            tweets=tweet_dicts,
            hook=hook,
            total_tweets=len(tweets),
            estimated_reach=estimated_reach,
            viral_score=round(viral_score, 3),
        )
        self._threads.append(thread.to_dict())
        await self._save()
        return thread

    def twitter_analytics(self) -> dict:
        total_tweets = sum(t.get("total_tweets", 0) for t in self._threads)
        total_viral = sum(t.get("viral_score", 0.0) for t in self._threads)
        total_reach = sum(t.get("estimated_reach", 0) for t in self._threads)
        count = len(self._threads)
        return {
            "total_threads": count,
            "total_tweets": total_tweets,
            "avg_viral_score": round(total_viral / count, 3) if count else 0.0,
            "avg_estimated_reach": total_reach // count if count else 0,
        }

    def recent_threads(self, limit: int = 10) -> list[dict]:
        return self._threads[-limit:]


_instance: TwitterEngine | None = None


def get_twitter_engine() -> TwitterEngine:
    global _instance
    if _instance is None:
        _instance = TwitterEngine()
    return _instance
