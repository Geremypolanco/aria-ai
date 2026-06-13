"""
Content Operating System — unified content creation and distribution platform.
Manages the full lifecycle: ideation → scripting → scheduling → publishing.
"""
from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

from apps.core.memory.redis_client import get_cache
from apps.core.tools.ai_client import get_ai_client, AIModel

logger = logging.getLogger("aria.content.os")

_REDIS_KEY = "content_os:v1"
_TTL = 86400 * 30  # 30 days

_EMOTIONAL_WORDS = {
    "amazing", "incredible", "shocking", "secret", "proven", "powerful",
    "ultimate", "explosive", "breakthrough", "revolutionary", "terrifying",
    "surprising", "unbelievable", "stunning", "dramatic", "critical",
    "urgent", "dangerous", "essential", "devastating", "inspiring",
}

_TRENDING_MARKERS = {
    "ai", "chatgpt", "viral", "trending", "2024", "2025", "hack",
    "growth", "passive income", "side hustle", "automation",
}


# ── Enums ──────────────────────────────────────────────────────────────────────


class ContentType(str, Enum):
    BLOG_POST = "blog_post"
    YOUTUBE_SCRIPT = "youtube_script"
    SHORT_FORM_VIDEO = "short_form_video"
    LINKEDIN_POST = "linkedin_post"
    TWEET_THREAD = "tweet_thread"
    EMAIL_NEWSLETTER = "email_newsletter"
    PRODUCT_DESCRIPTION = "product_description"
    AD_COPY = "ad_copy"
    PODCAST_OUTLINE = "podcast_outline"


class ContentStatus(str, Enum):
    IDEATED = "ideated"
    SCRIPTED = "scripted"
    PRODUCED = "produced"
    SCHEDULED = "scheduled"
    PUBLISHED = "published"
    ARCHIVED = "archived"


class ContentPlatform(str, Enum):
    YOUTUBE = "youtube"
    TIKTOK = "tiktok"
    INSTAGRAM = "instagram"
    LINKEDIN = "linkedin"
    TWITTER = "twitter"
    BLOG = "blog"
    EMAIL = "email"
    SHOPIFY = "shopify"


# ── Dataclasses ────────────────────────────────────────────────────────────────


@dataclass
class ContentPiece:
    content_id: str
    type: ContentType
    platform: ContentPlatform
    title: str
    body: str = ""
    status: ContentStatus = ContentStatus.IDEATED
    topic: str = ""
    target_keyword: str = ""
    estimated_reach: int = 0
    virality_score: float = 0.0
    created_at: float = field(default_factory=time.time)
    published_at: float = 0.0
    performance: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "content_id": self.content_id,
            "type": self.type.value,
            "platform": self.platform.value,
            "title": self.title,
            "body": self.body,
            "status": self.status.value,
            "topic": self.topic,
            "target_keyword": self.target_keyword,
            "estimated_reach": self.estimated_reach,
            "virality_score": self.virality_score,
            "created_at": self.created_at,
            "published_at": self.published_at,
            "performance": self.performance,
        }

    @classmethod
    def from_dict(cls, d: dict) -> ContentPiece:
        return cls(
            content_id=d["content_id"],
            type=ContentType(d["type"]),
            platform=ContentPlatform(d["platform"]),
            title=d["title"],
            body=d.get("body", ""),
            status=ContentStatus(d.get("status", ContentStatus.IDEATED.value)),
            topic=d.get("topic", ""),
            target_keyword=d.get("target_keyword", ""),
            estimated_reach=d.get("estimated_reach", 0),
            virality_score=d.get("virality_score", 0.0),
            created_at=d.get("created_at", time.time()),
            published_at=d.get("published_at", 0.0),
            performance=d.get("performance", {}),
        )


@dataclass
class ContentCalendarEntry:
    date_str: str
    pieces: list[ContentPiece] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "date_str": self.date_str,
            "pieces": [p.to_dict() for p in self.pieces],
        }


