"""
ARIA AI — Design Division
Phase 10: Professional design capability system.

Six design agents:
  - uiux_designer: UI spec/wireframe descriptions
  - graphic_designer: Ad creative briefs and copy
  - brand_designer: Brand kit specs
  - motion_designer: Animation specs
  - video_producer: Video scripts with scenes
  - figma_specialist: Figma-ready component specs (stub)
"""
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Optional

from apps.core.memory.redis_client import get_cache
from apps.core.tools.ai_client import get_ai_client, AIModel

# ── Redis configuration ────────────────────────────────────────────────────────
_REDIS_KEY = "workforce:design:v1"
_TTL_90D = 60 * 60 * 24 * 90


# ══════════════════════════════════════════════════════════════════════════════
# Domain object
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class DesignAsset:
    asset_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    asset_type: str = ""
    agent_type: str = ""
    title: str = ""
    description: str = ""
    specs: dict = field(default_factory=dict)
    ai_prompt: str = ""
    output_description: str = ""
    figma_url: Optional[str] = None
    quality_score: float = 0.0
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            "asset_id": self.asset_id,
            "asset_type": self.asset_type,
            "agent_type": self.agent_type,
            "title": self.title,
            "description": self.description,
            "specs": self.specs,
            "ai_prompt": self.ai_prompt,
            "output_description": self.output_description,
            "figma_url": self.figma_url,
            "quality_score": self.quality_score,
            "created_at": self.created_at,
        }


# ══════════════════════════════════════════════════════════════════════════════
# Design Division
# ══════════════════════════════════════════════════════════════════════════════

