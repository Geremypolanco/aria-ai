"""
ARIA AI — SEO Blog Publisher
Phase 13: Automated SEO blog post creation, optimization, and multi-platform distribution.
Drives organic traffic through keyword-targeted long-form content.
"""

from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass, field

from apps.core.memory.redis_client import get_cache
from apps.core.tools.ai_client import AIModel, get_ai_client

logger = logging.getLogger("aria.distribution.blog")

_KEY = "distribution:blog:v1"
_TTL = 86400 * 60


@dataclass
class BlogPost:
    post_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    title: str = ""
    slug: str = ""
    meta_title: str = ""
    meta_description: str = ""
    target_keyword: str = ""
    secondary_keywords: list = field(default_factory=list)
    outline: list = field(default_factory=list)
    body: str = ""
    word_count: int = 0
    seo_score: float = 0.0
    estimated_monthly_traffic: int = 0
    category: str = ""
    internal_links: list = field(default_factory=list)
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            "post_id": self.post_id,
            "title": self.title,
            "slug": self.slug,
            "meta_title": self.meta_title,
            "meta_description": self.meta_description,
            "target_keyword": self.target_keyword,
            "secondary_keywords": self.secondary_keywords,
            "outline": self.outline,
            "body": self.body,
            "word_count": self.word_count,
            "seo_score": self.seo_score,
            "estimated_monthly_traffic": self.estimated_monthly_traffic,
            "category": self.category,
            "internal_links": self.internal_links,
            "created_at": self.created_at,
        }