# ── Platform → ContentType mapping for calendar ───────────────────────────────

_DAY_PLAN: dict[int, tuple[ContentPlatform, ContentType]] = {
    0: (ContentPlatform.LINKEDIN, ContentType.LINKEDIN_POST),      # Monday
    1: (ContentPlatform.BLOG, ContentType.BLOG_POST),              # Tuesday
    2: (ContentPlatform.YOUTUBE, ContentType.YOUTUBE_SCRIPT),      # Wednesday
    3: (ContentPlatform.EMAIL, ContentType.EMAIL_NEWSLETTER),      # Thursday
    4: (ContentPlatform.TWITTER, ContentType.TWEET_THREAD),        # Friday
    5: (ContentPlatform.TIKTOK, ContentType.SHORT_FORM_VIDEO),     # Saturday
    6: (ContentPlatform.INSTAGRAM, ContentType.BLOG_POST),         # Sunday (ideation)
}


# ── ContentOS ──────────────────────────────────────────────────────────────────


class ContentOS:
    """Unified content creation and distribution platform."""

    def __init__(self) -> None:
        self._cache = get_cache()
        self._ai = get_ai_client()
        self._mem: list[dict] = []
        self._mem_loaded = False

    # ── Persistence ───────────────────────────────────────────────────────────

    async def _load(self) -> list[dict]:
        if not self._mem_loaded:
            try:
                data = await self._cache.get(_REDIS_KEY)
                if isinstance(data, list):
                    self._mem = data
            except Exception:
                pass
            self._mem_loaded = True
        return self._mem

    async def _save(self, pieces: list[ContentPiece]) -> None:
        self._mem = [p.to_dict() for p in pieces]
        try:
            await self._cache.set(_REDIS_KEY, self._mem, ttl_seconds=_TTL)
        except Exception as exc:
            logger.warning("ContentOS: save failed — %s", exc)

    async def _get_piece(self, content_id: str) -> Optional[ContentPiece]:
        raw = await self._load()
        for d in raw:
            if d.get("content_id") == content_id:
                return ContentPiece.from_dict(d)
        return None

    async def _upsert_piece(self, updated: ContentPiece) -> None:
        raw = await self._load()
        pieces = [ContentPiece.from_dict(d) for d in raw]
        pieces = [p for p in pieces if p.content_id != updated.content_id]
        pieces.append(updated)
        await self._save(pieces)

    # ── Core operations ───────────────────────────────────────────────────────

    async def ideate(
        self,
        topic: str,
        platforms: list[ContentPlatform],
        count: int = 3,
    ) -> list[ContentPiece]:
        """Generate `count` content ideas per platform using AI."""
        results: list[ContentPiece] = []

        for platform in platforms:
            platform_name = platform.value
            content_type = _PLATFORM_DEFAULT_TYPE.get(platform, ContentType.BLOG_POST)

            ai_ideas: list[dict] = []
            try:
                if self._ai:
                    response = await self._ai.complete(
                        system=(
                            "You are a viral content strategist. Return ONLY valid JSON — "
                            "a JSON array of objects, each with keys: title (string) and hook (string)."
                        ),
                        user=(
                            f"Topic: {topic}\nPlatform: {platform_name}\n"
                            f"Generate {count} high-performing content ideas. "
                            f"Each idea needs a compelling title and a 1-sentence hook. "
                            f"Return as JSON array: [{{'title': ..., 'hook': ...}}, ...]"
                        ),
                        model=AIModel.CREATIVE,
                        max_tokens=800,
                        json_mode=True,
                        agent_name="content_os",
                    )
                    if response.success and response.content:
                        import json as _json
                        parsed = _json.loads(response.content) if isinstance(response.content, str) else response.content
                        if isinstance(parsed, list):
                            ai_ideas = parsed[:count]
            except Exception as exc:
                logger.warning("ContentOS.ideate: AI failed — %s", exc)

            # Fallback if AI unavailable or returned bad data
            if not ai_ideas:
                ai_ideas = [
                    {"title": f"{topic}: A Complete Guide #{i+1}", "hook": f"Everything you need to know about {topic}"}
                    for i in range(count)
                ]

            for idea in ai_ideas[:count]:
                piece = ContentPiece(
                    content_id=str(uuid.uuid4()),
                    type=content_type,
                    platform=platform,
                    title=idea.get("title", f"{topic} — Idea"),
                    body=idea.get("hook", ""),
                    status=ContentStatus.IDEATED,
                    topic=topic,
                    created_at=time.time(),
                )
                results.append(piece)

        # Persist all new pieces
        raw = await self._load()
        existing = [ContentPiece.from_dict(d) for d in raw]
        await self._save(existing + results)
        return results

    async def generate_script(self, content_id: str) -> Optional[ContentPiece]:
        """Write a full script/body for a content piece and mark it SCRIPTED."""
        piece = await self._get_piece(content_id)
        if not piece:
            logger.warning("ContentOS.generate_script: piece %s not found", content_id)
            return None

        body = ""
        try:
            if self._ai:
                response = await self._ai.complete(
                    system=(
                        "You are an expert content writer. Write complete, engaging, "
                        "publication-ready content."
                    ),
                    user=(
                        f"Platform: {piece.platform.value}\n"
                        f"Content type: {piece.type.value}\n"
                        f"Title: {piece.title}\n"
                        f"Topic: {piece.topic}\n"
                        f"Write the full script or body copy. Be specific and actionable."
                    ),
                    model=AIModel.CREATIVE,
                    max_tokens=2000,
                    agent_name="content_os",
                )
                if response.success:
                    body = response.content
        except Exception as exc:
            logger.warning("ContentOS.generate_script: AI failed — %s", exc)
            body = f"[Script for: {piece.title}]\n\nIntroduction...\n\nMain content about {piece.topic}...\n\nConclusion..."

        piece.body = body or piece.body
        piece.status = ContentStatus.SCRIPTED
        await self._upsert_piece(piece)
        return piece

    async def score_virality(self, content_id: str) -> Optional[ContentPiece]:
        """Score virality 0–1 based on title characteristics."""
        piece = await self._get_piece(content_id)
        if not piece:
            return None

        score = 0.0
        title = piece.title
        words = title.split()
        word_count = len(words)

        # Title length optimal 6-12 words
        if 6 <= word_count <= 12:
            score += 0.20

        # Has question mark
        if "?" in title:
            score += 0.15

        # Has number
        if any(ch.isdigit() for ch in title):
            score += 0.15

        # Emotional words present
        title_lower = title.lower()
        if any(w in title_lower for w in _EMOTIONAL_WORDS):
            score += 0.20

        # Trending topic markers
        if any(m in title_lower for m in _TRENDING_MARKERS):
            score += 0.15

        # Cap at 1.0
        piece.virality_score = min(round(score, 3), 1.0)
        await self._upsert_piece(piece)
        return piece

    async def plan_calendar(
        self,
        week_start_date: str,
        topics: list[str],
    ) -> list[ContentCalendarEntry]:
        """Create a 7-day content calendar distributing types across days."""
        from datetime import datetime, timedelta

        try:
            start = datetime.strptime(week_start_date, "%Y-%m-%d")
        except ValueError:
            start = datetime.utcnow()

        topic_cycle = topics if topics else ["Content Marketing"]
        entries: list[ContentCalendarEntry] = []
        new_pieces: list[ContentPiece] = []

        for day_offset in range(7):
            current_date = start + timedelta(days=day_offset)
            date_str = current_date.strftime("%Y-%m-%d")
            weekday = current_date.weekday()  # 0=Mon … 6=Sun

            platform, content_type = _DAY_PLAN[weekday]
            topic = topic_cycle[day_offset % len(topic_cycle)]

            piece = ContentPiece(
                content_id=str(uuid.uuid4()),
                type=content_type,
                platform=platform,
                title=f"{topic}: {_DAY_TITLE_SUFFIX.get(weekday, 'Featured Content')}",
                status=ContentStatus.IDEATED,
                topic=topic,
                created_at=time.time(),
            )
            entry = ContentCalendarEntry(date_str=date_str, pieces=[piece])
            entries.append(entry)
            new_pieces.append(piece)

        # Persist calendar pieces
        raw = await self._load()
        existing = [ContentPiece.from_dict(d) for d in raw]
        await self._save(existing + new_pieces)
        return entries

    async def get_all_content(
        self,
        status_filter: Optional[ContentStatus] = None,
        platform_filter: Optional[ContentPlatform] = None,
    ) -> list[ContentPiece]:
        """Return all content pieces, optionally filtered."""
        raw = await self._load()
        pieces = [ContentPiece.from_dict(d) for d in raw]
        if status_filter:
            pieces = [p for p in pieces if p.status == status_filter]
        if platform_filter:
            pieces = [p for p in pieces if p.platform == platform_filter]
        return pieces

    async def performance_report(self) -> dict:
        """Return aggregated performance metrics across all content."""
        pieces = await self.get_all_content()

        by_status: dict[str, int] = {}
        by_platform: dict[str, int] = {}
        virality_scores: list[float] = []

        for p in pieces:
            by_status[p.status.value] = by_status.get(p.status.value, 0) + 1
            by_platform[p.platform.value] = by_platform.get(p.platform.value, 0) + 1
            if p.virality_score > 0:
                virality_scores.append(p.virality_score)

        avg_virality = round(sum(virality_scores) / len(virality_scores), 3) if virality_scores else 0.0
        top_content = sorted(pieces, key=lambda p: p.virality_score, reverse=True)[:5]

        return {
            "total_pieces": len(pieces),
            "by_status": by_status,
            "by_platform": by_platform,
            "avg_virality_score": avg_virality,
            "top_content": [p.to_dict() for p in top_content],
        }

    def summary(self) -> dict:
        """Synchronous summary — returns pipeline overview without I/O."""
        return {
            "content_pipeline_size": 0,
            "published_count": 0,
            "scheduled_count": 0,
            "avg_virality": 0.0,
            "_note": "Call performance_report() for live data",
        }


