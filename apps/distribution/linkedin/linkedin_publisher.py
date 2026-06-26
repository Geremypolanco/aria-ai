"""
ARIA AI — LinkedIn Publisher
Phase 13: Authority content creation and distribution on LinkedIn.
Drives B2B leads, thought leadership, and brand awareness.
"""

from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass, field

from apps.core.memory.redis_client import get_cache
from apps.core.tools.ai_client import AIModel, get_ai_client

logger = logging.getLogger("aria.distribution.linkedin")

_KEY = "distribution:linkedin:v1"
_TTL = 86400 * 30


@dataclass
class LinkedInPost:
    post_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    topic: str = ""
    content: str = ""
    hook: str = ""
    hashtags: list = field(default_factory=list)
    cta: str = ""
    content_type: str = "thought_leadership"
    engagement_score: float = 0.0
    estimated_impressions: int = 0
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            "post_id": self.post_id,
            "topic": self.topic,
            "content": self.content,
            "hook": self.hook,
            "hashtags": self.hashtags,
            "cta": self.cta,
            "content_type": self.content_type,
            "engagement_score": self.engagement_score,
            "estimated_impressions": self.estimated_impressions,
            "created_at": self.created_at,
        }


class LinkedInPublisher:

    def __init__(self) -> None:
        self._posts: list[dict] = []
        self._loaded = False

    async def _load(self) -> None:
        if self._loaded:
            return
        try:
            cache = get_cache()
            data = await cache.get(_KEY)
            if isinstance(data, list):
                self._posts = data
        except Exception as exc:
            logger.warning("LinkedInPublisher._load failed: %s", exc)
        self._loaded = True

    async def _save(self) -> None:
        try:
            cache = get_cache()
            await cache.set(_KEY, self._posts[-1000:], ttl_seconds=_TTL)
        except Exception as exc:
            logger.warning("LinkedInPublisher._save failed: %s", exc)

    async def create_post(self, topic: str, objective: str = "thought_leadership") -> LinkedInPost:
        await self._load()

        content = ""
        hashtags: list[str] = []
        cta = ""

        try:
            ai = get_ai_client()
            resp = await ai.complete(
                system=(
                    "You are an expert LinkedIn content strategist. Write a LinkedIn post that:\n"
                    "- Starts with a single attention-grabbing hook line (first line only, no hashtags)\n"
                    "- Is under 1300 characters total\n"
                    "- Uses short paragraphs (1-2 sentences max) for mobile readability\n"
                    "- Ends with a CTA followed by an open question to drive comments\n"
                    "- Includes 3-5 relevant hashtags on a new line at the end\n"
                    "Do not include any preamble. Output only the post text."
                ),
                user=f"Topic: {topic}\nObjective: {objective}",
                model=AIModel.CREATIVE,
                max_tokens=600,
            )
            if resp.success:
                content = resp.content.strip()
                lines = content.split("\n")
                hook = lines[0].strip() if lines else topic
                hashtags = [w for w in content.split() if w.startswith("#")]
                cta_line = next(
                    (l for l in reversed(lines) if l.strip() and not l.startswith("#")),
                    "",
                )
                cta = cta_line.strip()
        except Exception as exc:
            logger.warning("LinkedInPublisher.create_post AI call failed: %s", exc)

        if not content:
            hook = f"Most people get {topic} completely wrong."
            hashtags = [f"#{topic.replace(' ', '')}", "#LinkedInTips", "#B2B"]
            cta = f"What's your experience with {topic}? Share below."
            content = (
                f"{hook}\n\n"
                f"Here's what the top 1% know about {topic} that others don't:\n\n"
                f"→ It's not about working harder, it's about working smarter.\n"
                f"→ The fundamentals matter more than any hack.\n"
                f"→ Consistency beats intensity every single time.\n\n"
                f"{cta}\n\n" + " ".join(hashtags)
            )

        lines = content.split("\n")
        hook = lines[0].strip() if lines else topic

        engagement_score = min(0.3 + len(content) / 3000, 0.95)
        estimated_impressions = int(engagement_score * 5000)

        post = LinkedInPost(
            topic=topic,
            content=content,
            hook=hook,
            hashtags=hashtags,
            cta=cta,
            content_type=objective,
            engagement_score=round(engagement_score, 3),
            estimated_impressions=estimated_impressions,
        )
        self._posts.append(post.to_dict())
        await self._save()
        return post

    async def optimize_for_algorithm(self, post: LinkedInPost) -> LinkedInPost:
        await self._load()

        optimized_content = ""

        try:
            ai = get_ai_client()
            resp = await ai.complete(
                system=(
                    "You are a LinkedIn algorithm expert. Rewrite the post to maximize dwell time:\n"
                    "- Start with a scroll-stopping question or bold statement\n"
                    "- Use line breaks after every 1-2 sentences\n"
                    "- Use → or • as bullet markers (no standard dashes)\n"
                    "- Add 1-2 strategic emojis only where they aid scanning\n"
                    "- Keep under 1300 characters\n"
                    "- End with a direct question to the reader\n"
                    "Output only the rewritten post."
                ),
                user=f"Original post:\n{post.content}",
                model=AIModel.CREATIVE,
                max_tokens=600,
            )
            if resp.success:
                optimized_content = resp.content.strip()
        except Exception as exc:
            logger.warning("LinkedInPublisher.optimize_for_algorithm AI call failed: %s", exc)

        if not optimized_content:
            optimized_content = post.content

        lines = optimized_content.split("\n")
        new_hook = lines[0].strip() if lines else post.hook
        engagement_score = min(0.3 + len(optimized_content) / 3000, 0.95)

        optimized = LinkedInPost(
            topic=post.topic,
            content=optimized_content,
            hook=new_hook,
            hashtags=post.hashtags,
            cta=post.cta,
            content_type=post.content_type,
            engagement_score=round(engagement_score, 3),
            estimated_impressions=int(engagement_score * 5000),
        )
        self._posts.append(optimized.to_dict())
        await self._save()
        return optimized

    async def generate_carousel_outline(self, topic: str, num_slides: int = 7) -> dict:
        await self._load()

        try:
            ai = get_ai_client()
            resp = await ai.complete(
                system=(
                    "You are a LinkedIn carousel content expert. Generate a carousel outline as JSON.\n"
                    "Return a JSON object with keys: topic, cover_text, hook, slides.\n"
                    "slides is a list of objects with keys: slide (int), headline (str), content (str).\n"
                    "Each slide headline should be punchy (max 8 words). Content is 1-2 sentences.\n"
                    "Return only valid JSON, no markdown fences."
                ),
                user=f"Topic: {topic}\nNumber of slides: {num_slides}",
                model=AIModel.STRATEGY,
                max_tokens=900,
            )
            if resp.success:
                import json

                raw = resp.content.strip()
                # Strip markdown code fences if model includes them despite instructions
                if raw.startswith("```"):
                    raw = raw.split("```")[1]
                    if raw.startswith("json"):
                        raw = raw[4:]
                outline = json.loads(raw.strip())
                return outline
        except Exception as exc:
            logger.warning("LinkedInPublisher.generate_carousel_outline AI call failed: %s", exc)

        slides = [
            {
                "slide": i + 1,
                "headline": f"Point {i + 1} about {topic}",
                "content": f"Key insight #{i + 1} on {topic}.",
            }
            for i in range(num_slides)
        ]
        return {
            "topic": topic,
            "cover_text": f"Everything you need to know about {topic}",
            "hook": f"Here are {num_slides} things about {topic} that changed everything for me:",
            "slides": slides,
        }

    async def generate_hook_variants(self, topic: str) -> list[str]:
        await self._load()

        try:
            ai = get_ai_client()
            resp = await ai.complete(
                system=(
                    "You are a LinkedIn hook specialist. Generate 5 distinct first-line hooks "
                    "for a LinkedIn post. Each hook must:\n"
                    "- Be under 120 characters\n"
                    "- Stop the scroll immediately\n"
                    "- Create curiosity, urgency, or a pattern interrupt\n"
                    "Output one hook per line, numbered 1-5. No extra text."
                ),
                user=f"Topic: {topic}",
                model=AIModel.CREATIVE,
                max_tokens=400,
            )
            if resp.success:
                lines = [
                    l.lstrip("0123456789.-) ").strip()
                    for l in resp.content.strip().split("\n")
                    if l.strip()
                ]
                hooks = [l for l in lines if l][:5]
                if hooks:
                    return hooks
        except Exception as exc:
            logger.warning("LinkedInPublisher.generate_hook_variants AI call failed: %s", exc)

        return [
            f"Most people get {topic} wrong — here's the truth:",
            f"I wasted 2 years on {topic} before I learned this:",
            f"Nobody talks about the dark side of {topic}:",
            f"The {topic} advice that 10x'd my results (it's not what you think):",
            f"Stop doing {topic} the hard way. Do this instead:",
        ][:3]

    def post_analytics(self) -> dict:
        by_type: dict[str, int] = {}
        total_engagement = 0.0
        total_impressions = 0

        for p in self._posts:
            ct = p.get("content_type", "unknown")
            by_type[ct] = by_type.get(ct, 0) + 1
            total_engagement += p.get("engagement_score", 0.0)
            total_impressions += p.get("estimated_impressions", 0)

        count = len(self._posts)
        return {
            "total_posts": count,
            "by_type": by_type,
            "avg_engagement_score": round(total_engagement / count, 3) if count else 0.0,
            "avg_impressions": total_impressions // count if count else 0,
        }

    def recent_posts(self, limit: int = 10) -> list[dict]:
        return self._posts[-limit:]


_instance: LinkedInPublisher | None = None


def get_linkedin_publisher() -> LinkedInPublisher:
    global _instance
    if _instance is None:
        _instance = LinkedInPublisher()
    return _instance
