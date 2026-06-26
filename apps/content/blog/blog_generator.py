"""
Autonomous blog post generator.
Generates SEO-optimized blog posts in markdown with AI or template fallback.
"""

from __future__ import annotations

import logging
import re
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta

from apps.core.memory.redis_client import get_cache
from apps.core.tools.ai_client import AIModel, get_ai_client

logger = logging.getLogger("aria.content.blog")

_CACHE_KEY = "content:blog:v1"
_CACHE_TTL = 86400 * 90  # 90 days

_SERIES_ANGLES = [
    "beginner's complete guide",
    "ultimate comparison and review",
    "real-world case study",
    "actionable tips and tricks",
    "expert review and analysis",
]

_BUYER_INTENT_CTAS = {
    "buy": "Ready to purchase? Click here to get the best deal today.",
    "best": "Find the best options — compare top picks and choose yours.",
    "review": "Read more in-depth reviews and make an informed decision.",
    "vs": "Still deciding? See our full comparison chart.",
    "cheap": "Get the lowest prices — check current deals now.",
    "default": "Start today — sign up free and see results in 30 days.",
}


# ── Data models ────────────────────────────────────────────────────────────────


@dataclass
class BlogPost:
    post_id: str
    title: str
    slug: str
    meta_description: str
    content: str  # markdown
    word_count: int
    target_keyword: str
    secondary_keywords: list[str]
    cta: str
    internal_links: list[str]
    estimated_traffic: int
    created_at: float
    status: str  # "draft" | "ready" | "published"

    def to_dict(self) -> dict:
        return {
            "post_id": self.post_id,
            "title": self.title,
            "slug": self.slug,
            "meta_description": self.meta_description,
            "content": self.content,
            "word_count": self.word_count,
            "target_keyword": self.target_keyword,
            "secondary_keywords": self.secondary_keywords,
            "cta": self.cta,
            "internal_links": self.internal_links,
            "estimated_traffic": self.estimated_traffic,
            "created_at": self.created_at,
            "status": self.status,
        }


# ── Helpers ────────────────────────────────────────────────────────────────────


def _slugify(title: str) -> str:
    slug = re.sub(r"[^\w\s-]", "", title.lower())
    slug = re.sub(r"[\s_-]+", "-", slug)
    return slug.strip("-")[:80]


def _extract_title(content: str) -> str:
    match = re.search(r"^#\s+(.+)$", content, re.MULTILINE)
    return match.group(1).strip() if match else ""


def _extract_meta(content: str) -> str:
    """Extract first paragraph as meta description."""
    paragraphs = [p.strip() for p in content.split("\n\n") if p.strip() and not p.startswith("#")]
    return paragraphs[0][:160] if paragraphs else ""


def _get_cta(keyword: str) -> str:
    kw_lower = keyword.lower()
    for trigger, cta in _BUYER_INTENT_CTAS.items():
        if trigger in kw_lower:
            return cta
    return _BUYER_INTENT_CTAS["default"]


def _template_post(keyword: str, word_count: int = 800) -> str:
    """Generate a minimal template blog post when AI is unavailable."""
    return f"""# The Complete Guide to {keyword.title()}

If you're looking to master {keyword}, you've come to the right place. This guide covers everything you need to know to get started and see real results.

## What Is {keyword.title()}?

{keyword.title()} is a powerful approach used by thousands of successful businesses and individuals. Understanding the fundamentals is the first step toward achieving your goals.

## Why {keyword.title()} Matters

In today's competitive landscape, {keyword} can make the difference between success and failure. Here are the top reasons to invest your time and energy:

- Proven results backed by data
- Scalable approach that grows with you
- Low barrier to entry for beginners
- High ROI when implemented correctly

## How to Get Started with {keyword.title()}

Follow these steps to launch your {keyword} strategy today:

1. **Research your audience** — Understand who you're targeting and what they need
2. **Set clear goals** — Define what success looks like for your {keyword} efforts
3. **Choose the right tools** — Select platforms and software that fit your budget
4. **Create a content plan** — Map out your approach for the next 30, 60, and 90 days
5. **Track and optimize** — Measure results and iterate based on data

## Common {keyword.title()} Mistakes to Avoid

Many beginners make costly mistakes when starting with {keyword}. Avoid these pitfalls:

- Skipping the research phase
- Trying to do everything at once
- Ignoring analytics and data
- Giving up too soon before seeing results

## Final Thoughts

{keyword.title()} is one of the most powerful tools available to modern businesses. With the right strategy and consistent effort, you can achieve remarkable results.

**Ready to get started?** Take the first step today and watch your results grow.
"""


# ── Main class ─────────────────────────────────────────────────────────────────


