"""
Content calendar management for scheduling and tracking content across all channels.
"""
from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Optional

from apps.core.memory.redis_client import get_cache
from apps.core.tools.ai_client import get_ai_client, AIModel

logger = logging.getLogger("aria.content.blog.calendar")

_CACHE_KEY = "content:calendar:v1"
_CACHE_TTL = 86400 * 90  # 90 days

_CONTENT_MIX = [
    # (content_type, platform, count)
    ("blog", "website", 12),
    ("social", "instagram", 4),
    ("social", "twitter", 4),
    ("email", "mailchimp", 6),
    ("video", "youtube", 4),
]

_TEMPLATES: dict[str, list[str]] = {
    "blog": [
        "The Ultimate Guide to {niche}",
        "Top 10 {niche} Tips for Beginners",
        "How to Master {niche} in 30 Days",
        "{niche} vs Alternatives: Which Is Best?",
        "Why {niche} Is the Future",
        "The Biggest {niche} Mistakes and How to Avoid Them",
        "Case Study: How We Used {niche} to 10x Results",
        "{niche} Tools Every Professional Needs",
        "The Complete {niche} Checklist",
        "Advanced {niche} Strategies for Experts",
        "{niche} for Small Businesses: A Practical Guide",
        "The ROI of {niche}: Real Numbers",
    ],
    "social": [
        "Quick {niche} tip that changed everything",
        "Controversial opinion on {niche}",
        "{niche} myth BUSTED",
        "My {niche} results after 90 days",
        "The {niche} mistake 90% of people make",
        "Why I switched to {niche} (and never looked back)",
        "{niche} cheat sheet — save this!",
        "Unpopular opinion: {niche} is overrated",
    ],
    "email": [
        "This week in {niche}: What you missed",
        "The {niche} secret nobody talks about",
        "Special offer for {niche} enthusiasts",
        "{niche} trends to watch this month",
        "Your {niche} action plan for this week",
        "Exclusive {niche} resource roundup",
    ],
    "video": [
        "{niche} Tutorial: Complete Beginner's Guide",
        "I Tested 5 {niche} Tools So You Don't Have To",
        "{niche} Q&A — Your Top Questions Answered",
        "The {niche} Strategy That Gets Results",
    ],
}


# ── Data models ────────────────────────────────────────────────────────────────

@dataclass
class ContentSlot:
    slot_id: str
    date: str  # YYYY-MM-DD
    content_type: str  # "blog" | "video" | "social" | "email"
    title: str
    keyword: str
    platform: str
    status: str  # "planned" | "in_progress" | "published"
    notes: str

    def to_dict(self) -> dict:
        return {
            "slot_id": self.slot_id,
            "date": self.date,
            "content_type": self.content_type,
            "title": self.title,
            "keyword": self.keyword,
            "platform": self.platform,
            "status": self.status,
            "notes": self.notes,
        }


# ── Main class ─────────────────────────────────────────────────────────────────

class ContentCalendar:
    """Content calendar for planning and tracking multi-channel content."""

    def __init__(self) -> None:
        self._slots: list[dict] = []
        self._loaded = False

    async def _load(self) -> None:
        if self._loaded:
            return
        try:
            cache = get_cache()
            data = await cache.get(_CACHE_KEY)
            if data and isinstance(data, list):
                self._slots = data
        except Exception as exc:
            logger.warning("ContentCalendar._load failed: %s", exc)
        self._loaded = True

    async def _save(self) -> None:
        try:
            cache = get_cache()
            await cache.set(_CACHE_KEY, self._slots, ttl_seconds=_CACHE_TTL)
        except Exception as exc:
            logger.warning("ContentCalendar._save failed: %s", exc)

    async def plan_month(self, niche: str, month_start: str = "") -> list[ContentSlot]:
        """Create a 30-day content calendar with mixed content types."""
        await self._load()

        if not month_start:
            month_start = datetime.utcnow().strftime("%Y-%m-%d")

        start_date = datetime.strptime(month_start, "%Y-%m-%d")
        slots: list[ContentSlot] = []

        # Build pool of content items
        items: list[tuple[str, str, str]] = []  # (type, platform, title)
        for content_type, platform, count in _CONTENT_MIX:
            templates = _TEMPLATES.get(content_type, [])
            for i in range(count):
                title_template = templates[i % len(templates)]
                title = title_template.format(niche=niche)
                items.append((content_type, platform, title))

        # Distribute across 30 days
        total = len(items)
        for i, (content_type, platform, title) in enumerate(items):
            day_offset = int(i * 30 / total)
            slot_date = start_date + timedelta(days=day_offset)

            slot = ContentSlot(
                slot_id=str(uuid.uuid4()),
                date=slot_date.strftime("%Y-%m-%d"),
                content_type=content_type,
                title=title,
                keyword=niche,
                platform=platform,
                status="planned",
                notes="",
            )
            slots.append(slot)
            self._slots.append(slot.to_dict())

        await self._save()
        return slots

    async def add_slot(
        self,
        date: str,
        content_type: str,
        title: str,
        keyword: str = "",
        platform: str = "",
    ) -> ContentSlot:
        """Add a single content slot to the calendar."""
        await self._load()
        slot = ContentSlot(
            slot_id=str(uuid.uuid4()),
            date=date,
            content_type=content_type,
            title=title,
            keyword=keyword,
            platform=platform,
            status="planned",
            notes="",
        )
        self._slots.append(slot.to_dict())
        await self._save()
        return slot

    def this_week(self) -> list[dict]:
        """Return slots for the current week (Mon–Sun)."""
        today = datetime.utcnow()
        week_start = today - timedelta(days=today.weekday())
        week_end = week_start + timedelta(days=6)
        return [
            s for s in self._slots
            if week_start.strftime("%Y-%m-%d") <= s.get("date", "") <= week_end.strftime("%Y-%m-%d")
        ]

    def upcoming(self, days: int = 14) -> list[dict]:
        """Return upcoming slots within the next N days."""
        today = datetime.utcnow().strftime("%Y-%m-%d")
        cutoff = (datetime.utcnow() + timedelta(days=days)).strftime("%Y-%m-%d")
        return [
            s for s in self._slots
            if today <= s.get("date", "") <= cutoff
        ]

    def mark_published(self, slot_id: str) -> bool:
        """Mark a slot as published by its ID."""
        for slot in self._slots:
            if slot.get("slot_id") == slot_id:
                slot["status"] = "published"
                return True
        return False

    def calendar_stats(self) -> dict:
        planned = sum(1 for s in self._slots if s.get("status") == "planned")
        in_progress = sum(1 for s in self._slots if s.get("status") == "in_progress")
        published = sum(1 for s in self._slots if s.get("status") == "published")
        return {
            "planned": planned,
            "in_progress": in_progress,
            "published": published,
            "total": len(self._slots),
        }


# ── Singleton ──────────────────────────────────────────────────────────────────

_content_calendar: Optional[ContentCalendar] = None


def get_content_calendar() -> ContentCalendar:
    global _content_calendar
    if _content_calendar is None:
        _content_calendar = ContentCalendar()
    return _content_calendar
