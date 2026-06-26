"""
Keyword research with optional Google Trends integration via pytrends.
Falls back to AI-generated suggestions when pytrends is unavailable.
"""

from __future__ import annotations

import logging

from apps.core.tools.ai_client import AIModel, get_ai_client

logger = logging.getLogger("aria.content.seo.keyword_research")

try:
    from pytrends.request import TrendReq

    _PYTRENDS_AVAILABLE = True
except ImportError:
    _PYTRENDS_AVAILABLE = False


class KeywordResearcher:
    """Keyword research engine with pytrends and AI fallback."""

    def __init__(self) -> None:
        self._pytrends = None
        if _PYTRENDS_AVAILABLE:
            try:
                self._pytrends = TrendReq(hl="en-US", tz=360)
            except Exception as exc:
                logger.warning("KeywordResearcher: pytrends init failed: %s", exc)

    async def trending_topics(self, niche: str) -> list[str]:
        """Get trending topics. Uses pytrends if available, else AI fallback."""
        if self._pytrends:
            try:
                suggestions = self._pytrends.suggestions(keyword=niche)
                return [s["title"] for s in suggestions[:10]]
            except Exception as exc:
                logger.warning("KeywordResearcher.trending_topics pytrends failed: %s", exc)

        # AI fallback
        ai = get_ai_client()
        try:
            resp = await ai.complete(
                system="You are an SEO expert.",
                user=f"List 10 trending subtopics in '{niche}' right now. One per line, no bullets.",
                model=AIModel.FAST,
                max_tokens=200,
                agent_name="keyword_researcher",
            )
            if resp.success and resp.content:
                return [line.strip() for line in resp.content.split("\n") if line.strip()][:10]
        except Exception as exc:
            logger.warning("KeywordResearcher.trending_topics AI fallback failed: %s", exc)

        return [f"{niche} tips", f"best {niche} tools", f"{niche} for beginners"]

    async def keyword_volume_estimate(self, keyword: str) -> dict:
        """Estimate search volume and competition. Simulated when no API."""
        words = keyword.lower().split()
        base_volume = max(100, 10000 - len(words) * 1500)
        buyer_words = {"buy", "best", "review", "vs", "cheap", "discount", "deal", "price"}
        buyer_intent = min(1.0, sum(0.2 for w in words if w in buyer_words) + 0.1)
        difficulty = min(0.95, 0.3 + len(words) * 0.05)
        return {
            "keyword": keyword,
            "estimated_volume": base_volume,
            "buyer_intent": round(buyer_intent, 2),
            "difficulty": round(difficulty, 2),
            "cpc_usd": round(buyer_intent * 8.5 + 0.5, 2),
        }


# ── Singleton ──────────────────────────────────────────────────────────────────

_keyword_researcher: KeywordResearcher | None = None


def get_keyword_researcher() -> KeywordResearcher:
    global _keyword_researcher
    if _keyword_researcher is None:
        _keyword_researcher = KeywordResearcher()
    return _keyword_researcher
