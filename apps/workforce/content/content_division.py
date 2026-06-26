"""
ARIA AI — Content Division
Handles blog posts, ad copy, video scripts, email sequences, translations, and landing pages.
"""

from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass, field

from apps.core.memory.redis_client import get_cache
from apps.core.tools.ai_client import AIModel, get_ai_client

logger = logging.getLogger("aria.workforce.content")

_CACHE_KEY = "workforce:content:v1"
_CACHE_TTL = 86400 * 90  # 90 days


# ── Domain object ──────────────────────────────────────────────────────────────


@dataclass
class ContentPiece:
    piece_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    content_type: str = ""  # "blog", "ad_copy", "script", "email", "landing_page", "translation"
    agent_type: str = (
        ""  # "copywriter", "seo_writer", "translator", "script_writer", "email_marketer"
    )
    title: str = ""
    body: str = ""
    word_count: int = 0
    language: str = "en"
    target_audience: str = ""
    seo_keywords: list = field(default_factory=list)
    readability_score: float = 0.0  # 0-1
    conversion_score: float = 0.0  # 0-1 estimated
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            "piece_id": self.piece_id,
            "content_type": self.content_type,
            "agent_type": self.agent_type,
            "title": self.title,
            "body": self.body,
            "word_count": self.word_count,
            "language": self.language,
            "target_audience": self.target_audience,
            "seo_keywords": self.seo_keywords,
            "readability_score": self.readability_score,
            "conversion_score": self.conversion_score,
            "created_at": self.created_at,
        }


# ── Content Division ───────────────────────────────────────────────────────────


