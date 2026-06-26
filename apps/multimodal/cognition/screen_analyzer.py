"""
Screen and landing page analysis for conversion optimization.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from apps.core.tools.ai_client import AIModel, get_ai_client

logger = logging.getLogger("aria.screen_analyzer")


@dataclass
class PageAnalysis:
    url: str
    title: str = ""
    cta_count: int = 0
    load_score: float = 0.0
    mobile_friendly: bool = True
    seo_score: float = 0.0
    conversion_score: float = 0.0
    trust_signals: list[str] = field(default_factory=list)
    friction_points: list[str] = field(default_factory=list)
    recommendations: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "url": self.url,
            "title": self.title,
            "cta_count": self.cta_count,
            "load_score": self.load_score,
            "mobile_friendly": self.mobile_friendly,
            "seo_score": self.seo_score,
            "conversion_score": self.conversion_score,
            "trust_signals": self.trust_signals,
            "friction_points": self.friction_points,
            "recommendations": self.recommendations,
        }


class ScreenAnalyzer:
    def __init__(self) -> None:
        self._ai = get_ai_client()

    async def analyze_landing_page(self, url: str) -> PageAnalysis:
        html_snippet = await self._fetch_html(url)
        analysis = PageAnalysis(url=url)

        if not html_snippet:
            analysis.recommendations = ["Could not fetch page content"]
            return analysis

        try:
            lower = html_snippet.lower()
            # Heuristic CTA detection
            cta_keywords = [
                "buy now",
                "get started",
                "sign up",
                "subscribe",
                "add to cart",
                "shop now",
            ]
            analysis.cta_count = sum(1 for kw in cta_keywords if kw in lower)

            # Trust signals
            if "ssl" in lower or "https" in url:
                analysis.trust_signals.append("SSL/HTTPS")
            if "review" in lower or "testimonial" in lower:
                analysis.trust_signals.append("Social proof")
            if "guarantee" in lower or "money back" in lower:
                analysis.trust_signals.append("Guarantee")

            # Friction points
            if "captcha" in lower:
                analysis.friction_points.append("CAPTCHA present")
            if analysis.cta_count == 0:
                analysis.friction_points.append("No visible CTA")

            analysis.conversion_score = min(
                1.0,
                round(
                    (analysis.cta_count * 0.2)
                    + (len(analysis.trust_signals) * 0.15)
                    - (len(analysis.friction_points) * 0.1)
                    + 0.3,
                    3,
                ),
            )
            analysis.seo_score = 0.6 if "<title>" in lower else 0.3

            if self._ai:
                response = await self._ai.complete(
                    system="You are a conversion rate optimization expert.",
                    user=f"Analyze this landing page HTML snippet for conversion optimization:\n{html_snippet[:2000]}",
                    model=AIModel.FAST,
                    max_tokens=400,
                    agent_name="screen_analyzer",
                )
                if response.success and response.content:
                    analysis.recommendations = [response.content[:500]]
        except Exception as exc:
            logger.warning("ScreenAnalyzer: analysis failed — %s", exc)

        if not analysis.recommendations:
            analysis.recommendations = [
                "Add urgency elements (countdown timers)",
                "Increase social proof above the fold",
                "Simplify the conversion form",
            ]
        return analysis

    async def _fetch_html(self, url: str) -> str:
        try:
            import httpx

            async with httpx.AsyncClient(timeout=10.0) as client:
                r = await client.get(url, headers={"User-Agent": "ARIA-Bot/1.0"})
                return r.text[:5000]
        except Exception:
            return ""

    async def competitor_scan(self, urls: list[str]) -> list[dict]:
        results = []
        for url in urls:
            analysis = await self.analyze_landing_page(url)
            results.append(analysis.to_dict())
        results.sort(key=lambda r: r["conversion_score"], reverse=True)
        return results

    async def conversion_recommendations(self, url: str) -> list[str]:
        analysis = await self.analyze_landing_page(url)
        recs = list(analysis.recommendations)
        if analysis.cta_count < 2:
            recs.append("Add at least 2 CTAs (above fold and after social proof)")
        if len(analysis.trust_signals) < 2:
            recs.append("Add reviews, testimonials, or trust badges")
        return recs


_screen_analyzer_instance: ScreenAnalyzer | None = None


def get_screen_analyzer() -> ScreenAnalyzer:
    global _screen_analyzer_instance
    if _screen_analyzer_instance is None:
        _screen_analyzer_instance = ScreenAnalyzer()
    return _screen_analyzer_instance
