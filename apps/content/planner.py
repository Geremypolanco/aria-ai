"""
Strategic content planning — topic research, strategy building, SEO clustering,
and content repurposing maps.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass

from apps.content.content_os import ContentPlatform, ContentType
from apps.core.memory.redis_client import get_cache

logger = logging.getLogger("aria.content.planner")

_STRATEGY_KEY = "content:strategy:v1"
_STRATEGY_TTL = 86400 * 90  # 90 days

# ── Niche topic seeds ──────────────────────────────────────────────────────────

_NICHE_TOPICS: dict[str, list[str]] = {
    "ecommerce": [
        "product reviews",
        "buying guides",
        "unboxing",
        "best deals",
        "comparison shopping",
        "dropshipping tips",
        "store setup",
        "customer retention",
        "abandoned cart recovery",
        "upsell strategies",
    ],
    "fitness": [
        "workout tutorials",
        "nutrition tips",
        "transformation stories",
        "supplement reviews",
        "home gym setup",
        "meal prep ideas",
        "weight loss strategies",
        "muscle building",
        "recovery techniques",
        "fitness challenges",
    ],
    "tech": [
        "how-to guides",
        "product comparisons",
        "tutorials",
        "software reviews",
        "AI tools",
        "productivity hacks",
        "cybersecurity basics",
        "developer tips",
        "gadget unboxing",
        "tech news roundup",
    ],
    "finance": [
        "investing basics",
        "budgeting tips",
        "passive income ideas",
        "side hustles",
        "debt payoff strategies",
        "crypto explained",
        "real estate investing",
        "tax saving tips",
        "financial independence",
        "money mindset",
    ],
    "marketing": [
        "growth hacking",
        "email marketing",
        "SEO strategies",
        "social media tips",
        "content strategy",
        "copywriting secrets",
        "funnel optimization",
        "brand building",
        "influencer outreach",
        "paid ads guide",
    ],
}

_DEFAULT_TOPICS = [
    "content strategy",
    "audience building",
    "brand story",
    "growth tactics",
    "engagement tips",
    "platform mastery",
    "monetization ideas",
    "community building",
    "analytics insights",
    "content repurposing",
]

# ── Objective → channel weight presets ────────────────────────────────────────

_OBJECTIVE_CADENCES: dict[str, dict[str, int]] = {
    "awareness": {
        ContentPlatform.YOUTUBE.value: 2,
        ContentPlatform.TIKTOK.value: 5,
        ContentPlatform.INSTAGRAM.value: 4,
        ContentPlatform.TWITTER.value: 3,
        ContentPlatform.LINKEDIN.value: 2,
        ContentPlatform.BLOG.value: 1,
        ContentPlatform.EMAIL.value: 1,
    },
    "conversion": {
        ContentPlatform.EMAIL.value: 3,
        ContentPlatform.BLOG.value: 2,
        ContentPlatform.LINKEDIN.value: 2,
        ContentPlatform.YOUTUBE.value: 1,
        ContentPlatform.TWITTER.value: 2,
        ContentPlatform.TIKTOK.value: 1,
        ContentPlatform.INSTAGRAM.value: 1,
    },
    "retention": {
        ContentPlatform.EMAIL.value: 4,
        ContentPlatform.BLOG.value: 2,
        ContentPlatform.LINKEDIN.value: 2,
        ContentPlatform.YOUTUBE.value: 1,
        ContentPlatform.TWITTER.value: 2,
        ContentPlatform.TIKTOK.value: 1,
        ContentPlatform.INSTAGRAM.value: 1,
    },
}

_DEFAULT_CADENCE: dict[str, int] = {
    ContentPlatform.YOUTUBE.value: 1,
    ContentPlatform.TIKTOK.value: 3,
    ContentPlatform.INSTAGRAM.value: 3,
    ContentPlatform.LINKEDIN.value: 2,
    ContentPlatform.TWITTER.value: 3,
    ContentPlatform.BLOG.value: 2,
    ContentPlatform.EMAIL.value: 1,
}

# ── SEO keyword cluster templates ─────────────────────────────────────────────

_KEYWORD_CLUSTER_TEMPLATES = [
    "{seed} for beginners",
    "best {seed} strategies",
    "how to {seed}",
    "{seed} tips and tricks",
    "{seed} examples",
]

_CLUSTER_MODIFIERS = [
    ["step by step", "complete guide", "tutorial", "course", "checklist"],
    ["tools", "software", "platforms", "resources", "templates"],
    ["mistakes to avoid", "common errors", "pitfalls", "challenges", "problems"],
    ["advanced {seed}", "{seed} mastery", "pro {seed}", "expert {seed}", "{seed} secrets"],
    ["{seed} 2024", "{seed} 2025", "modern {seed}", "new {seed}", "future of {seed}"],
]

# ── Repurposing map ────────────────────────────────────────────────────────────

_REPURPOSING_MAP: dict[ContentType, list[ContentType]] = {
    ContentType.BLOG_POST: [
        ContentType.TWEET_THREAD,
        ContentType.LINKEDIN_POST,
        ContentType.EMAIL_NEWSLETTER,
    ],
    ContentType.YOUTUBE_SCRIPT: [
        ContentType.SHORT_FORM_VIDEO,
        ContentType.BLOG_POST,
        ContentType.PODCAST_OUTLINE,
    ],
    ContentType.PODCAST_OUTLINE: [
        ContentType.BLOG_POST,
        ContentType.TWEET_THREAD,
        ContentType.EMAIL_NEWSLETTER,
    ],
    ContentType.EMAIL_NEWSLETTER: [
        ContentType.BLOG_POST,
        ContentType.LINKEDIN_POST,
        ContentType.TWEET_THREAD,
    ],
    ContentType.LINKEDIN_POST: [
        ContentType.BLOG_POST,
        ContentType.TWEET_THREAD,
        ContentType.EMAIL_NEWSLETTER,
    ],
    ContentType.TWEET_THREAD: [
        ContentType.LINKEDIN_POST,
        ContentType.BLOG_POST,
        ContentType.SHORT_FORM_VIDEO,
    ],
    ContentType.SHORT_FORM_VIDEO: [
        ContentType.YOUTUBE_SCRIPT,
        ContentType.TWEET_THREAD,
        ContentType.LINKEDIN_POST,
    ],
    ContentType.AD_COPY: [
        ContentType.EMAIL_NEWSLETTER,
        ContentType.LINKEDIN_POST,
        ContentType.TWEET_THREAD,
    ],
    ContentType.PRODUCT_DESCRIPTION: [
        ContentType.BLOG_POST,
        ContentType.AD_COPY,
        ContentType.EMAIL_NEWSLETTER,
    ],
}


# ── Dataclasses ────────────────────────────────────────────────────────────────


@dataclass
class ContentTopic:
    topic: str
    niche: str
    search_volume_est: int
    competition: str
    content_angle: str
    target_platform: ContentPlatform
    priority_score: float


@dataclass
class ContentStrategy:
    strategy_id: str
    name: str
    objective: str
    weekly_cadence: dict[str, int]
    topics: list[ContentTopic]
    expected_reach_per_week: int

    def to_dict(self) -> dict:
        return {
            "strategy_id": self.strategy_id,
            "name": self.name,
            "objective": self.objective,
            "weekly_cadence": self.weekly_cadence,
            "topics": [
                {
                    "topic": t.topic,
                    "niche": t.niche,
                    "search_volume_est": t.search_volume_est,
                    "competition": t.competition,
                    "content_angle": t.content_angle,
                    "target_platform": t.target_platform.value,
                    "priority_score": t.priority_score,
                }
                for t in self.topics
            ],
            "expected_reach_per_week": self.expected_reach_per_week,
        }

    @classmethod
    def from_dict(cls, d: dict) -> ContentStrategy:
        topics = [
            ContentTopic(
                topic=t["topic"],
                niche=t["niche"],
                search_volume_est=t["search_volume_est"],
                competition=t["competition"],
                content_angle=t["content_angle"],
                target_platform=ContentPlatform(t["target_platform"]),
                priority_score=t["priority_score"],
            )
            for t in d.get("topics", [])
        ]
        return cls(
            strategy_id=d["strategy_id"],
            name=d["name"],
            objective=d["objective"],
            weekly_cadence=d["weekly_cadence"],
            topics=topics,
            expected_reach_per_week=d["expected_reach_per_week"],
        )


# ── ContentPlanner ─────────────────────────────────────────────────────────────


class ContentPlanner:
    """Strategic content planning — topics, strategy, SEO, and repurposing."""

    def __init__(self) -> None:
        self._cache = get_cache()

    def research_topics(self, niche: str, count: int = 10) -> list[ContentTopic]:
        """Generate topic list deterministically from niche keywords."""
        niche_lower = niche.lower()

        # Match niche to known topic seeds
        matched_topics: list[str] = []
        for key, topics in _NICHE_TOPICS.items():
            if key in niche_lower or niche_lower in key:
                matched_topics = topics
                break

        if not matched_topics:
            matched_topics = _DEFAULT_TOPICS

        # Trim or cycle to reach `count`
        while len(matched_topics) < count:
            matched_topics = matched_topics + matched_topics
        matched_topics = matched_topics[:count]

        # Assign scores and metadata deterministically
        results: list[ContentTopic] = []
        platforms = list(ContentPlatform)

        for i, topic in enumerate(matched_topics):
            # Volume decreases as topic length increases (shorter = broader = higher volume)
            base_volume = max(500, 10000 - len(topic) * 200)
            niche_relevance = 1.0 - (i * 0.05)
            volume_norm = base_volume / 10000
            priority = round(niche_relevance * volume_norm, 3)

            competition = "low" if i > 6 else ("medium" if i > 3 else "high")
            platform = platforms[i % len(platforms)]

            results.append(
                ContentTopic(
                    topic=topic,
                    niche=niche,
                    search_volume_est=base_volume,
                    competition=competition,
                    content_angle=f"How to master {topic} in {niche}",
                    target_platform=platform,
                    priority_score=priority,
                )
            )

        return sorted(results, key=lambda t: t.priority_score, reverse=True)

    def build_strategy(
        self,
        objective: str,
        weekly_budget_hours: float,
    ) -> ContentStrategy:
        """Build a content strategy based on objective and budget."""
        obj_lower = objective.lower()

        # Select cadence preset
        cadence = _DEFAULT_CADENCE.copy()
        for key, preset in _OBJECTIVE_CADENCES.items():
            if key in obj_lower:
                cadence = preset.copy()
                break

        # Scale cadence to fit budget (assume ~1h per piece average)
        total_pieces = sum(cadence.values())
        if weekly_budget_hours < total_pieces:
            scale = weekly_budget_hours / total_pieces
            cadence = {k: max(1, round(v * scale)) for k, v in cadence.items()}

        # Estimate reach based on cadence
        reach_per_platform: dict[str, int] = {
            ContentPlatform.YOUTUBE.value: 500,
            ContentPlatform.TIKTOK.value: 2000,
            ContentPlatform.INSTAGRAM.value: 800,
            ContentPlatform.LINKEDIN.value: 1200,
            ContentPlatform.TWITTER.value: 600,
            ContentPlatform.BLOG.value: 300,
            ContentPlatform.EMAIL.value: 400,
        }
        expected_reach = sum(cadence.get(p, 0) * reach_per_platform.get(p, 200) for p in cadence)

        return ContentStrategy(
            strategy_id=str(uuid.uuid4()),
            name=f"{objective.title()} Strategy",
            objective=objective,
            weekly_cadence=cadence,
            topics=[],
            expected_reach_per_week=expected_reach,
        )

    async def save_strategy(self, strategy: ContentStrategy) -> bool:
        """Persist strategy to Redis."""
        try:
            await self._cache.set(_STRATEGY_KEY, strategy.to_dict(), ttl_seconds=_STRATEGY_TTL)
            return True
        except Exception as exc:
            logger.warning("ContentPlanner.save_strategy: %s", exc)
            return False

    async def load_strategy(self) -> ContentStrategy | None:
        """Load current strategy from Redis, or return None."""
        try:
            data = await self._cache.get(_STRATEGY_KEY)
            if data and isinstance(data, dict):
                return ContentStrategy.from_dict(data)
        except Exception as exc:
            logger.warning("ContentPlanner.load_strategy: %s", exc)
        return None

    def seo_keyword_clusters(self, seed_keyword: str) -> dict[str, list[str]]:
        """Return 5 keyword clusters with 3–5 related terms each."""
        seed = seed_keyword.lower().strip()
        clusters: dict[str, list[str]] = {}

        for i, template in enumerate(_KEYWORD_CLUSTER_TEMPLATES):
            cluster_head = template.format(seed=seed)
            modifiers = _CLUSTER_MODIFIERS[i]
            # Interpolate seed into modifiers that contain {seed}
            terms = []
            for mod in modifiers[:4]:
                term = mod.format(seed=seed) if "{seed}" in mod else f"{seed} {mod}"
                terms.append(term)
            clusters[cluster_head] = terms

        return clusters

    def repurposing_plan(self, content_piece_type: ContentType) -> dict[str, list[str]]:
        """Return mapping of original type to list of repurposed types."""
        repurposed = _REPURPOSING_MAP.get(content_piece_type, [])
        return {content_piece_type.value: [ct.value for ct in repurposed]}


# ── Singleton ──────────────────────────────────────────────────────────────────

_planner_instance: ContentPlanner | None = None


def get_content_planner() -> ContentPlanner:
    global _planner_instance
    if _planner_instance is None:
        _planner_instance = ContentPlanner()
    return _planner_instance
