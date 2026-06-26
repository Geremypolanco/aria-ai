"""
AI-powered thumbnail optimization for YouTube and social media.
Provides deterministic scoring and variant generation without external API calls.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field

# ── Dataclasses ────────────────────────────────────────────────────────────────


@dataclass
class ThumbnailScore:
    contrast_score: float
    text_readability: float
    emotion_score: float
    curiosity_score: float
    ctr_prediction: float
    overall: float
    recommendations: list[str] = field(default_factory=list)


@dataclass
class ThumbnailVariant:
    variant_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    title_text: str = ""
    image_prompt: str = ""
    color_scheme: str = ""
    layout: str = ""
    estimated_ctr: float = 0.0


# ── ThumbnailOptimizer ─────────────────────────────────────────────────────────


class ThumbnailOptimizer:
    """Deterministic thumbnail scoring and variant generation."""

    # Niche CTR benchmarks (average %, top-10 %, target %)
    _NICHE_BENCHMARKS: dict[str, dict] = {
        "gaming": {"avg_ctr_pct": 4.5, "top_10_pct": 9.0, "your_target_pct": 6.0},
        "tech": {"avg_ctr_pct": 3.2, "top_10_pct": 7.0, "your_target_pct": 4.5},
        "fitness": {"avg_ctr_pct": 4.0, "top_10_pct": 8.5, "your_target_pct": 5.5},
        "ecommerce": {"avg_ctr_pct": 2.5, "top_10_pct": 6.0, "your_target_pct": 3.5},
        "general": {"avg_ctr_pct": 3.0, "top_10_pct": 7.5, "your_target_pct": 4.0},
    }

    def score_thumbnail_concept(
        self,
        title: str,
        colors: list[str],
        has_face: bool,
        has_text: bool,
        has_contrast: bool,
    ) -> ThumbnailScore:
        """
        Deterministic scoring — no external calls.
        Returns ThumbnailScore with component breakdown and recommendations.
        """
        recommendations: list[str] = []
        score = 0.0

        # Title word count: 6-12 words is optimal
        word_count = len(title.split())
        if 6 <= word_count <= 12:
            score += 20
        else:
            recommendations.append(
                f"Adjust title to 6-12 words (currently {word_count}) for better readability."
            )

        # Face presence increases CTR significantly
        if has_face:
            score += 25
        else:
            recommendations.append("Add a human face — thumbnails with faces get ~38% more clicks.")

        # High contrast improves visibility
        if has_contrast:
            score += 20
        else:
            recommendations.append("Increase contrast between subject and background.")

        # Text overlay
        if has_text:
            score += 15
        else:
            recommendations.append("Add bold text overlay with 2-4 words of the title.")

        # Color count: 2-3 distinct colors
        color_count = len(set(colors))
        if 2 <= color_count <= 3:
            score += 10
        elif color_count > 3:
            recommendations.append("Reduce to 2-3 primary colors to avoid visual clutter.")
        else:
            recommendations.append("Use at least 2 contrasting colors.")

        # Bright color bonus (heuristic: check for warm/bright color names)
        bright_indicators = {"red", "yellow", "orange", "bright", "neon", "gold"}
        colors_lower = {c.lower() for c in colors}
        if colors_lower & bright_indicators:
            score += 10

        # Clamp to 100
        score = min(score, 100.0)

        # Derive sub-scores from total score proportionally
        contrast_score = min(score * 0.9, 100.0) if has_contrast else score * 0.5
        text_readability = min(score * 0.85, 100.0) if has_text else score * 0.4
        emotion_score = min(score * 0.95, 100.0) if has_face else score * 0.6
        curiosity_score = score * (1.05 if 6 <= word_count <= 10 else 0.8)
        curiosity_score = min(curiosity_score, 100.0)
        ctr_prediction = round(score / 100 * 8.5, 2)  # scale to ~0-8.5% CTR range

        return ThumbnailScore(
            contrast_score=round(contrast_score, 1),
            text_readability=round(text_readability, 1),
            emotion_score=round(emotion_score, 1),
            curiosity_score=round(curiosity_score, 1),
            ctr_prediction=ctr_prediction,
            overall=round(score, 1),
            recommendations=recommendations,
        )

    def generate_variants(
        self,
        video_title: str,
        niche: str,
        count: int = 4,
    ) -> list[ThumbnailVariant]:
        """
        Generate up to 4 thumbnail variants using different psychological approaches.
        Always returns the first `count` from the fixed set of 4 strategies.
        """
        safe_title = video_title[:60]
        niche_lower = niche.lower()

        variants = [
            ThumbnailVariant(
                title_text=f"You won't believe... {safe_title}",
                image_prompt=(
                    f"Mystery thumbnail for '{safe_title}', {niche_lower} niche, "
                    "dramatic lighting, question mark motif, cinematic, high contrast, "
                    "dark background with glowing elements, YouTube thumbnail style"
                ),
                color_scheme="dark blue / teal / white",
                layout="curiosity_gap",
                estimated_ctr=5.2,
            ),
            ThumbnailVariant(
                title_text=safe_title.upper(),
                image_prompt=(
                    f"Bold statement thumbnail for '{safe_title}', {niche_lower} niche, "
                    "large bold text overlay, red and yellow color scheme, "
                    "explosive visual, impactful, YouTube thumbnail style"
                ),
                color_scheme="red / yellow / black",
                layout="bold_claim",
                estimated_ctr=4.8,
            ),
            ThumbnailVariant(
                title_text=safe_title,
                image_prompt=(
                    f"Person-forward thumbnail for '{safe_title}', {niche_lower} niche, "
                    "expressive face filling 60% of frame, surprised or excited expression, "
                    "text overlay on right side, bright background, YouTube thumbnail style"
                ),
                color_scheme="bright background / skin tones / white text",
                layout="face_forward",
                estimated_ctr=6.1,
            ),
            ThumbnailVariant(
                title_text=safe_title[:30],
                image_prompt=(
                    f"Minimalist clean thumbnail for '{safe_title}', {niche_lower} niche, "
                    "white or light background, single icon or symbol, "
                    "clean sans-serif typography, professional, modern, YouTube thumbnail style"
                ),
                color_scheme="white / accent color / dark text",
                layout="minimalist",
                estimated_ctr=3.9,
            ),
        ]

        return variants[: max(1, min(count, 4))]

    def best_variant(self, variants: list[ThumbnailVariant]) -> ThumbnailVariant | None:
        """Return the variant with the highest estimated CTR."""
        if not variants:
            return None
        return max(variants, key=lambda v: v.estimated_ctr)

    def ctr_benchmark(self, niche: str) -> dict:
        """Return CTR benchmarks for the given niche."""
        key = niche.lower().strip()
        return self._NICHE_BENCHMARKS.get(key, self._NICHE_BENCHMARKS["general"])


# ── Singleton ──────────────────────────────────────────────────────────────────

_optimizer_instance: ThumbnailOptimizer | None = None


def get_thumbnail_optimizer() -> ThumbnailOptimizer:
    global _optimizer_instance
    if _optimizer_instance is None:
        _optimizer_instance = ThumbnailOptimizer()
    return _optimizer_instance