# ── Constants ──────────────────────────────────────────────────────────────────

_PLATFORM_DEFAULT_TYPE: dict[ContentPlatform, ContentType] = {
    ContentPlatform.YOUTUBE: ContentType.YOUTUBE_SCRIPT,
    ContentPlatform.TIKTOK: ContentType.SHORT_FORM_VIDEO,
    ContentPlatform.INSTAGRAM: ContentType.SHORT_FORM_VIDEO,
    ContentPlatform.LINKEDIN: ContentType.LINKEDIN_POST,
    ContentPlatform.TWITTER: ContentType.TWEET_THREAD,
    ContentPlatform.BLOG: ContentType.BLOG_POST,
    ContentPlatform.EMAIL: ContentType.EMAIL_NEWSLETTER,
    ContentPlatform.SHOPIFY: ContentType.PRODUCT_DESCRIPTION,
}

_DAY_TITLE_SUFFIX: dict[int, str] = {
    0: "Monday Insight",
    1: "Deep Dive",
    2: "Video Guide",
    3: "Newsletter Feature",
    4: "Thread Breakdown",
    5: "Weekend Quicktake",
    6: "Idea Roundup",
}


# ── Singleton ──────────────────────────────────────────────────────────────────

_content_os_instance: Optional[ContentOS] = None


def get_content_os() -> ContentOS:
    global _content_os_instance
    if _content_os_instance is None:
        _content_os_instance = ContentOS()
    return _content_os_instance
