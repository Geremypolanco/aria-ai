"""
Persistent brand identity management system.
Stores BrandProfile objects in Redis with in-memory caching layer.
"""

from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass, field
from enum import StrEnum

from apps.core.memory.redis_client import get_cache

logger = logging.getLogger("aria.brand_engine")

_REDIS_KEY = "brand:profiles:v1"
_REDIS_TTL = 86400 * 365  # 1 year


# ── Enums ──────────────────────────────────────────────────────────────────────


class BrandTone(StrEnum):
    PROFESSIONAL = "professional"
    FRIENDLY = "friendly"
    BOLD = "bold"
    LUXURIOUS = "luxurious"
    PLAYFUL = "playful"
    MINIMALIST = "minimalist"
    AUTHORITATIVE = "authoritative"


# ── Dataclasses ────────────────────────────────────────────────────────────────


@dataclass
class ColorPalette:
    primary: str
    secondary: str
    accent: str
    background: str
    text: str

    def to_dict(self) -> dict:
        return {
            "primary": self.primary,
            "secondary": self.secondary,
            "accent": self.accent,
            "background": self.background,
            "text": self.text,
        }

    @classmethod
    def from_dict(cls, d: dict) -> ColorPalette:
        return cls(
            primary=d.get("primary", "#000000"),
            secondary=d.get("secondary", "#FFFFFF"),
            accent=d.get("accent", "#888888"),
            background=d.get("background", "#FFFFFF"),
            text=d.get("text", "#000000"),
        )


@dataclass
class Typography:
    heading_font: str
    body_font: str
    heading_weight: str = "700"
    body_size: str = "16px"

    def to_dict(self) -> dict:
        return {
            "heading_font": self.heading_font,
            "body_font": self.body_font,
            "heading_weight": self.heading_weight,
            "body_size": self.body_size,
        }

    @classmethod
    def from_dict(cls, d: dict) -> Typography:
        return cls(
            heading_font=d.get("heading_font", "Inter"),
            body_font=d.get("body_font", "Inter"),
            heading_weight=d.get("heading_weight", "700"),
            body_size=d.get("body_size", "16px"),
        )


@dataclass
class BrandVoice:
    tone: BrandTone
    keywords: list[str] = field(default_factory=list)
    avoid_words: list[str] = field(default_factory=list)
    style_notes: str = ""
    sample_headlines: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "tone": self.tone.value,
            "keywords": self.keywords,
            "avoid_words": self.avoid_words,
            "style_notes": self.style_notes,
            "sample_headlines": self.sample_headlines,
        }

    @classmethod
    def from_dict(cls, d: dict) -> BrandVoice:
        return cls(
            tone=BrandTone(d.get("tone", BrandTone.PROFESSIONAL.value)),
            keywords=d.get("keywords", []),
            avoid_words=d.get("avoid_words", []),
            style_notes=d.get("style_notes", ""),
            sample_headlines=d.get("sample_headlines", []),
        )


@dataclass
class BrandProfile:
    brand_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    name: str = ""
    niche: str = ""
    palette: ColorPalette = field(
        default_factory=lambda: ColorPalette("#000000", "#FFFFFF", "#888888", "#FFFFFF", "#000000")
    )
    typography: Typography = field(default_factory=lambda: Typography("Inter", "Inter"))
    voice: BrandVoice = field(default_factory=lambda: BrandVoice(tone=BrandTone.PROFESSIONAL))
    logo_url: str = ""
    tagline: str = ""
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            "brand_id": self.brand_id,
            "name": self.name,
            "niche": self.niche,
            "palette": self.palette.to_dict(),
            "typography": self.typography.to_dict(),
            "voice": self.voice.to_dict(),
            "logo_url": self.logo_url,
            "tagline": self.tagline,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, d: dict) -> BrandProfile:
        return cls(
            brand_id=d.get("brand_id", str(uuid.uuid4())),
            name=d.get("name", ""),
            niche=d.get("niche", ""),
            palette=ColorPalette.from_dict(d.get("palette", {})),
            typography=Typography.from_dict(d.get("typography", {})),
            voice=BrandVoice.from_dict(d.get("voice", {})),
            logo_url=d.get("logo_url", ""),
            tagline=d.get("tagline", ""),
            created_at=d.get("created_at", time.time()),
            updated_at=d.get("updated_at", time.time()),
        )


# ── Niche defaults ─────────────────────────────────────────────────────────────


