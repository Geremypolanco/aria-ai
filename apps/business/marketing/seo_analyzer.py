"""
SEO analysis and keyword intelligence — page scoring, keyword research,
content gap analysis, trending topics, and internal linking opportunities.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from apps.core.memory.redis_client import get_cache

logger = logging.getLogger("aria.marketing.seo")

# ── Niche → trending topics ────────────────────────────────────────────────────

_TRENDING_BY_NICHE: dict[str, list[str]] = {
    "ecommerce": [
        "AI-powered product recommendations",
        "Social commerce on TikTok Shop",
        "Sustainability and eco-friendly packaging",
        "Headless commerce architecture",
        "Same-day delivery expectations",
    ],
    "fitness": [
        "Wearable fitness technology",
        "Hybrid home/gym workout programs",
        "Recovery and sleep optimization",
        "Personalized nutrition via DNA testing",
        "Mental wellness and exercise connection",
    ],
    "tech": [
        "Generative AI for productivity",
        "Edge computing applications",
        "Privacy-first product design",
        "No-code and low-code platforms",
        "AI agent automation",
    ],
    "finance": [
        "AI financial planning tools",
        "Fractional investing platforms",
        "Crypto regulatory clarity",
        "Buy now, pay later fatigue",
        "High-yield savings account surge",
    ],
    "marketing": [
        "Zero-click search optimization",
        "AI-generated content strategy",
        "First-party data post-cookie",
        "Community-led growth",
        "Short-form video ROI measurement",
    ],
    "default": [
        "AI automation for small business",
        "Creator economy monetization",
        "Privacy and data ownership",
        "Micro-community building",
        "Authentic brand storytelling",
    ],
}

# ── Volume decay by term length ────────────────────────────────────────────────


def _estimate_volume(term: str) -> int:
    """Shorter terms have higher search volume (deterministic heuristic)."""
    words = len(term.split())
    base = 10000 - (words * 1500)
    return max(100, base)


def _estimate_difficulty(term: str, i: int) -> float:
    """Longer, more specific terms are easier to rank for."""
    words = len(term.split())
    return round(max(0.1, 0.9 - (words * 0.08) - (i * 0.02)), 2)


def _estimate_cpc(volume: int) -> float:
    """Higher volume terms tend to have higher CPC (rough heuristic)."""
    return round(max(0.10, volume / 5000 * 1.5), 2)


def _infer_intent(term: str) -> str:
    """Infer search intent from term patterns."""
    t = term.lower()
    if any(w in t for w in ["buy", "price", "cost", "purchase", "deal", "discount", "shop"]):
        return "commercial"
    if any(w in t for w in ["how to", "what is", "guide", "tutorial", "learn", "tips"]):
        return "informational"
    if any(w in t for w in ["vs", "compare", "best", "review", "top"]):
        return "commercial"
    if any(w in t for w in ["near me", "location", "open", "hours"]):
        return "navigational"
    return "informational"


# ── Dataclasses ────────────────────────────────────────────────────────────────


@dataclass
class Keyword:
    term: str
    volume_estimate: int
    difficulty: float = 0.5
    cpc_estimate: float = 0.0
    opportunity_score: float = 0.0
    intent: str = "informational"


@dataclass
class SEOAudit:
    url: str
    title: str
    title_score: float
    description: str
    description_score: float
    h1_count: int
    word_count: int
    internal_links: int
    issues: list[str]
    score: float


# ── SEOAnalyzer ────────────────────────────────────────────────────────────────


class SEOAnalyzer:
    """SEO analysis and keyword intelligence."""

    def __init__(self) -> None:
        self._cache = get_cache()

    def score_page(
        self,
        title: str,
        description: str,
        word_count: int,
        has_h1: bool,
        has_images: bool,
    ) -> SEOAudit:
        """Deterministic SEO page scoring (0–100)."""
        score = 0.0
        issues: list[str] = []
        title_score = 0.0
        description_score = 0.0

        # Title scoring
        title_len = len(title)
        if 50 <= title_len <= 60:
            title_score += 25
        elif 40 <= title_len < 50 or 60 < title_len <= 70:
            title_score += 15
            issues.append(f"Title length {title_len} chars — optimal 50–60")
        else:
            title_score += 5
            issues.append(f"Title length {title_len} chars is outside recommended range (50–60)")

        score += title_score

        # Description scoring
        desc_len = len(description)
        if 120 <= desc_len <= 160:
            description_score += 20
        elif 100 <= desc_len < 120 or 160 < desc_len <= 180:
            description_score += 12
            issues.append(f"Description length {desc_len} chars — optimal 120–160")
        else:
            description_score += 4
            issues.append(
                f"Description length {desc_len} chars is outside recommended range (120–160)"
            )

        score += description_score

        # Word count
        if word_count >= 1500 or word_count >= 500:
            score += 20
        elif word_count >= 300:
            score += 10
            issues.append(f"Word count {word_count} — aim for 500+ for better ranking")
        else:
            score += 0
            issues.append(f"Very thin content ({word_count} words) — Google prefers 500+")

        # H1 presence
        if has_h1:
            score += 15
        else:
            issues.append("Missing H1 tag — each page should have exactly one H1")

        # Images
        if has_images:
            score += 10
        else:
            issues.append("No images found — add relevant images with alt text")

        # Deductions
        if title_len > 70:
            score -= 5
            issues.append("Title too long — will be truncated in search results")
        if not description:
            score -= 10
            issues.append("Missing meta description")

        final_score = round(max(0.0, min(score, 100.0)), 1)

        return SEOAudit(
            url="",
            title=title,
            title_score=title_score,
            description=description,
            description_score=description_score,
            h1_count=1 if has_h1 else 0,
            word_count=word_count,
            internal_links=0,
            issues=issues,
            score=final_score,
        )

    def keyword_research(self, seed: str, niche: str) -> list[Keyword]:
        """Return 10 keywords built deterministically from seed + niche."""
        seed_lower = seed.lower().strip()
        niche_lower = niche.lower().strip()

        # Combine seed and niche into keyword patterns
        raw_terms: list[str] = [
            seed_lower,
            f"{seed_lower} guide",
            f"best {seed_lower}",
            f"how to {seed_lower}",
            f"{seed_lower} tips",
            f"{seed_lower} for beginners",
            f"{niche_lower} {seed_lower}",
            f"{seed_lower} {niche_lower} strategy",
            f"{seed_lower} examples",
            f"{seed_lower} tools",
        ]

        keywords: list[Keyword] = []
        for i, term in enumerate(raw_terms[:10]):
            volume = _estimate_volume(term)
            difficulty = _estimate_difficulty(term, i)
            cpc = _estimate_cpc(volume)
            intent = _infer_intent(term)
            # Opportunity = volume * (1 - difficulty), normalized 0–1
            opportunity = round(min(1.0, (volume / 10000) * (1 - difficulty)), 3)

            keywords.append(
                Keyword(
                    term=term,
                    volume_estimate=volume,
                    difficulty=difficulty,
                    cpc_estimate=cpc,
                    opportunity_score=opportunity,
                    intent=intent,
                )
            )

        return sorted(keywords, key=lambda k: k.opportunity_score, reverse=True)

    async def content_gap_analysis(
        self,
        my_keywords: list[str],
        competitor_keywords: list[str],
    ) -> list[str]:
        """Return keywords in competitor set but not in mine, sorted by volume."""
        my_set = {k.lower().strip() for k in my_keywords}
        gaps: list[str] = []

        for kw in competitor_keywords:
            if kw.lower().strip() not in my_set:
                gaps.append(kw)

        # Score gaps by volume estimate and sort descending
        scored = [(kw, _estimate_volume(kw)) for kw in gaps]
        scored.sort(key=lambda x: x[1], reverse=True)
        return [kw for kw, _ in scored]

    def trending_topics(self, niche: str) -> list[str]:
        """Return 5 trending topic suggestions for the given niche."""
        niche_lower = niche.lower()
        for key, topics in _TRENDING_BY_NICHE.items():
            if key in niche_lower or niche_lower in key:
                return topics[:5]
        return _TRENDING_BY_NICHE["default"]

    def internal_linking_opportunities(
        self,
        pages: list[dict],
    ) -> list[tuple[str, str, str]]:
        """
        Return (source_url, target_url, anchor_text) tuples where pages share
        topic keywords.

        Each page dict should have: url(str), title(str), keywords(list[str]).
        """
        opportunities: list[tuple[str, str, str]] = []

        for i, source in enumerate(pages):
            source_url = source.get("url", "")
            source_keywords = {kw.lower() for kw in source.get("keywords", [])}
            source.get("title", "")

            for j, target in enumerate(pages):
                if i == j:
                    continue
                target_url = target.get("url", "")
                target_keywords = {kw.lower() for kw in target.get("keywords", [])}
                target.get("title", "")

                # Find shared keywords
                shared = source_keywords & target_keywords
                if shared:
                    anchor_text = next(iter(shared)).title()
                    opportunities.append((source_url, target_url, anchor_text))

        return opportunities


# ── Singleton ──────────────────────────────────────────────────────────────────

_seo_instance: SEOAnalyzer | None = None


def get_seo_analyzer() -> SEOAnalyzer:
    global _seo_instance
    if _seo_instance is None:
        _seo_instance = SEOAnalyzer()
    return _seo_instance