class BlogPublisher:

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
            logger.warning("BlogPublisher._load failed: %s", exc)
        self._loaded = True

    async def _save(self) -> None:
        try:
            cache = get_cache()
            await cache.set(_KEY, self._posts[-500:], ttl_seconds=_TTL)
        except Exception as exc:
            logger.warning("BlogPublisher._save failed: %s", exc)

    def _make_slug(self, title: str) -> str:
        return title.lower().replace(" ", "-").replace("'", "")[:60]

    def _build_fallback_post(
        self, topic: str, target_keyword: str, word_target: int
    ) -> tuple[str, str]:
        title = f"The Complete Guide to {topic}: Everything You Need to Know"
        body = (
            f"# {title}\n\n"
            f"If you're looking to master {target_keyword}, you've come to the right place.\n"
            f"In this guide, we'll walk through the most important aspects of {topic}.\n\n"
            f"## What Is {topic}?\n\n"
            f"Understanding {target_keyword} starts with the fundamentals. "
            f"Here's what every beginner needs to know before diving in.\n\n"
            f"## Why {topic} Matters\n\n"
            f"The importance of {target_keyword} cannot be overstated in today's landscape. "
            f"Those who invest time in understanding it gain a significant edge.\n\n"
            f"## How to Get Started with {topic}\n\n"
            f"Getting started with {target_keyword} is simpler than most people think. "
            f"Follow these steps to build a solid foundation.\n\n"
            f"## Common Mistakes to Avoid\n\n"
            f"Many beginners struggle with {target_keyword} because of these avoidable pitfalls. "
            f"Learn from others' mistakes to accelerate your progress.\n\n"
            f"## Advanced {topic} Strategies\n\n"
            f"Once you have the basics down, these advanced {target_keyword} techniques will "
            f"take your results to the next level.\n\n"
            f"## Conclusion\n\n"
            f"Mastering {target_keyword} takes time, but the rewards are worth it. "
            f"Start with the basics, stay consistent, and don't hesitate to revisit this guide. "
            f"Ready to go deeper? Subscribe for weekly insights on {topic}."
        )
        return title, body

    async def write_post(
        self,
        topic: str,
        target_keyword: str,
        target_audience: str = "general",
        word_target: int = 1200,
    ) -> BlogPost:
        await self._load()

        title = ""
        body = ""

        try:
            ai = get_ai_client()
            resp = await ai.complete(
                system=(
                    f"You are an SEO content writer. Write a {word_target}-word blog post "
                    f"optimized for '{target_keyword}'. Include: H1 title, intro with keyword "
                    f"in first 100 words, 5 H2 sections, conclusion with CTA. "
                    f"Write for {target_audience}."
                ),
                user=f"Topic: {topic}\nTarget keyword: {target_keyword}\nAudience: {target_audience}",
                model=AIModel.STRATEGY,
                max_tokens=2000,
            )
            if resp.success and resp.content:
                body = resp.content.strip()
                lines = body.splitlines()
                for line in lines:
                    stripped = line.strip().lstrip("#").strip()
                    if stripped:
                        title = stripped
                        break
        except Exception as exc:
            logger.warning("BlogPublisher.write_post AI call failed: %s", exc)

        if not body or not title:
            title, body = self._build_fallback_post(topic, target_keyword, word_target)

        word_count = len(body.split())
        seo_score = round(min(0.3 + word_count / 2000, 0.95), 3)
        estimated_monthly_traffic = int(seo_score * 500)
        slug = self._make_slug(title)
        meta_title = title[:60]
        meta_description = f"Learn everything about {target_keyword}. {title[:100]}."[:155]
        secondary_keywords = [
            f"{target_keyword} tips",
            f"best {target_keyword}",
            f"how to {target_keyword}",
            f"{target_keyword} guide",
        ]

        post = BlogPost(
            title=title,
            slug=slug,
            meta_title=meta_title,
            meta_description=meta_description,
            target_keyword=target_keyword,
            secondary_keywords=secondary_keywords,
            outline=[],
            body=body,
            word_count=word_count,
            seo_score=seo_score,
            estimated_monthly_traffic=estimated_monthly_traffic,
            category=topic,
            internal_links=[],
        )
        self._posts.append(post.to_dict())
        await self._save()
        return post

    async def generate_outline(
        self,
        topic: str,
        keyword: str,
        num_sections: int = 5,
    ) -> list[dict]:
        await self._load()

        outline: list[dict] = []

        try:
            ai = get_ai_client()
            resp = await ai.complete(
                system=(
                    f"You are an SEO content strategist. Generate a {num_sections}-section blog outline "
                    f"for the keyword '{keyword}'.\n"
                    "For each section provide: heading (H2), word_target (int 150-300), key_points (3 bullet points).\n"
                    "Format each section as:\n"
                    "HEADING: section title\n"
                    "WORDS: 200\n"
                    "POINTS: point one | point two | point three\n"
                    "---"
                ),
                user=f"Topic: {topic}\nKeyword: {keyword}\nSections: {num_sections}",
                model=AIModel.FAST,
                max_tokens=700,
            )
            if resp.success and resp.content:
                blocks = resp.content.strip().split("---")
                for block in blocks:
                    block = block.strip()
                    if not block:
                        continue
                    heading = ""
                    word_target = 200
                    key_points: list[str] = []
                    for line in block.splitlines():
                        line = line.strip()
                        if line.upper().startswith("HEADING:"):
                            heading = line[8:].strip()
                        elif line.upper().startswith("WORDS:"):
                            try:
                                word_target = int(line[6:].strip())
                            except ValueError:
                                word_target = 200
                        elif line.upper().startswith("POINTS:"):
                            raw = line[7:].strip()
                            key_points = [p.strip() for p in raw.split("|") if p.strip()]
                    if heading:
                        outline.append(
                            {
                                "heading": heading,
                                "word_target": word_target,
                                "key_points": key_points,
                            }
                        )
                    if len(outline) >= num_sections:
                        break
        except Exception as exc:
            logger.warning("BlogPublisher.generate_outline AI call failed: %s", exc)

        if not outline:
            generic_sections = [
                f"What Is {topic}?",
                f"Why {keyword} Matters",
                f"How to Get Started with {topic}",
                f"Best Practices for {keyword}",
                "Common Mistakes to Avoid",
            ]
            outline = [
                {"heading": h, "word_target": 200, "key_points": [f"Key insight about {h}"]}
                for h in generic_sections[:num_sections]
            ]

        return outline[:num_sections]

    async def optimize_for_seo(self, post: BlogPost, keyword: str) -> BlogPost:
        await self._load()

        optimized_body = post.body
        optimized_meta_desc = post.meta_description
        internal_links = list(post.internal_links)

        try:
            ai = get_ai_client()
            resp = await ai.complete(
                system=(
                    f"You are an SEO optimization expert. Improve this blog post for the keyword '{keyword}'.\n"
                    "Tasks:\n"
                    "1. Ensure keyword appears naturally in first 100 words\n"
                    "2. Add 2-3 keyword variations in H2 headings where natural\n"
                    "3. Strengthen the meta description to include keyword and a benefit\n"
                    "4. Suggest 3 internal link anchor texts (as: INTERNAL_LINKS: anchor1 | anchor2 | anchor3)\n"
                    "5. Return the full improved article body\n\n"
                    "Format: META: <improved meta description>\nINTERNAL_LINKS: ...\nBODY:\n<full article>"
                ),
                user=f"Keyword: {keyword}\n\nArticle:\n{post.body[:3000]}",
                model=AIModel.STRATEGY,
                max_tokens=2000,
            )
            if resp.success and resp.content:
                content = resp.content.strip()
                meta_idx = content.upper().find("META:")
                links_idx = content.upper().find("INTERNAL_LINKS:")
                body_idx = content.upper().find("BODY:")

                if meta_idx != -1:
                    end = (
                        links_idx
                        if links_idx != -1
                        else (body_idx if body_idx != -1 else len(content))
                    )
                    optimized_meta_desc = content[meta_idx + 5 : end].strip()[:155]
                if links_idx != -1:
                    end = body_idx if body_idx != -1 else len(content)
                    raw_links = content[links_idx + 15 : end].strip()
                    internal_links = [l.strip() for l in raw_links.split("|") if l.strip()][:3]
                if body_idx != -1:
                    optimized_body = content[body_idx + 5 :].strip()
        except Exception as exc:
            logger.warning("BlogPublisher.optimize_for_seo AI call failed: %s", exc)

        word_count = len(optimized_body.split())
        seo_score = round(min(0.3 + word_count / 2000 + 0.05, 0.95), 3)
        estimated_monthly_traffic = int(seo_score * 500)

        updated = BlogPost(
            title=post.title,
            slug=post.slug,
            meta_title=post.meta_title,
            meta_description=optimized_meta_desc,
            target_keyword=keyword,
            secondary_keywords=post.secondary_keywords,
            outline=post.outline,
            body=optimized_body,
            word_count=word_count,
            seo_score=seo_score,
            estimated_monthly_traffic=estimated_monthly_traffic,
            category=post.category,
            internal_links=internal_links,
        )
        self._posts.append(updated.to_dict())
        await self._save()
        return updated

    async def generate_topic_cluster(
        self,
        pillar_topic: str,
        num_posts: int = 5,
    ) -> list[dict]:
        await self._load()

        cluster: list[dict] = []

        try:
            ai = get_ai_client()
            resp = await ai.complete(
                system=(
                    f"You are an SEO content strategist. Generate a topic cluster of {num_posts} blog posts "
                    f"around the pillar topic '{pillar_topic}'.\n"
                    "For each post provide: title, keyword, search_intent (informational|commercial|transactional), "
                    "difficulty (low|medium|high).\n"
                    "Format each post as:\n"
                    "TITLE: post title\n"
                    "KEYWORD: target keyword\n"
                    "INTENT: informational\n"
                    "DIFFICULTY: low\n"
                    "---"
                ),
                user=f"Pillar topic: {pillar_topic}\nNumber of posts: {num_posts}",
                model=AIModel.STRATEGY,
                max_tokens=800,
            )
            if resp.success and resp.content:
                blocks = resp.content.strip().split("---")
                for block in blocks:
                    block = block.strip()
                    if not block:
                        continue
                    entry: dict = {}
                    for line in block.splitlines():
                        line = line.strip()
                        if line.upper().startswith("TITLE:"):
                            entry["title"] = line[6:].strip()
                        elif line.upper().startswith("KEYWORD:"):
                            entry["keyword"] = line[8:].strip()
                        elif line.upper().startswith("INTENT:"):
                            raw = line[7:].strip().lower()
                            entry["search_intent"] = (
                                raw
                                if raw in {"informational", "commercial", "transactional"}
                                else "informational"
                            )
                        elif line.upper().startswith("DIFFICULTY:"):
                            raw = line[11:].strip().lower()
                            entry["difficulty"] = (
                                raw if raw in {"low", "medium", "high"} else "medium"
                            )
                    if entry.get("title") and entry.get("keyword"):
                        cluster.append(entry)
                    if len(cluster) >= num_posts:
                        break
        except Exception as exc:
            logger.warning("BlogPublisher.generate_topic_cluster AI call failed: %s", exc)

        if not cluster:
            intents = [
                "informational",
                "commercial",
                "informational",
                "transactional",
                "informational",
            ]
            difficulties = ["low", "medium", "low", "medium", "high"]
            for i in range(num_posts):
                cluster.append(
                    {
                        "title": f"Complete Guide to {pillar_topic} — Part {i + 1}",
                        "keyword": f"{pillar_topic} guide {i + 1}",
                        "search_intent": intents[i % len(intents)],
                        "difficulty": difficulties[i % len(difficulties)],
                    }
                )

        return cluster[:num_posts]

    def blog_stats(self) -> dict:
        count = len(self._posts)
        by_category: dict[str, int] = {}
        total_seo = 0.0
        total_words = 0
        total_traffic = 0
        for p in self._posts:
            cat = p.get("category", "uncategorized")
            by_category[cat] = by_category.get(cat, 0) + 1
            total_seo += p.get("seo_score", 0.0)
            total_words += p.get("word_count", 0)
            total_traffic += p.get("estimated_monthly_traffic", 0)
        return {
            "total_posts": count,
            "avg_seo_score": round(total_seo / count, 3) if count else 0.0,
            "avg_word_count": total_words // count if count else 0,
            "avg_monthly_traffic": total_traffic // count if count else 0,
            "by_category": by_category,
        }

    def recent_posts(self, limit: int = 10) -> list[dict]:
        return self._posts[-limit:]


_instance: BlogPublisher | None = None


def get_blog_publisher() -> BlogPublisher:
    global _instance
    if _instance is None:
        _instance = BlogPublisher()
    return _instance