def _palette_for_niche(niche: str) -> ColorPalette:
    """Return a niche-appropriate default color palette."""
    n = niche.lower()
    if "ecommerce" in n or "shop" in n or "retail" in n:
        return ColorPalette(
            primary="#0066CC",
            secondary="#FFFFFF",
            accent="#D4A017",
            background="#F8F9FA",
            text="#1A1A1A",
        )
    if "fitness" in n or "gym" in n or "sport" in n:
        return ColorPalette(
            primary="#CC0000",
            secondary="#1A1A1A",
            accent="#FFFFFF",
            background="#0A0A0A",
            text="#FFFFFF",
        )
    if "tech" in n or "software" in n or "saas" in n or "ai" in n:
        return ColorPalette(
            primary="#6C3FC5",
            secondary="#1E1E2E",
            accent="#00E5FF",
            background="#0F0F1A",
            text="#E8E8F0",
        )
    if "beauty" in n or "fashion" in n or "cosmetic" in n:
        return ColorPalette(
            primary="#E91E8C",
            secondary="#D4AF37",
            accent="#FFF0F5",
            background="#FFFAFA",
            text="#2C1A1A",
        )
    # general / default
    return ColorPalette(
        primary="#2563EB",
        secondary="#64748B",
        accent="#F59E0B",
        background="#FFFFFF",
        text="#1E293B",
    )


def _voice_for_tone(tone: BrandTone) -> BrandVoice:
    """Return sensible default voice config for a given tone."""
    defaults: dict[BrandTone, dict] = {
        BrandTone.PROFESSIONAL: {
            "keywords": ["reliable", "expert", "trusted", "results"],
            "avoid_words": ["cheap", "quick fix", "hack", "trick"],
            "style_notes": "Clear, concise, and authoritative. Use data to support claims.",
            "sample_headlines": [
                "Proven strategies for measurable growth",
                "The expert's guide to sustainable success",
            ],
        },
        BrandTone.FRIENDLY: {
            "keywords": ["easy", "simple", "together", "community", "help"],
            "avoid_words": ["difficult", "complex", "jargon", "exclusive"],
            "style_notes": "Warm, conversational. Use 'you' and 'we'. Short sentences.",
            "sample_headlines": [
                "Let's grow together",
                "We make it easy for you",
            ],
        },
        BrandTone.BOLD: {
            "keywords": ["dominate", "crush", "unstoppable", "revolutionary", "powerful"],
            "avoid_words": ["maybe", "try", "somewhat", "average"],
            "style_notes": "High energy. Use action verbs. Make big, confident statements.",
            "sample_headlines": [
                "Dominate your market in 90 days",
                "Stop playing small — go all in",
            ],
        },
        BrandTone.LUXURIOUS: {
            "keywords": ["exclusive", "curated", "premium", "refined", "bespoke"],
            "avoid_words": ["cheap", "discount", "affordable", "budget", "deal"],
            "style_notes": "Elegant and understated. Evoke exclusivity and craftsmanship.",
            "sample_headlines": [
                "Crafted for the discerning few",
                "Where quality meets exclusivity",
            ],
        },
        BrandTone.PLAYFUL: {
            "keywords": ["fun", "wow", "amazing", "love", "awesome", "joy"],
            "avoid_words": ["serious", "formal", "strict", "rigid"],
            "style_notes": "Energetic, emoji-friendly, casual. Don't take yourself too seriously.",
            "sample_headlines": [
                "This changes everything (in the best way!)",
                "Making your day a little brighter",
            ],
        },
        BrandTone.MINIMALIST: {
            "keywords": ["clean", "simple", "essential", "pure", "focused"],
            "avoid_words": ["complicated", "busy", "cluttered", "overloaded"],
            "style_notes": "Less is more. Single clear idea per sentence. White space matters.",
            "sample_headlines": [
                "Less noise. More signal.",
                "One thing. Done perfectly.",
            ],
        },
        BrandTone.AUTHORITATIVE: {
            "keywords": ["proven", "research", "data-driven", "evidence", "industry-leading"],
            "avoid_words": ["guess", "maybe", "might", "supposedly"],
            "style_notes": "Back every claim with evidence. Use formal language and statistics.",
            "sample_headlines": [
                "Research-backed strategies for peak performance",
                "Industry data reveals what actually works",
            ],
        },
    }
    d = defaults.get(tone, defaults[BrandTone.PROFESSIONAL])
    return BrandVoice(
        tone=tone,
        keywords=d["keywords"],
        avoid_words=d["avoid_words"],
        style_notes=d["style_notes"],
        sample_headlines=d["sample_headlines"],
    )


# ── BrandEngine ────────────────────────────────────────────────────────────────


