"""
SEO analysis and optimization engine.
Researches keywords, analyzes content, optimizes meta tags, and generates content briefs.
"""

from __future__ import annotations

import logging
import random
import re
from dataclasses import dataclass

from apps.core.memory.redis_client import get_cache
from apps.core.tools.ai_client import AIModel, get_ai_client

logger = logging.getLogger("aria.content.seo")

_CACHE_KEY = "content:seo:v1"
_CACHE_TTL = 86400 * 30  # 30 days

_BUYER_INTENT_WORDS = {
    "buy",
    "best",
    "review",
    "vs",
    "cheap",
    "top",
    "discount",
    "deal",
    "price",
    "purchase",
}


# ── Data models ────────────────────────────────────────────────────────────────


@dataclass
class KeywordMetrics:
    keyword: str
    search_volume: int
    difficulty: float
    cpc_usd: float
    buyer_intent_score: float
    opportunity_score: float

    def to_dict(self) -> dict:
        return {
            "keyword": self.keyword,
            "search_volume": self.search_volume,
            "difficulty": self.difficulty,
            "cpc_usd": self.cpc_usd,
            "buyer_intent_score": self.buyer_intent_score,
            "opportunity_score": self.opportunity_score,
        }


@dataclass
class SEOAnalysis:
    url: str
    title: str
    meta_description: str
    h1: str
    keywords_found: list[str]
    word_count: int
    readability_score: float
    seo_score: float
    recommendations: list[str]

    def to_dict(self) -> dict:
        return {
            "url": self.url,
            "title": self.title,
            "meta_description": self.meta_description,
            "h1": self.h1,
            "keywords_found": self.keywords_found,
            "word_count": self.word_count,
            "readability_score": self.readability_score,
            "seo_score": self.seo_score,
            "recommendations": self.recommendations,
        }


# ── Helpers ────────────────────────────────────────────────────────────────────


def _buyer_intent(keyword: str) -> float:
    words = set(keyword.lower().split())
    hits = words & _BUYER_INTENT_WORDS
    return round(min(1.0, len(hits) * 0.25 + 0.1), 2)


def _opportunity_score(search_volume: int, difficulty: float, buyer_intent: float) -> float:
    volume_norm = min(1.0, search_volume / 50000)
    return round(volume_norm * 0.4 + (1 - difficulty) * 0.35 + buyer_intent * 0.25, 3)


def _simulate_keyword_metrics(keyword: str) -> dict:
    words = keyword.lower().split()
    base_volume = max(1000, 50000 - len(words) * 5000)
    search_volume = random.randint(max(1000, base_volume - 10000), min(50000, base_volume + 10000))
    difficulty = round(min(0.9, 0.1 + len(words) * 0.12 + random.uniform(0, 0.2)), 2)
    buyer_intent = _buyer_intent(keyword)
    cpc = round(buyer_intent * 12.0 + random.uniform(0.5, 3.0), 2)
    return {
        "search_volume": search_volume,
        "difficulty": difficulty,
        "cpc_usd": cpc,
        "buyer_intent_score": buyer_intent,
    }


def _readability_score(content: str) -> float:
    """Flesch-style readability approximation (0-1, higher = more readable)."""
    sentences = re.split(r"[.!?]+", content)
    sentences = [s.strip() for s in sentences if s.strip()]
    if not sentences:
        return 0.5
    words = content.split()
    if not words:
        return 0.5
    avg_sentence_len = len(words) / max(1, len(sentences))
    if avg_sentence_len < 20:
        return 0.9
    if avg_sentence_len < 30:
        return 0.7
    return 0.5


# ── Main class ─────────────────────────────────────────────────────────────────