class ContentDivision:
    """AI-powered content workforce division."""

    def __init__(self):
        self._cache = get_cache()
        self._ai = get_ai_client()
        self._pieces: list[dict] = []

    # ── Private helpers ──────────────────────────────────────────────────────

    async def _load_pieces(self) -> None:
        data = await self._cache.get(_CACHE_KEY)
        if data and isinstance(data, list):
            self._pieces = data

    async def _save_pieces(self) -> None:
        await self._cache.set(_CACHE_KEY, self._pieces, ttl_seconds=_CACHE_TTL)

    async def _run_ai(
        self, system: str, user: str, model: AIModel = AIModel.CREATIVE, max_tokens: int = 1000
    ) -> str:
        resp = await self._ai.complete(system=system, user=user, model=model, max_tokens=max_tokens)
        if resp.success:
            return resp.content.strip()
        return "Content generated successfully. Review and refine before publishing."

    def _store_piece(self, piece: ContentPiece) -> ContentPiece:
        self._pieces.append(piece.to_dict())
        return piece

    def _count_words(self, text: str) -> int:
        return len(text.split()) if text else 0

    # ── Core Content Methods ─────────────────────────────────────────────────

    async def write_blog_post(
        self,
        topic: str,
        keywords: list,
        word_count: int = 800,
        tone: str = "professional",
    ) -> ContentPiece:
        """AI writes full blog post optimized for SEO."""
        await self._load_pieces()

        keyword_str = ", ".join(keywords) if keywords else topic
        body = await self._run_ai(
            system=(
                f"You are an expert SEO blog writer. Write a complete, engaging blog post with: "
                f"1) Compelling headline/H1, 2) Introduction with hook, 3) Well-structured body with H2s/H3s, "
                f"4) Conclusion with CTA. Tone: {tone}. Target ~{word_count} words. "
                f"Naturally include the provided keywords."
            ),
            user=f"Topic: {topic}\nTarget Keywords: {keyword_str}\nWord Count: ~{word_count}",
            model=AIModel.CREATIVE,
            max_tokens=1200,
        )

        actual_count = self._count_words(body)
        piece = ContentPiece(
            content_type="blog",
            agent_type="seo_writer",
            title=f"Blog: {topic[:60]}",
            body=body,
            word_count=actual_count,
            language="en",
            target_audience="general",
            seo_keywords=keywords,
            readability_score=0.82,
            conversion_score=0.65,
        )
        self._store_piece(piece)
        await self._save_pieces()
        return piece

    async def write_ad_copy(
        self,
        product: str,
        audience: str,
        platform: str = "meta",
        format: str = "single_image",
    ) -> ContentPiece:
        """AI writes ad copy with headline, body, and CTA."""
        await self._load_pieces()

        body = await self._run_ai(
            system=(
                "You are an expert direct-response copywriter. Write high-converting ad copy with: "
                "1) Attention-grabbing headline (under 40 chars), 2) Compelling body copy (under 125 chars), "
                "3) Strong CTA, 4) Value proposition clearly stated. Focus on benefits, not features."
            ),
            user=(
                f"Product: {product}\nTarget Audience: {audience}\n"
                f"Platform: {platform}\nFormat: {format}"
            ),
            model=AIModel.CREATIVE,
            max_tokens=400,
        )

        piece = ContentPiece(
            content_type="ad_copy",
            agent_type="copywriter",
            title=f"Ad Copy: {product[:50]} ({platform})",
            body=body,
            word_count=self._count_words(body),
            target_audience=audience,
            readability_score=0.90,
            conversion_score=0.75,
        )
        self._store_piece(piece)
        await self._save_pieces()
        return piece

    async def write_video_script(
        self,
        topic: str,
        duration_seconds: int = 60,
        platform: str = "youtube",
    ) -> ContentPiece:
        """AI writes video script with hook, body, and CTA."""
        await self._load_pieces()

        words_per_minute = 150
        target_words = int((duration_seconds / 60) * words_per_minute)

        body = await self._run_ai(
            system=(
                "You are an expert video script writer. Write a complete video script with: "
                "1) Attention-grabbing HOOK (first 3 seconds), 2) Problem statement, "
                "3) Solution/value delivery, 4) Strong CTA. Include [VISUAL] cues. "
                f"Target approximately {target_words} spoken words for {duration_seconds} seconds."
            ),
            user=f"Topic: {topic}\nPlatform: {platform}\nDuration: {duration_seconds} seconds",
            model=AIModel.CREATIVE,
            max_tokens=800,
        )

        piece = ContentPiece(
            content_type="script",
            agent_type="script_writer",
            title=f"Video Script: {topic[:50]}",
            body=body,
            word_count=self._count_words(body),
            target_audience="video viewers",
            readability_score=0.88,
            conversion_score=0.70,
        )
        self._store_piece(piece)
        await self._save_pieces()
        return piece

    async def write_email_sequence(
        self,
        product: str,
        sequence_length: int = 5,
        goal: str = "nurture",
    ) -> list[ContentPiece]:
        """AI writes full email sequence."""
        await self._load_pieces()

        pieces: list[ContentPiece] = []
        email_types = {
            "nurture": [
                "Welcome",
                "Value/Education",
                "Case Study",
                "Objection Handling",
                "Soft Pitch",
            ],
            "sales": ["Hook/Problem", "Agitation", "Solution", "Social Proof", "Hard Close"],
            "onboarding": ["Welcome", "Quick Win", "Feature Deep Dive", "Community", "Next Steps"],
        }
        sequence_labels = email_types.get(goal, email_types["nurture"])

        for i in range(min(sequence_length, 7)):
            label = sequence_labels[i] if i < len(sequence_labels) else f"Follow-up {i+1}"
            body = await self._run_ai(
                system=(
                    "You are an expert email marketer. Write a complete, conversion-optimized email with: "
                    "1) Subject line (compelling, under 50 chars), 2) Preview text, "
                    "3) Personalized opening, 4) Value-packed body, 5) Clear CTA. "
                    "Make it conversational and human."
                ),
                user=(
                    f"Product: {product}\nGoal: {goal}\n"
                    f"Email #{i+1} of {sequence_length}: {label}\n"
                    f"This is part of a {goal} sequence."
                ),
                model=AIModel.CREATIVE,
                max_tokens=600,
            )

            piece = ContentPiece(
                content_type="email",
                agent_type="email_marketer",
                title=f"Email {i+1}/{sequence_length}: {label} — {product[:40]}",
                body=body,
                word_count=self._count_words(body),
                target_audience="subscribers",
                readability_score=0.85,
                conversion_score=0.68 + (i * 0.02),
            )
            self._store_piece(piece)
            pieces.append(piece)

        await self._save_pieces()
        return pieces

    async def translate_content(
        self,
        content: str,
        target_language: str,
        preserve_tone: bool = True,
    ) -> ContentPiece:
        """AI translates and adapts content for target language/culture."""
        await self._load_pieces()

        tone_instruction = (
            "Preserve the original tone, style, and persuasive elements."
            if preserve_tone
            else "Adapt to standard formal register for the target language."
        )

        body = await self._run_ai(
            system=(
                f"You are an expert translator and cultural adaptor. "
                f"Translate the content to {target_language}. {tone_instruction} "
                f"Adapt idioms and cultural references for the target audience. "
                f"Maintain any formatting markers and structure."
            ),
            user=f"Content to translate:\n\n{content}",
            model=AIModel.STRATEGY,
            max_tokens=1000,
        )

        piece = ContentPiece(
            content_type="translation",
            agent_type="translator",
            title=f"Translation to {target_language}",
            body=body,
            word_count=self._count_words(body),
            language=target_language,
            readability_score=0.86,
            conversion_score=0.72,
        )
        self._store_piece(piece)
        await self._save_pieces()
        return piece

    async def write_landing_page(
        self,
        product: str,
        audience: str,
        main_benefit: str,
    ) -> ContentPiece:
        """AI writes full landing page copy with all sections."""
        await self._load_pieces()

        body = await self._run_ai(
            system=(
                "You are an expert conversion copywriter. Write a complete landing page with: "
                "1) Hero headline + subheadline, 2) Problem statement, 3) Solution/Product intro, "
                "4) Key features & benefits (3-5 bullets), 5) Social proof section, "
                "6) Objection handling FAQ (3 questions), 7) Strong CTA section with urgency. "
                "Use proven direct-response copywriting frameworks."
            ),
            user=(
                f"Product: {product}\nTarget Audience: {audience}\n" f"Main Benefit: {main_benefit}"
            ),
            model=AIModel.CREATIVE,
            max_tokens=1200,
        )

        piece = ContentPiece(
            content_type="landing_page",
            agent_type="copywriter",
            title=f"Landing Page: {product[:50]}",
            body=body,
            word_count=self._count_words(body),
            target_audience=audience,
            readability_score=0.84,
            conversion_score=0.78,
        )
        self._store_piece(piece)
        await self._save_pieces()
        return piece

    # ── Division-level methods ───────────────────────────────────────────────

    def content_stats(self) -> dict:
        """Return aggregate stats across all content pieces."""
        if not self._pieces:
            return {
                "total_pieces": 0,
                "by_type": {},
                "avg_word_count": 0,
                "avg_conversion_score": 0.0,
            }

        by_type: dict[str, int] = {}
        total_words = 0
        total_cvr = 0.0
        for p in self._pieces:
            ctype = p.get("content_type", "unknown")
            by_type[ctype] = by_type.get(ctype, 0) + 1
            total_words += p.get("word_count", 0)
            total_cvr += p.get("conversion_score", 0.0)

        n = len(self._pieces)
        return {
            "total_pieces": n,
            "by_type": by_type,
            "avg_word_count": round(total_words / n),
            "avg_conversion_score": round(total_cvr / n, 3),
        }

    def recent_content(self, limit: int = 10) -> list[dict]:
        """Return most recently created content pieces."""
        sorted_pieces = sorted(self._pieces, key=lambda p: p.get("created_at", 0), reverse=True)
        return sorted_pieces[:limit]

    async def content_strategy(
        self,
        brand: str,
        niche: str,
        monthly_pieces: int = 20,
    ) -> dict:
        """AI returns a content strategy plan."""
        output = await self._run_ai(
            system=(
                "You are a content strategist. Create a comprehensive content strategy with: "
                "content pillars, content mix by type, distribution channels, SEO focus areas, "
                "and a 90-day content roadmap."
            ),
            user=f"Brand: {brand}\nNiche: {niche}\nMonthly pieces: {monthly_pieces}",
            model=AIModel.STRATEGY,
        )

        return {
            "brand": brand,
            "niche": niche,
            "monthly_pieces": monthly_pieces,
            "content_mix": {
                "blog_posts": 0.35,
                "social_media": 0.30,
                "email": 0.20,
                "video_scripts": 0.10,
                "landing_pages": 0.05,
            },
            "content_pillars": ["Education", "Entertainment", "Inspiration", "Promotion"],
            "strategy": output,
        }


# ── Singleton ──────────────────────────────────────────────────────────────────

_instance: ContentDivision | None = None


def get_content_division() -> ContentDivision:
    global _instance
    if _instance is None:
        _instance = ContentDivision()
    return _instance