class DesignDivision:
    """
    Manages a fleet of AI-powered design agents.
    State is persisted in Redis (key: workforce:design:v1, TTL 90d).
    """

    def __init__(self):
        self._assets: list[dict] = []

    # ── Internal helpers ───────────────────────────────────────────────────────

    def _quality_score(self, content: str) -> float:
        """Score based on word count — richer output → higher quality."""
        words = len(content.split())
        score = 0.5 + (words / 2000)
        return min(score, 0.95)

    async def _load(self) -> None:
        cache = get_cache()
        data = await cache.get(_REDIS_KEY)
        if isinstance(data, dict):
            self._assets = data.get("assets", [])
        elif isinstance(data, list):
            self._assets = data

    async def _save(self) -> None:
        cache = get_cache()
        await cache.set(_REDIS_KEY, {"assets": self._assets}, ttl_seconds=_TTL_90D)

    async def _run_design_task(
        self,
        asset_type: str,
        agent_type: str,
        title: str,
        description: str,
        specs: dict,
        system_prompt: str,
        user_prompt: str,
        model: AIModel = AIModel.CREATIVE,
        figma_url: Optional[str] = None,
    ) -> DesignAsset:
        asset = DesignAsset(
            asset_type=asset_type,
            agent_type=agent_type,
            title=title,
            description=description,
            specs=specs,
            ai_prompt=user_prompt[:500],
            figma_url=figma_url,
        )
        try:
            ai = get_ai_client()
            resp = await ai.complete(
                system=system_prompt,
                user=user_prompt,
                model=model,
                max_tokens=1500,
            )
            if resp.success:
                asset.output_description = resp.content
                asset.quality_score = self._quality_score(resp.content)
            else:
                asset.output_description = "Design generation failed — no AI response"
                asset.quality_score = 0.0
        except Exception as exc:
            asset.output_description = f"Error: {exc}"
            asset.quality_score = 0.0

        await self._load()
        self._assets.append(asset.to_dict())
        await self._save()
        return asset

    # ── Design agents ──────────────────────────────────────────────────────────

    async def ui_design_task(
        self, title: str, requirements: dict, platform: str = "web"
    ) -> DesignAsset:
        """Produce a detailed UI spec/wireframe description."""
        system = (
            "You are a senior UI/UX designer with expertise in design systems, "
            "accessibility (WCAG 2.1 AA), and modern web/mobile patterns. "
            "Produce detailed wireframe descriptions, component hierarchies, "
            "interaction states, and user flow notes. Be specific about layout, "
            "spacing, typography, and color usage."
        )
        user = (
            f"Design task: {title}\n"
            f"Platform: {platform}\n\n"
            f"Requirements:\n{requirements}\n\n"
            "Produce a detailed UI specification including layout wireframe description, "
            "component list with props, interaction states, responsive breakpoints, "
            "and accessibility notes."
        )
        return await self._run_design_task(
            asset_type="ui_component",
            agent_type="uiux_designer",
            title=title,
            description=f"UI design for {platform}",
            specs={"platform": platform, "requirements": requirements},
            system_prompt=system,
            user_prompt=user,
        )

    async def ad_creative_task(
        self,
        title: str,
        product: str,
        audience: str,
        format: str = "1080x1080",
    ) -> DesignAsset:
        """Produce an ad creative brief plus copy."""
        system = (
            "You are a creative director specializing in performance marketing. "
            "Produce complete ad creative briefs with visual direction, headline "
            "variants, body copy, CTA options, color palette, and imagery guidelines. "
            "Optimize for the specified format and target audience psychology."
        )
        user = (
            f"Ad campaign: {title}\n"
            f"Product: {product}\n"
            f"Target audience: {audience}\n"
            f"Format: {format}\n\n"
            "Produce a complete ad creative brief including:\n"
            "1. Visual direction (layout, imagery, color scheme)\n"
            "2. Headline variants (3 options)\n"
            "3. Body copy\n"
            "4. CTA button text variants\n"
            "5. Typography guidelines\n"
            "6. A/B test suggestions"
        )
        return await self._run_design_task(
            asset_type="ad_creative",
            agent_type="graphic_designer",
            title=title,
            description=f"Ad creative for {product}",
            specs={"product": product, "audience": audience, "format": format},
            system_prompt=system,
            user_prompt=user,
        )

    async def brand_kit_task(
        self,
        brand_name: str,
        industry: str,
        style_preferences: dict,
    ) -> DesignAsset:
        """Produce a complete brand kit spec (colors, fonts, logo concepts)."""
        system = (
            "You are a brand identity designer with 15 years of experience. "
            "Produce comprehensive brand kit specifications including primary/secondary "
            "color palettes with hex values, typography pairings, logo concept descriptions, "
            "brand voice guidelines, and usage rules."
        )
        user = (
            f"Brand: {brand_name}\n"
            f"Industry: {industry}\n"
            f"Style preferences: {style_preferences}\n\n"
            "Produce a complete brand kit specification:\n"
            "1. Color palette (primary, secondary, accent, neutral — with hex codes)\n"
            "2. Typography (heading font, body font, mono font — with rationale)\n"
            "3. Logo concept descriptions (3 directions)\n"
            "4. Brand voice & tone guidelines\n"
            "5. Spacing and grid system\n"
            "6. Do's and don'ts"
        )
        return await self._run_design_task(
            asset_type="brand_kit",
            agent_type="brand_designer",
            title=f"{brand_name} Brand Kit",
            description=f"Brand identity for {brand_name} in {industry}",
            specs={"brand_name": brand_name, "industry": industry, "style": style_preferences},
            system_prompt=system,
            user_prompt=user,
            model=AIModel.STRATEGY,
        )

    async def video_script_task(
        self,
        title: str,
        topic: str,
        duration_seconds: int = 60,
        platform: str = "tiktok",
    ) -> DesignAsset:
        """Produce a video script with scenes and timing."""
        system = (
            "You are an expert video scriptwriter and content strategist. "
            "Write engaging video scripts optimized for the target platform with "
            "scene descriptions, on-screen text, voiceover copy, and b-roll suggestions. "
            "Include hook in first 3 seconds, structured narrative arc, and strong CTA."
        )
        user = (
            f"Video title: {title}\n"
            f"Topic: {topic}\n"
            f"Duration: {duration_seconds} seconds\n"
            f"Platform: {platform}\n\n"
            "Produce a complete video script including:\n"
            "1. Hook (first 3 seconds)\n"
            "2. Scene-by-scene breakdown with timestamps\n"
            "3. On-screen text/captions\n"
            "4. Voiceover script\n"
            "5. B-roll and visual suggestions\n"
            "6. CTA scene\n"
            "7. Music/sound suggestions"
        )
        return await self._run_design_task(
            asset_type="video_script",
            agent_type="video_producer",
            title=title,
            description=f"{duration_seconds}s video for {platform}",
            specs={"topic": topic, "duration_seconds": duration_seconds, "platform": platform},
            system_prompt=system,
            user_prompt=user,
            model=AIModel.CREATIVE,
        )

    async def figma_design_task(
        self, title: str, component_spec: dict
    ) -> DesignAsset:
        """
        Produce a Figma-ready component specification.
        (Stub — no actual Figma API call; produces detailed AI spec instead.)
        """
        system = (
            "You are a Figma design expert and design systems specialist. "
            "Produce detailed Figma component specifications including auto-layout rules, "
            "component properties, variants, tokens, and implementation notes for "
            "developers. Format output as a structured Figma component guide."
        )
        user = (
            f"Component: {title}\n\n"
            f"Spec:\n{component_spec}\n\n"
            "Produce a Figma-ready component specification including:\n"
            "1. Component structure (frames, groups, layers)\n"
            "2. Auto-layout configuration\n"
            "3. Component properties and variants\n"
            "4. Design token references (colors, typography, spacing)\n"
            "5. Interactive states (hover, focus, disabled, loading)\n"
            "6. Responsive behavior\n"
            "7. Developer handoff notes"
        )
        # Stub figma_url — would be populated by real Figma API integration
        stub_figma_url = f"https://figma.com/file/stub/{title.lower().replace(' ', '-')}"
        return await self._run_design_task(
            asset_type="ui_component",
            agent_type="figma_specialist",
            title=title,
            description="Figma component specification",
            specs={"component_spec": component_spec},
            system_prompt=system,
            user_prompt=user,
            model=AIModel.FAST,
            figma_url=stub_figma_url,
        )

    async def motion_design_task(
        self, title: str, animation_brief: dict
    ) -> DesignAsset:
        """Produce animation spec with timing details."""
        system = (
            "You are a motion designer and animation director. "
            "Produce detailed animation specifications including keyframe descriptions, "
            "easing curves, timing functions, element transitions, and implementation "
            "notes for CSS/Framer Motion/GSAP. Be precise about durations and delays."
        )
        user = (
            f"Animation: {title}\n\n"
            f"Brief:\n{animation_brief}\n\n"
            "Produce a complete motion design specification:\n"
            "1. Animation overview and concept\n"
            "2. Element-by-element breakdown with timing (ms)\n"
            "3. Easing curves for each transition\n"
            "4. Keyframe sequence descriptions\n"
            "5. Stagger patterns (if applicable)\n"
            "6. CSS/Framer Motion implementation snippets\n"
            "7. Performance considerations"
        )
        return await self._run_design_task(
            asset_type="motion_design",
            agent_type="motion_designer",
            title=title,
            description="Motion design specification",
            specs={"animation_brief": animation_brief},
            system_prompt=system,
            user_prompt=user,
            model=AIModel.CREATIVE,
        )

    # ── Division-level methods ─────────────────────────────────────────────────

    def design_stats(self) -> dict:
        """Return aggregate statistics for all design assets."""
        total = len(self._assets)
        by_type: dict[str, int] = {}
        total_quality = 0.0
        for a in self._assets:
            asset_type = a.get("asset_type", "unknown")
            by_type[asset_type] = by_type.get(asset_type, 0) + 1
            total_quality += a.get("quality_score", 0.0)
        return {
            "total_assets": total,
            "by_type": by_type,
            "avg_quality_score": round(total_quality / total, 3) if total else 0.0,
        }

    def brand_assets(self) -> list[dict]:
        """Return all brand_kit assets."""
        return [a for a in self._assets if a.get("asset_type") == "brand_kit"]

    def recent_designs(self, limit: int = 10) -> list[dict]:
        """Return the most recent design assets, newest first."""
        return list(reversed(self._assets))[:limit]

    async def design_system(self, brand_name: str) -> dict:
        """
        Generate a full design system spec: colors, typography, spacing, components.
        """
        system = (
            "You are a design systems architect. Produce a comprehensive design system "
            "specification in structured format covering all foundational tokens and "
            "component patterns."
        )
        user = (
            f"Brand: {brand_name}\n\n"
            "Produce a complete design system specification with these sections:\n"
            "1. Colors (semantic tokens: primary, secondary, accent, neutral, semantic)\n"
            "2. Typography (scale, families, weights, line-heights)\n"
            "3. Spacing (scale: 4px base, all multiples)\n"
            "4. Shadows and elevation\n"
            "5. Border radius tokens\n"
            "6. Core component list with brief specs\n"
            "7. Motion and animation tokens\n"
            "8. Responsive breakpoints\n"
            "Format as a structured spec document."
        )
        ai = get_ai_client()
        resp = await ai.complete(
            system=system,
            user=user,
            model=AIModel.STRATEGY,
            max_tokens=2000,
        )
        content = resp.content if resp.success else ""
        return {
            "brand_name": brand_name,
            "colors": _extract_section(content, "Colors", "color palette specification"),
            "typography": _extract_section(content, "Typography", "typography scale and families"),
            "spacing": _extract_section(content, "Spacing", "spacing scale based on 4px"),
            "shadows": _extract_section(content, "Shadows", "elevation and shadow tokens"),
            "border_radius": _extract_section(content, "Border radius", "rounded corner tokens"),
            "components": _extract_section(content, "components", "core component specifications"),
            "motion": _extract_section(content, "Motion", "animation and transition tokens"),
            "breakpoints": _extract_section(content, "breakpoints", "responsive breakpoints"),
            "full_spec": content,
        }


def _extract_section(content: str, keyword: str, fallback: str) -> str:
    """Best-effort extraction of a section from AI output."""
    lines = content.split("\n")
    for i, line in enumerate(lines):
        if keyword.lower() in line.lower():
            section_lines = [line]
            for j in range(i + 1, min(i + 15, len(lines))):
                next_line = lines[j]
                # Stop at next heading
                if next_line.startswith("#") and j != i:
                    break
                section_lines.append(next_line)
            return "\n".join(section_lines).strip()
    return fallback


# ── Singleton ──────────────────────────────────────────────────────────────────

_instance: Optional[DesignDivision] = None


def get_design_division() -> DesignDivision:
    global _instance
    if _instance is None:
        _instance = DesignDivision()
    return _instance