class BlogGenerator:
    """Autonomous blog post generator with AI content creation and persistence."""

    def __init__(self) -> None:
        self._ai = get_ai_client()
        self._posts: list[dict] = []
        self._loaded = False

    async def _load(self) -> None:
        if self._loaded:
            return
        try:
            cache = get_cache()
            data = await cache.get(_CACHE_KEY)
            if data and isinstance(data, list):
                self._posts = data
        except Exception as exc:
            logger.warning("BlogGenerator._load failed: %s", exc)
        self._loaded = True

    async def _save(self) -> None:
        try:
            cache = get_cache()
            await cache.set(_CACHE_KEY, self._posts, ttl_seconds=_CACHE_TTL)
        except Exception as exc:
            logger.warning("BlogGenerator._save failed: %s", exc)

    async def generate_post(
        self,
        keyword: str,
        audience: str = "general",
        word_count: int = 800,
    ) -> BlogPost:
        """Generate a full SEO-optimized blog post in markdown."""
        await self._load()

        content = ""
        try:
            resp = await self._ai.complete(
                system=(
                    "You are an expert content marketer who writes high-converting, "
                    "SEO-optimized blog posts that rank and convert. "
                    "No AI fluff. Specific, actionable, original."
                ),
                user=(
                    f"Write a {word_count}-word blog post targeting the keyword: '{keyword}'.\n"
                    f"Audience: {audience}.\n\n"
                    "Format requirements:\n"
                    "- Start with '# Title' on the first line\n"
                    "- Include 4-5 H2 sections with substantial content\n"
                    "- Add a strong CTA paragraph at the end\n"
                    "- Use markdown formatting\n"
                    "- Be specific and actionable, avoid generic advice"
                ),
                model=AIModel.CREATIVE,
                max_tokens=2000,
                agent_name="blog_generator",
            )
            if resp.success and resp.content:
                content = resp.content
        except Exception as exc:
            logger.warning("BlogGenerator.generate_post AI failed: %s", exc)

        if not content:
            content = _template_post(keyword, word_count)

        # Extract metadata from content
        title = _extract_title(content) or f"The Complete Guide to {keyword.title()}"
        slug = _slugify(title)
        meta_description = _extract_meta(content)
        actual_word_count = len(content.split())
        cta = _get_cta(keyword)

        # Estimate traffic (3% CTR of simulated ~5000 avg volume)
        estimated_traffic = max(10, int(5000 * 0.03))

        post = BlogPost(
            post_id=str(uuid.uuid4()),
            title=title,
            slug=slug,
            meta_description=meta_description,
            content=content,
            word_count=actual_word_count,
            target_keyword=keyword,
            secondary_keywords=[f"{keyword} guide", f"best {keyword}", f"{keyword} tips"],
            cta=cta,
            internal_links=[],
            estimated_traffic=estimated_traffic,
            created_at=time.time(),
            status="draft",
        )
        self._posts.append(post.to_dict())
        await self._save()
        return post

    async def generate_series(self, topic: str, count: int = 5) -> list[BlogPost]:
        """Generate N posts on a topic with different angles."""
        await self._load()
        posts: list[BlogPost] = []
        angles = _SERIES_ANGLES[:count]
        for angle in angles:
            keyword = f"{topic} {angle}"
            post = await self.generate_post(keyword=keyword, audience="general", word_count=800)
            posts.append(post)
        return posts

    async def get_publishing_schedule(
        self,
        posts: list[BlogPost],
        posts_per_week: int = 3,
    ) -> list[dict]:
        """Return a publishing schedule with post titles and planned dates."""
        schedule = []
        start = datetime.utcnow()
        interval_days = max(1, 7 // posts_per_week)
        for i, post in enumerate(posts):
            publish_date = start + timedelta(days=i * interval_days)
            schedule.append(
                {
                    "post_id": post.post_id,
                    "title": post.title,
                    "planned_date": publish_date.strftime("%Y-%m-%d"),
                    "keyword": post.target_keyword,
                    "status": post.status,
                }
            )
        return schedule

    def draft_posts(self) -> list[dict]:
        """Return posts with status 'draft' or 'ready'."""
        return [p for p in self._posts if p.get("status") in ("draft", "ready")]

    def stats(self) -> dict:
        if not self._posts:
            return {"total_posts": 0, "avg_word_count": 0, "estimated_monthly_traffic": 0}
        total = len(self._posts)
        avg_wc = int(sum(p.get("word_count", 0) for p in self._posts) / total)
        monthly_traffic = sum(p.get("estimated_traffic", 0) for p in self._posts)
        return {
            "total_posts": total,
            "avg_word_count": avg_wc,
            "estimated_monthly_traffic": monthly_traffic,
        }


# ── Singleton ──────────────────────────────────────────────────────────────────

_blog_generator: BlogGenerator | None = None


def get_blog_generator() -> BlogGenerator:
    global _blog_generator
    if _blog_generator is None:
        _blog_generator = BlogGenerator()
    return _blog_generator