class BrandEngine:
    """Persistent brand identity manager with Redis + in-memory caching."""

    def __init__(self) -> None:
        self._profiles: dict[str, BrandProfile] = {}
        self._loaded: bool = False

    # ── Persistence ────────────────────────────────────────────────────────────

    async def _load(self) -> None:
        if self._loaded:
            return
        try:
            cache = get_cache()
            data = await cache.get(_REDIS_KEY)
            if data and isinstance(data, dict):
                self._profiles = {bid: BrandProfile.from_dict(bd) for bid, bd in data.items()}
        except Exception as exc:
            logger.warning("Could not load brand profiles from Redis: %s", exc)
        self._loaded = True

    async def _persist(self) -> None:
        try:
            cache = get_cache()
            payload = {bid: bp.to_dict() for bid, bp in self._profiles.items()}
            await cache.set(_REDIS_KEY, payload, ttl_seconds=_REDIS_TTL)
        except Exception as exc:
            logger.warning("Could not persist brand profiles to Redis: %s", exc)

    # ── CRUD ───────────────────────────────────────────────────────────────────

    async def create_brand(
        self,
        name: str,
        niche: str,
        tone: BrandTone = BrandTone.PROFESSIONAL,
    ) -> BrandProfile:
        """Create and persist a new BrandProfile with auto-generated defaults."""
        await self._load()
        palette = _palette_for_niche(niche)
        typography = Typography(
            heading_font="Inter",
            body_font="Inter",
            heading_weight="700",
            body_size="16px",
        )
        voice = _voice_for_tone(tone)
        profile = BrandProfile(
            name=name,
            niche=niche,
            palette=palette,
            typography=typography,
            voice=voice,
        )
        self._profiles[profile.brand_id] = profile
        await self._persist()
        logger.info("Created brand '%s' (id=%s, niche=%s)", name, profile.brand_id, niche)
        return profile

    async def get_brand(self, brand_id: str) -> BrandProfile | None:
        """Return a BrandProfile by ID, or None if not found."""
        await self._load()
        return self._profiles.get(brand_id)

    async def list_brands(self) -> list[BrandProfile]:
        """Return all stored brand profiles."""
        await self._load()
        return list(self._profiles.values())

    async def update_palette(self, brand_id: str, palette: ColorPalette) -> BrandProfile | None:
        """Update only the color palette for a brand."""
        await self._load()
        profile = self._profiles.get(brand_id)
        if profile is None:
            return None
        profile.palette = palette
        profile.updated_at = time.time()
        await self._persist()
        return profile

    async def update_voice(self, brand_id: str, voice: BrandVoice) -> BrandProfile | None:
        """Update only the brand voice for a brand."""
        await self._load()
        profile = self._profiles.get(brand_id)
        if profile is None:
            return None
        profile.voice = voice
        profile.updated_at = time.time()
        await self._persist()
        return profile

    # ── Prompt helpers ─────────────────────────────────────────────────────────

    def prompt_prefix(self, brand_id: str) -> str:
        """
        Return a short brand style prefix for image generation prompts.
        Returns empty string if brand not loaded yet or not found.
        """
        profile = self._profiles.get(brand_id)
        if profile is None:
            return ""
        return (
            f"In the style of {profile.name} brand: {profile.voice.tone.value} tone, "
            f"colors {profile.palette.primary}/{profile.palette.secondary}, "
        )

    def voice_prompt(self, brand_id: str, content_type: str) -> str:
        """
        Return LLM writing style instructions for a content type.
        Returns empty string if brand not found.
        """
        profile = self._profiles.get(brand_id)
        if profile is None:
            return ""
        kw_str = ", ".join(profile.voice.keywords[:6]) if profile.voice.keywords else "—"
        avoid_str = ", ".join(profile.voice.avoid_words[:6]) if profile.voice.avoid_words else "—"
        return (
            f"Write in {profile.voice.tone.value} tone. "
            f"Use these keywords: {kw_str}. "
            f"Avoid: {avoid_str}. "
            f"Keep it {profile.voice.style_notes} "
            f"Content type: {content_type}."
        )

    def consistency_check(self, brand_id: str, content: str) -> dict:
        """
        Check whether content aligns with brand voice guidelines.
        Returns: score (0-100), violations list, suggestions list.
        """
        profile = self._profiles.get(brand_id)
        if profile is None:
            return {"score": 0, "violations": ["Brand not found"], "suggestions": []}

        content_lower = content.lower()
        violations: list[str] = []
        suggestions: list[str] = []
        score = 100

        # Check for forbidden words
        for word in profile.voice.avoid_words:
            if word.lower() in content_lower:
                violations.append(f"Contains avoided word: '{word}'")
                score -= 15

        # Check for keyword presence (reward, not penalise absence)
        keyword_hits = sum(1 for kw in profile.voice.keywords if kw.lower() in content_lower)
        keyword_total = len(profile.voice.keywords) or 1
        keyword_ratio = keyword_hits / keyword_total
        if keyword_ratio < 0.25:
            suggestions.append(
                f"Consider using more brand keywords: {', '.join(profile.voice.keywords[:3])}"
            )
            score -= 10
        elif keyword_ratio >= 0.5:
            suggestions.append("Good keyword usage — content feels on-brand.")

        # Tone check (simple length heuristic for minimalist)
        if profile.voice.tone == BrandTone.MINIMALIST:
            avg_sentence_len = len(content.split()) / max(
                content.count(".") + content.count("!") + content.count("?"), 1
            )
            if avg_sentence_len > 20:
                violations.append("Sentences are too long for a minimalist brand voice.")
                score -= 10
                suggestions.append("Shorten sentences to under 15 words for minimalist clarity.")

        score = max(0, min(score, 100))
        return {
            "score": score,
            "violations": violations,
            "suggestions": suggestions,
        }


# ── Singleton ──────────────────────────────────────────────────────────────────

_engine_instance: BrandEngine | None = None


def get_brand_engine() -> BrandEngine:
    global _engine_instance
    if _engine_instance is None:
        _engine_instance = BrandEngine()
    return _engine_instance
