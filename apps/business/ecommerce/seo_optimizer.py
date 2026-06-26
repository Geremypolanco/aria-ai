"""
Shopify SEO and content optimization.

Scores product listings, generates meta tags via AI, surfaces keyword
opportunities, and audits catalogs — all without circular imports.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


@dataclass
class SEOScore:
    product_id: str
    overall_score: float
    title_score: float
    description_score: float
    tags_score: float
    images_score: float
    url_score: float
    issues: list[str] = field(default_factory=list)
    recommendations: list[str] = field(default_factory=list)


@dataclass
class KeywordTarget:
    keyword: str
    volume_estimate: int
    difficulty: float
    opportunity_score: float
    current_rank: int = -1


# ---------------------------------------------------------------------------
# Niche → keyword mapping (deterministic)
# ---------------------------------------------------------------------------

_NICHE_KEYWORDS: dict[str, list[dict[str, Any]]] = {
    "home_decor": [
        {"keyword": "wall art", "volume_estimate": 135000, "difficulty": 0.62},
        {"keyword": "home decor gifts", "volume_estimate": 74000, "difficulty": 0.55},
        {"keyword": "room decor", "volume_estimate": 201000, "difficulty": 0.70},
        {"keyword": "modern home accessories", "volume_estimate": 22000, "difficulty": 0.40},
    ],
    "fitness": [
        {"keyword": "workout gear", "volume_estimate": 89000, "difficulty": 0.65},
        {"keyword": "home gym equipment", "volume_estimate": 165000, "difficulty": 0.72},
        {"keyword": "resistance bands", "volume_estimate": 110000, "difficulty": 0.58},
    ],
    "beauty": [
        {"keyword": "natural skincare", "volume_estimate": 95000, "difficulty": 0.68},
        {"keyword": "organic beauty products", "volume_estimate": 54000, "difficulty": 0.60},
        {"keyword": "cruelty free makeup", "volume_estimate": 38000, "difficulty": 0.50},
    ],
    "fashion": [
        {"keyword": "sustainable clothing", "volume_estimate": 74000, "difficulty": 0.64},
        {"keyword": "casual summer outfits", "volume_estimate": 120000, "difficulty": 0.70},
        {"keyword": "minimalist style", "volume_estimate": 48000, "difficulty": 0.55},
    ],
    "tech": [
        {"keyword": "smart home devices", "volume_estimate": 180000, "difficulty": 0.75},
        {"keyword": "wireless accessories", "volume_estimate": 95000, "difficulty": 0.65},
        {"keyword": "phone gadgets", "volume_estimate": 60000, "difficulty": 0.58},
    ],
    "food": [
        {"keyword": "gourmet gifts", "volume_estimate": 42000, "difficulty": 0.52},
        {"keyword": "artisan snacks", "volume_estimate": 28000, "difficulty": 0.44},
        {"keyword": "healthy snack delivery", "volume_estimate": 55000, "difficulty": 0.60},
    ],
}

_DEFAULT_KEYWORDS: list[dict[str, Any]] = [
    {"keyword": "online shopping", "volume_estimate": 500000, "difficulty": 0.90},
    {"keyword": "buy online", "volume_estimate": 300000, "difficulty": 0.85},
]


# ---------------------------------------------------------------------------
# Optimizer
# ---------------------------------------------------------------------------


class ShopifySEOOptimizer:
    """Scores and optimises Shopify product listings for search engine visibility."""

    # -- Scoring -----------------------------------------------------------

    def score_product(self, product: dict) -> SEOScore:
        """
        Analyse a product dict and return an SEOScore.

        Input keys used: title, body_html, tags, images, handle
        """
        pid = str(product.get("id", ""))
        title: str = product.get("title", "") or ""
        body: str = product.get("body_html", "") or ""
        tags_raw: str = product.get("tags", "") or ""
        images: list[dict] = product.get("images", []) or []
        handle: str = product.get("handle", "") or ""

        issues: list[str] = []
        recommendations: list[str] = []

        # ---- Title score (0–40) ----------------------------------------
        title_score = 0.0

        char_count = len(title)
        if 40 <= char_count <= 70:
            title_score += 25.0
        elif title:
            title_score += 10.0
            if char_count < 40:
                issues.append("Title is too short (under 40 characters).")
                recommendations.append(
                    "Expand the title to 40–70 characters with descriptive keywords."
                )
            else:
                issues.append("Title is too long (over 70 characters).")
                recommendations.append(
                    "Shorten the title to under 70 characters for better SERP display."
                )

        # Keyword-like terms: at least 2 words with 4+ chars each
        words = title.split()
        descriptive = [w for w in words if len(w) >= 4]
        if len(descriptive) >= 2:
            title_score += 15.0
        else:
            issues.append("Title lacks descriptive keywords.")
            recommendations.append("Include category or feature keywords in the title.")

        if title == title.upper() and title:
            title_score -= 10.0
            issues.append("Title is in ALL CAPS — this hurts readability and SEO.")
            recommendations.append("Use title case for the product title.")

        title_score = max(0.0, title_score)

        # ---- Description score (0–45) -----------------------------------
        desc_score = 0.0
        body_text = re.sub(r"<[^>]+>", "", body)  # strip HTML tags for length

        if len(body_text) > 200:
            desc_score += 25.0
        elif body_text:
            desc_score += 8.0
            issues.append("Description is under 200 characters — expand for better SEO.")
            recommendations.append("Write a 200+ character description with key product details.")
        else:
            issues.append("Product has no description.")
            recommendations.append(
                "Add a detailed description — listings without copy convert poorly."
            )

        # HTML structure or bullet-point signals
        has_structure = bool(
            re.search(r"<(ul|ol|li|h[1-6]|strong|b)>", body, re.IGNORECASE)
            or re.search(r"[•\-\*]\s", body_text)
        )
        if has_structure:
            desc_score += 10.0
        else:
            recommendations.append("Add bullet points or HTML formatting for readability.")

        # Simple keyword stuffing check: no single word > 5% of total words
        words_in_body = body_text.lower().split()
        if words_in_body:
            freq = {}
            for w in words_in_body:
                freq[w] = freq.get(w, 0) + 1
            max_freq = max(freq.values())
            if max_freq / len(words_in_body) <= 0.05:
                desc_score += 10.0
            else:
                issues.append("Possible keyword stuffing detected in description.")
                recommendations.append(
                    "Vary vocabulary — avoid repeating the same word excessively."
                )

        # ---- Tags score (0–30) ------------------------------------------
        if isinstance(tags_raw, list):
            tag_list = [str(t).strip() for t in tags_raw if str(t).strip()]
        else:
            tag_list = [t.strip() for t in str(tags_raw).split(",") if t.strip()]
        tags_score = 0.0

        if len(tag_list) >= 5:
            tags_score += 20.0
        elif tag_list:
            tags_score += 8.0
            issues.append(f"Only {len(tag_list)} tag(s) — aim for 5 or more.")
            recommendations.append("Add at least 5 descriptive tags for better discoverability.")
        else:
            issues.append("No tags set on this product.")
            recommendations.append("Add relevant tags to help customers find this product.")

        descriptive_tags = [t for t in tag_list if len(t) > 3]
        if len(descriptive_tags) >= len(tag_list) and tag_list:
            tags_score += 10.0

        # ---- Images score (0–30) ----------------------------------------
        images_score = 0.0

        if images:
            images_score += 20.0
            alts_present = sum(1 for img in images if img.get("alt", "").strip())
            images_score += min(alts_present * 5.0, 10.0)
            if alts_present < len(images):
                missing = len(images) - alts_present
                issues.append(f"{missing} image(s) missing alt text.")
                recommendations.append("Add descriptive alt text to all product images.")
        else:
            issues.append("No product images uploaded.")
            recommendations.append(
                "Upload high-quality product images — they are critical for conversion."
            )

        # ---- URL / handle score (0–10) ----------------------------------
        url_score = 0.0
        if handle:
            if re.match(r"^[a-z0-9\-]+$", handle) and len(handle) <= 60:
                url_score += 10.0
            else:
                url_score += 5.0
                issues.append("URL handle contains unusual characters or is too long.")
                recommendations.append("Use a short, lowercase, hyphenated URL handle.")
        else:
            issues.append("No URL handle set.")
            recommendations.append("Set a clean, keyword-rich URL handle.")

        overall = title_score + desc_score + tags_score + images_score + url_score
        # Normalise to 0–100 (max possible: 40 + 45 + 30 + 30 + 10 = 155 → scale down)
        overall_normalised = round(min((overall / 155.0) * 100, 100.0), 1)

        return SEOScore(
            product_id=pid,
            overall_score=overall_normalised,
            title_score=round(title_score, 1),
            description_score=round(desc_score, 1),
            tags_score=round(tags_score, 1),
            images_score=round(images_score, 1),
            url_score=round(url_score, 1),
            issues=issues,
            recommendations=recommendations,
        )

    # -- Meta tags ---------------------------------------------------------

    async def generate_meta_tags(self, product_title: str, product_category: str) -> dict[str, str]:
        """
        Generate SEO meta tags via AI.  Falls back to deterministic values
        when AI is unavailable.
        """
        fallback_title = f"{product_title[:50]} | {product_category.title()}"[:60]
        fallback_desc = (
            f"Shop {product_title} in our {product_category} collection. "
            "Free shipping on eligible orders. Find the best deals today."
        )[:160]
        fallback_keyword = product_title.split()[0].lower() if product_title else product_category

        try:
            from apps.core.tools.ai_client import AIModel, get_ai_client  # type: ignore

            ai = get_ai_client()
            prompt = (
                f"Generate SEO meta tags for a Shopify product.\n"
                f"Product: {product_title}\n"
                f"Category: {product_category}\n\n"
                "Return exactly three lines:\n"
                "META_TITLE: <60 chars or less>\n"
                "META_DESCRIPTION: <160 chars or less>\n"
                "FOCUS_KEYWORD: <single keyword phrase>\n"
                "No extra text."
            )
            result = await ai.complete(prompt, model=AIModel.DEFAULT)
            if result:
                lines = result.strip().splitlines()
                parsed: dict[str, str] = {}
                for line in lines:
                    if ":" in line:
                        key, _, val = line.partition(":")
                        parsed[key.strip().upper()] = val.strip()

                return {
                    "meta_title": parsed.get("META_TITLE", fallback_title)[:60],
                    "meta_description": parsed.get("META_DESCRIPTION", fallback_desc)[:160],
                    "focus_keyword": parsed.get("FOCUS_KEYWORD", fallback_keyword),
                }
        except Exception:
            logger.debug("ShopifySEOOptimizer.generate_meta_tags: AI unavailable, using fallback")

        return {
            "meta_title": fallback_title,
            "meta_description": fallback_desc,
            "focus_keyword": fallback_keyword,
        }

    # -- Keyword opportunities ----------------------------------------------

    def keyword_opportunities(
        self, niche: str, existing_keywords: list[str]
    ) -> list[KeywordTarget]:
        """
        Return keyword targets for a given niche, excluding any already in use.

        Niche values with built-in mappings:
          home_decor, fitness, beauty, fashion, tech, food
        Falls back to generic keywords for unknown niches.
        """
        normalised_niche = niche.lower().replace(" ", "_")
        raw = _NICHE_KEYWORDS.get(normalised_niche, _DEFAULT_KEYWORDS)

        existing_lower = {kw.lower() for kw in existing_keywords}
        targets: list[KeywordTarget] = []

        for entry in raw:
            kw = entry["keyword"]
            if kw.lower() in existing_lower:
                continue
            vol = entry["volume_estimate"]
            diff = entry["difficulty"]
            # opportunity = high volume, lower difficulty
            opportunity = round((vol / 200000) * (1 - diff), 3)
            targets.append(
                KeywordTarget(
                    keyword=kw,
                    volume_estimate=vol,
                    difficulty=diff,
                    opportunity_score=opportunity,
                )
            )

        targets.sort(key=lambda x: x.opportunity_score, reverse=True)
        return targets

    # -- URL handle --------------------------------------------------------

    def optimize_url_handle(self, title: str) -> str:
        """
        Convert a product title to a clean URL handle.

        - Lowercased
        - Spaces → hyphens
        - Special characters removed
        - Truncated to 60 characters
        """
        handle = title.lower()
        handle = re.sub(r"[^\w\s-]", "", handle)  # remove special chars
        handle = re.sub(r"[\s_]+", "-", handle)  # spaces/underscores → hyphens
        handle = re.sub(r"-{2,}", "-", handle)  # collapse multiple hyphens
        handle = handle.strip("-")
        return handle[:60]

    # -- Batch audit -------------------------------------------------------

    async def batch_audit(self, products: list[dict]) -> dict[str, Any]:
        """
        Score all products and return them sorted by overall_score ascending
        (worst performers first), plus an audit summary.
        """
        scores: list[SEOScore] = []
        critical_threshold = 40.0

        for product in products:
            try:
                score = self.score_product(product)
                scores.append(score)
            except Exception:
                logger.exception(
                    "ShopifySEOOptimizer.batch_audit: error scoring product %s",
                    product.get("id"),
                )

        scores.sort(key=lambda s: s.overall_score)  # worst first

        avg_score = round(sum(s.overall_score for s in scores) / len(scores), 1) if scores else 0.0
        critical_count = sum(1 for s in scores if s.overall_score < critical_threshold)

        return {
            "scores": scores,
            "avg_score": avg_score,
            "critical_issues_count": critical_count,
            "total_audited": len(scores),
        }


# ---------------------------------------------------------------------------
# Singleton factory
# ---------------------------------------------------------------------------

_seo_optimizer_instance: ShopifySEOOptimizer | None = None


def get_seo_optimizer() -> ShopifySEOOptimizer:
    """Return the shared ShopifySEOOptimizer singleton."""
    global _seo_optimizer_instance
    if _seo_optimizer_instance is None:
        _seo_optimizer_instance = ShopifySEOOptimizer()
    return _seo_optimizer_instance