class SEOEngine:
    """Full SEO analysis and optimization engine with keyword research and content briefs."""

    def __init__(self) -> None:
        self._ai = get_ai_client()
        self._keywords: dict[str, dict] = {}
        self._loaded = False

    async def _load(self) -> None:
        if self._loaded:
            return
        try:
            cache = get_cache()
            data = await cache.get(_CACHE_KEY)
            if data and isinstance(data, dict):
                self._keywords = data
        except Exception as exc:
            logger.warning("SEOEngine._load failed: %s", exc)
        self._loaded = True

    async def _save(self) -> None:
        try:
            cache = get_cache()
            await cache.set(_CACHE_KEY, self._keywords, ttl_seconds=_CACHE_TTL)
        except Exception as exc:
            logger.warning("SEOEngine._save failed: %s", exc)

    async def research_keywords(self, topic: str, count: int = 20) -> list[KeywordMetrics]:
        """Use AI to generate realistic keyword opportunities for the topic."""
        await self._load()

        # Ask AI for keyword ideas
        try:
            resp = await self._ai.complete(
                system="You are an expert SEO strategist.",
                user=(
                    f"Generate {count} SEO keyword variations for the topic: '{topic}'.\n"
                    "Include long-tail, buyer-intent, and informational variants.\n"
                    "Output one keyword per line, no bullets or numbering."
                ),
                model=AIModel.FAST,
                max_tokens=400,
                agent_name="seo_engine",
            )
            if resp.success and resp.content:
                lines = [ln.strip() for ln in resp.content.split("\n") if ln.strip()]
                keywords = lines[:count]
            else:
                keywords = [
                    f"{topic}",
                    f"best {topic}",
                    f"{topic} review",
                    f"{topic} vs alternatives",
                    f"buy {topic}",
                    f"{topic} for beginners",
                    f"how to use {topic}",
                    f"{topic} tips",
                    f"{topic} tutorial",
                    f"top {topic} tools",
                ][:count]
        except Exception as exc:
            logger.warning("SEOEngine.research_keywords AI call failed: %s", exc)
            keywords = [f"{topic}", f"best {topic}", f"{topic} guide"][:count]

        result: list[KeywordMetrics] = []
        for kw in keywords:
            metrics = _simulate_keyword_metrics(kw)
            opp = _opportunity_score(
                metrics["search_volume"],
                metrics["difficulty"],
                metrics["buyer_intent_score"],
            )
            km = KeywordMetrics(
                keyword=kw,
                search_volume=metrics["search_volume"],
                difficulty=metrics["difficulty"],
                cpc_usd=metrics["cpc_usd"],
                buyer_intent_score=metrics["buyer_intent_score"],
                opportunity_score=opp,
            )
            self._keywords[kw] = km.to_dict()
            result.append(km)

        await self._save()
        return result

    async def analyze_content(self, content: str, target_keyword: str = "") -> SEOAnalysis:
        """Analyze content for SEO quality and score it."""
        await self._load()

        words = content.split()
        word_count = len(words)
        recommendations: list[str] = []
        seo_score = 0.0

        # Word count scoring
        if word_count >= 600:
            seo_score += 0.4
        elif word_count >= 300:
            seo_score += 0.2
        else:
            recommendations.append("Add more content — aim for 600+ words for better rankings.")

        # Keyword density
        if target_keyword:
            keyword_occurrences = content.lower().count(target_keyword.lower())
            density = keyword_occurrences / max(1, word_count) * 100
            if 1.0 <= density <= 3.0:
                seo_score += 0.2
            elif density < 1.0:
                recommendations.append(
                    f"Increase keyword density for '{target_keyword}' (aim for 1–3%)."
                )
            else:
                recommendations.append(
                    f"Reduce keyword stuffing for '{target_keyword}' (currently {density:.1f}%)."
                )
        else:
            seo_score += 0.1  # partial credit if no target keyword given

        # Readability
        read_score = _readability_score(content)
        if read_score >= 0.8:
            seo_score += 0.2
        else:
            recommendations.append(
                "Shorten sentences — aim for average sentence length under 20 words."
            )

        # Header structure
        has_h1 = bool(re.search(r"^#{1,2}\s", content, re.MULTILINE))
        has_headers = bool(re.search(r"^#{2,3}\s", content, re.MULTILINE))
        if has_h1 or has_headers:
            seo_score += 0.2
        else:
            recommendations.append(
                "Add H2/H3 headers to structure content and improve crawlability."
            )

        # Extract title and h1
        title_match = re.search(r"^#\s+(.+)$", content, re.MULTILINE)
        title = title_match.group(1).strip() if title_match else ""
        h1 = title

        # Extract first paragraph as meta candidate
        paragraphs = [
            p.strip() for p in content.split("\n\n") if p.strip() and not p.startswith("#")
        ]
        meta_description = paragraphs[0][:160] if paragraphs else ""

        # Find keywords in content
        keywords_found = []
        if target_keyword and target_keyword.lower() in content.lower():
            keywords_found.append(target_keyword)

        return SEOAnalysis(
            url="",
            title=title,
            meta_description=meta_description,
            h1=h1,
            keywords_found=keywords_found,
            word_count=word_count,
            readability_score=round(read_score, 2),
            seo_score=round(min(1.0, seo_score), 2),
            recommendations=recommendations,
        )

    async def optimize_meta(self, title: str, description: str, keyword: str) -> dict:
        """AI-generate optimized title (<60 chars) and meta description (150-160 chars)."""
        try:
            resp = await self._ai.complete(
                system="You are an expert SEO copywriter.",
                user=(
                    f"Optimize this page's meta tags for the keyword: '{keyword}'.\n\n"
                    f"Current title: {title}\n"
                    f"Current description: {description}\n\n"
                    "Return EXACTLY this format (no extra text):\n"
                    "TITLE: <optimized title under 60 chars with keyword>\n"
                    "DESCRIPTION: <meta description 150-160 chars with keyword and CTA>"
                ),
                model=AIModel.FAST,
                max_tokens=200,
                agent_name="seo_engine",
            )
            if resp.success and resp.content:
                lines = resp.content.strip().split("\n")
                opt_title = title
                opt_desc = description
                for line in lines:
                    if line.startswith("TITLE:"):
                        opt_title = line.replace("TITLE:", "").strip()[:60]
                    elif line.startswith("DESCRIPTION:"):
                        opt_desc = line.replace("DESCRIPTION:", "").strip()[:160]
                return {"title": opt_title, "description": opt_desc, "keyword": keyword}
        except Exception as exc:
            logger.warning("SEOEngine.optimize_meta failed: %s", exc)

        # Fallback: inject keyword manually
        opt_title = f"{keyword.title()} — {title}"[:60]
        opt_desc = f"Discover the best {keyword} solutions. {description}"[:160]
        return {"title": opt_title, "description": opt_desc, "keyword": keyword}

    async def generate_content_brief(self, keyword: str, audience: str = "general") -> dict:
        """Return structured content brief for a keyword."""
        secondary = []
        try:
            resp = await self._ai.complete(
                system="You are an SEO content strategist.",
                user=(
                    f"Create a content brief for the keyword: '{keyword}' targeting '{audience}' audience.\n\n"
                    "Return EXACTLY this format:\n"
                    "SECONDARY: <5 related keywords, comma-separated>\n"
                    "TONE: <1-2 words: professional/conversational/technical etc>\n"
                    "H2_1: <first H2 heading>\n"
                    "H2_2: <second H2 heading>\n"
                    "H2_3: <third H2 heading>\n"
                    "H2_4: <fourth H2 heading>\n"
                    "H2_5: <fifth H2 heading>\n"
                    "CTA: <call to action suggestion>"
                ),
                model=AIModel.FAST,
                max_tokens=300,
                agent_name="seo_engine",
            )
            if resp.success and resp.content:
                lines = resp.content.strip().split("\n")
                tone = "professional"
                cta = f"Start your {keyword} journey today"
                h2s = []
                for line in lines:
                    if line.startswith("SECONDARY:"):
                        secondary = [k.strip() for k in line.replace("SECONDARY:", "").split(",")][
                            :5
                        ]
                    elif line.startswith("TONE:"):
                        tone = line.replace("TONE:", "").strip()
                    elif line.startswith("H2_"):
                        h2s.append(line.split(":", 1)[1].strip() if ":" in line else "")
                    elif line.startswith("CTA:"):
                        cta = line.replace("CTA:", "").strip()
                return {
                    "target_keyword": keyword,
                    "secondary_keywords": secondary
                    or [f"{keyword} guide", f"best {keyword}", f"{keyword} tips"],
                    "word_count_target": 1200,
                    "tone": tone,
                    "cta_suggestions": [cta],
                    "outline": h2s
                    or [
                        f"What Is {keyword}?",
                        f"Benefits of {keyword}",
                        f"How to Get Started with {keyword}",
                        f"Common {keyword} Mistakes to Avoid",
                        f"Final Thoughts on {keyword}",
                    ],
                    "buyer_intent": _buyer_intent(keyword),
                    "audience": audience,
                }
        except Exception as exc:
            logger.warning("SEOEngine.generate_content_brief failed: %s", exc)

        return {
            "target_keyword": keyword,
            "secondary_keywords": [
                f"{keyword} guide",
                f"best {keyword}",
                f"{keyword} tips",
                f"{keyword} review",
                f"{keyword} tools",
            ],
            "word_count_target": 1200,
            "tone": "conversational",
            "cta_suggestions": [f"Try {keyword} free today", f"Learn more about {keyword}"],
            "outline": [
                f"What Is {keyword}?",
                f"Top Benefits of {keyword}",
                f"Step-by-Step Guide to {keyword}",
                f"Best {keyword} Tools & Resources",
                f"Conclusion: Getting Started with {keyword}",
            ],
            "buyer_intent": _buyer_intent(keyword),
            "audience": audience,
        }

    async def top_opportunities(self, niche: str) -> list[KeywordMetrics]:
        """Return top 10 keywords by opportunity_score for niche."""
        await self._load()

        # Research if we don't have enough keywords for this niche
        if len(self._keywords) < 10:
            await self.research_keywords(niche, count=20)

        all_kw = [KeywordMetrics(**dict(kwd.items())) for kwd in self._keywords.values()]
        # Sort by opportunity score descending
        all_kw.sort(key=lambda k: k.opportunity_score, reverse=True)
        return all_kw[:10]

    def stats(self) -> dict:
        if not self._keywords:
            return {
                "total_keywords_researched": 0,
                "avg_opportunity_score": 0.0,
                "top_keyword": None,
            }

        scores = [v["opportunity_score"] for v in self._keywords.values()]
        avg_score = round(sum(scores) / len(scores), 3)
        top_kw = max(self._keywords.items(), key=lambda x: x[1]["opportunity_score"])
        return {
            "total_keywords_researched": len(self._keywords),
            "avg_opportunity_score": avg_score,
            "top_keyword": top_kw[0],
        }


# ── Singleton ──────────────────────────────────────────────────────────────────

_seo_engine: SEOEngine | None = None


def get_seo_engine() -> SEOEngine:
    global _seo_engine
    if _seo_engine is None:
        _seo_engine = SEOEngine()
    return _seo_engine
