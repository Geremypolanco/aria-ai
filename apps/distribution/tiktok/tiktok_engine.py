"""
ARIA AI — TikTok/Reels/Shorts Content Engine
Phase 13: Viral short-form video scripts for maximum reach and engagement.
Covers TikTok, Instagram Reels, YouTube Shorts.
"""

from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass, field

from apps.core.memory.redis_client import get_cache
from apps.core.tools.ai_client import AIModel, get_ai_client

logger = logging.getLogger("aria.distribution.tiktok")

_KEY = "distribution:tiktok:v1"
_TTL = 86400 * 30


@dataclass
class TikTokScript:
    script_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    topic: str = ""
    niche: str = ""
    platform: str = "tiktok"
    hook: str = ""
    main_content: str = ""
    cta: str = ""
    hashtags: list = field(default_factory=list)
    sound_suggestion: str = ""
    estimated_views: int = 0
    viral_potential: float = 0.0
    duration_seconds: int = 45
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            "script_id": self.script_id,
            "topic": self.topic,
            "niche": self.niche,
            "platform": self.platform,
            "hook": self.hook,
            "main_content": self.main_content,
            "cta": self.cta,
            "hashtags": self.hashtags,
            "sound_suggestion": self.sound_suggestion,
            "estimated_views": self.estimated_views,
            "viral_potential": self.viral_potential,
            "duration_seconds": self.duration_seconds,
            "created_at": self.created_at,
        }


@dataclass
class TrendHook:
    hook_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    hook_text: str = ""
    niche: str = ""
    hook_type: str = "curiosity"
    viral_score: float = 0.0
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            "hook_id": self.hook_id,
            "hook_text": self.hook_text,
            "niche": self.niche,
            "hook_type": self.hook_type,
            "viral_score": self.viral_score,
            "created_at": self.created_at,
        }


class TikTokEngine:

    def __init__(self) -> None:
        self._scripts: list[dict] = []
        self._loaded = False

    async def _load(self) -> None:
        if self._loaded:
            return
        try:
            cache = get_cache()
            data = await cache.get(_KEY)
            if isinstance(data, list):
                self._scripts = data
        except Exception as exc:
            logger.warning("TikTokEngine._load failed: %s", exc)
        self._loaded = True

    async def _save(self) -> None:
        try:
            cache = get_cache()
            await cache.set(_KEY, self._scripts[-1000:], ttl_seconds=_TTL)
        except Exception as exc:
            logger.warning("TikTokEngine._save failed: %s", exc)

    def _build_fallback_script(
        self, topic: str, niche: str, platform: str
    ) -> tuple[str, str, str, list, str]:
        hook = f"Wait — you NEED to hear this about {topic}"
        main_content = (
            f"Here's what nobody tells you about {topic} in the {niche} space.\n\n"
            f"First: the basics everyone skips.\n"
            f"Second: the shortcut that actually works.\n"
            f"Third: the one mistake that kills results.\n\n"
            f"I spent months learning this so you don't have to."
        )
        cta = f"Follow for more {niche} tips. Drop a comment if this helped!"
        hashtags = [
            f"#{niche.replace(' ', '')}",
            f"#{topic.replace(' ', '')}",
            "#viral",
            "#tips",
            "#fyp",
        ]
        sound_suggestion = "trending pop"
        return hook, main_content, cta, hashtags, sound_suggestion

    async def generate_script(
        self,
        topic: str,
        niche: str,
        platform: str = "tiktok",
    ) -> TikTokScript:
        await self._load()

        hook = ""
        main_content = ""
        cta = ""
        hashtags: list[str] = []
        sound_suggestion = "trending pop"

        try:
            ai = get_ai_client()
            resp = await ai.complete(
                system=(
                    "You are a TikTok viral content expert. Write a script with:\n"
                    "HOOK (3 sec, scroll-stopper ≤15 words)\n"
                    "MAIN (30-45 sec, fast-paced content)\n"
                    "CTA (5 sec, drive follow/comment/share)\n"
                    "5 hashtags\n"
                    "sound suggestion\n\n"
                    "Format each section with its label on its own line: HOOK:, MAIN:, CTA:, HASHTAGS:, SOUND:"
                ),
                user=f"Topic: {topic}\nNiche: {niche}\nPlatform: {platform}",
                model=AIModel.CREATIVE,
                max_tokens=600,
            )
            if resp.success and resp.content:
                lines = resp.content.strip().splitlines()
                section = ""
                buffer: list[str] = []
                sections: dict[str, str] = {}
                for line in lines:
                    stripped = line.strip()
                    upper = stripped.upper()
                    if upper.startswith("HOOK:"):
                        if section:
                            sections[section] = " ".join(buffer).strip()
                        section = "HOOK"
                        buffer = [stripped[5:].strip()]
                    elif upper.startswith("MAIN:"):
                        if section:
                            sections[section] = " ".join(buffer).strip()
                        section = "MAIN"
                        buffer = [stripped[5:].strip()]
                    elif upper.startswith("CTA:"):
                        if section:
                            sections[section] = " ".join(buffer).strip()
                        section = "CTA"
                        buffer = [stripped[4:].strip()]
                    elif upper.startswith("HASHTAGS:"):
                        if section:
                            sections[section] = " ".join(buffer).strip()
                        section = "HASHTAGS"
                        buffer = [stripped[9:].strip()]
                    elif upper.startswith("SOUND:"):
                        if section:
                            sections[section] = " ".join(buffer).strip()
                        section = "SOUND"
                        buffer = [stripped[6:].strip()]
                    elif stripped and section:
                        buffer.append(stripped)
                if section:
                    sections[section] = " ".join(buffer).strip()

                hook = sections.get("HOOK", lines[0] if lines else "").strip()
                main_content = sections.get("MAIN", "").strip()
                cta = sections.get("CTA", "").strip()
                raw_tags = sections.get("HASHTAGS", "")
                hashtags = [
                    t.strip()
                    for t in raw_tags.replace(",", " ").split()
                    if t.strip().startswith("#")
                ][:7]
                sound_suggestion = sections.get("SOUND", "trending pop").strip() or "trending pop"

                if not hook and lines:
                    hook = lines[0].strip()
        except Exception as exc:
            logger.warning("TikTokEngine.generate_script AI call failed: %s", exc)

        if not hook:
            hook, main_content, cta, hashtags, sound_suggestion = self._build_fallback_script(
                topic, niche, platform
            )

        if not hashtags:
            hashtags = [
                f"#{niche.replace(' ', '')}",
                f"#{topic.replace(' ', '')}",
                "#viral",
                "#fyp",
                "#trending",
            ]

        hook_words = hook.split()
        viral_potential = round(min(0.4 + len(hook_words) / 20, 0.95), 3)
        estimated_views = int(viral_potential * 50000)

        script = TikTokScript(
            topic=topic,
            niche=niche,
            platform=platform,
            hook=hook,
            main_content=main_content,
            cta=cta,
            hashtags=hashtags[:7],
            sound_suggestion=sound_suggestion,
            estimated_views=estimated_views,
            viral_potential=viral_potential,
        )
        self._scripts.append(script.to_dict())
        await self._save()
        return script

    async def batch_generate(self, topics: list[str], niche: str) -> list[TikTokScript]:
        await self._load()
        results: list[TikTokScript] = []
        for topic in topics:
            try:
                script = await self.generate_script(topic, niche)
                results.append(script)
            except Exception as exc:
                logger.warning("TikTokEngine.batch_generate failed for topic '%s': %s", topic, exc)
        return results

    async def generate_trend_hooks(self, niche: str, count: int = 5) -> list[TrendHook]:
        await self._load()
        hooks: list[TrendHook] = []

        try:
            ai = get_ai_client()
            resp = await ai.complete(
                system=(
                    f"You are a TikTok scroll-stopping hook expert. Generate {count} viral hooks for the '{niche}' niche.\n"
                    "Each hook must be ≤15 words, extremely attention-grabbing, and belong to one type: "
                    "curiosity, controversy, relatability, shock, or value.\n"
                    "Format each hook on its own line as: [TYPE] hook text here\n"
                    "Example: [curiosity] Nobody talks about this {niche} secret that changes everything"
                ),
                user=f"Niche: {niche}\nGenerate {count} hooks.",
                model=AIModel.CREATIVE,
                max_tokens=400,
            )
            if resp.success and resp.content:
                hook_types = {"curiosity", "controversy", "relatability", "shock", "value"}
                for line in resp.content.strip().splitlines():
                    line = line.strip()
                    if not line:
                        continue
                    hook_type = "curiosity"
                    hook_text = line
                    if line.startswith("["):
                        end = line.find("]")
                        if end != -1:
                            candidate = line[1:end].lower()
                            if candidate in hook_types:
                                hook_type = candidate
                            hook_text = line[end + 1 :].strip()
                    words = hook_text.split()
                    if not hook_text or len(words) > 20:
                        continue
                    viral_score = round(min(0.5 + len(words) / 30, 0.95), 3)
                    hooks.append(
                        TrendHook(
                            hook_text=hook_text,
                            niche=niche,
                            hook_type=hook_type,
                            viral_score=viral_score,
                        )
                    )
                    if len(hooks) >= count:
                        break
        except Exception as exc:
            logger.warning("TikTokEngine.generate_trend_hooks AI call failed: %s", exc)

        if not hooks:
            templates = [
                ("curiosity", f"Nobody's talking about this {niche} secret and it's wild"),
                (
                    "shock",
                    f"I tried every {niche} hack so you don't have to — here's what happened",
                ),
                ("relatability", f"POV: you're just starting out in {niche} and overwhelmed"),
                ("value", f"3 {niche} tips that changed everything for me"),
                ("controversy", f"Unpopular opinion: most {niche} advice is completely wrong"),
            ]
            for hook_type, text in templates[:count]:
                hooks.append(
                    TrendHook(
                        hook_text=text,
                        niche=niche,
                        hook_type=hook_type,
                        viral_score=round(0.6 + len(hooks) * 0.05, 3),
                    )
                )

        return hooks[:count]

    async def optimize_hook(self, original_hook: str, niche: str) -> str:
        await self._load()

        try:
            ai = get_ai_client()
            resp = await ai.complete(
                system=(
                    "You are a TikTok hook optimization expert. Rewrite the given hook to maximize scroll-stopping potential.\n"
                    "Rules: ≤15 words, creates instant curiosity or shock, speaks directly to the viewer.\n"
                    "Output only the improved hook text, nothing else."
                ),
                user=f"Niche: {niche}\nOriginal hook: {original_hook}",
                model=AIModel.CREATIVE,
                max_tokens=80,
            )
            if resp.success and resp.content:
                improved = resp.content.strip()
                words = improved.split()
                return " ".join(words[:15]) if len(words) > 15 else improved
        except Exception as exc:
            logger.warning("TikTokEngine.optimize_hook AI call failed: %s", exc)

        words = original_hook.split()
        return " ".join(words[:15]) if len(words) > 15 else original_hook

    async def adapt_for_platform(self, script: TikTokScript, target_platform: str) -> TikTokScript:
        await self._load()

        platform_notes = {
            "reels": "Instagram Reels: polished aesthetic, lifestyle tone, 3-5 hashtags max",
            "shorts": "YouTube Shorts: educational tone, value-first, searchable hashtags",
            "tiktok": "TikTok: raw and authentic, trending audio, 5-7 hashtags",
        }
        note = platform_notes.get(
            target_platform, f"{target_platform}: adapt tone and hashtags appropriately"
        )

        new_hook = script.hook
        new_main = script.main_content
        new_cta = script.cta
        new_hashtags = script.hashtags
        new_sound = script.sound_suggestion

        try:
            ai = get_ai_client()
            resp = await ai.complete(
                system=(
                    f"You are a cross-platform short-form video expert. Adapt this script for {target_platform}.\n"
                    f"Platform guidance: {note}\n"
                    "Adjust the tone, hook wording, CTA, and hashtags for the target platform.\n"
                    "Format: HOOK: ... | MAIN: ... | CTA: ... | HASHTAGS: #tag1 #tag2 | SOUND: ..."
                ),
                user=(
                    f"Original platform: {script.platform}\n"
                    f"Target platform: {target_platform}\n"
                    f"HOOK: {script.hook}\n"
                    f"MAIN: {script.main_content}\n"
                    f"CTA: {script.cta}"
                ),
                model=AIModel.FAST,
                max_tokens=500,
            )
            if resp.success and resp.content:
                content = resp.content
                for label, attr in [
                    ("HOOK:", "hook"),
                    ("MAIN:", "main"),
                    ("CTA:", "cta"),
                    ("HASHTAGS:", "hashtags"),
                    ("SOUND:", "sound"),
                ]:
                    idx = content.upper().find(label)
                    if idx != -1:
                        end = len(content)
                        for other in ["HOOK:", "MAIN:", "CTA:", "HASHTAGS:", "SOUND:"]:
                            o_idx = content.upper().find(other, idx + 1)
                            if o_idx != -1 and o_idx < end:
                                end = o_idx
                        val = content[idx + len(label) : end].strip().strip("|").strip()
                        if attr == "hook":
                            new_hook = val
                        elif attr == "main":
                            new_main = val
                        elif attr == "cta":
                            new_cta = val
                        elif attr == "hashtags":
                            new_hashtags = [
                                t.strip()
                                for t in val.replace(",", " ").split()
                                if t.startswith("#")
                            ][:7]
                        elif attr == "sound":
                            new_sound = val
        except Exception as exc:
            logger.warning("TikTokEngine.adapt_for_platform AI call failed: %s", exc)

        hook_words = new_hook.split()
        viral_potential = round(min(0.4 + len(hook_words) / 20, 0.95), 3)
        adapted = TikTokScript(
            topic=script.topic,
            niche=script.niche,
            platform=target_platform,
            hook=new_hook,
            main_content=new_main,
            cta=new_cta,
            hashtags=new_hashtags or script.hashtags,
            sound_suggestion=new_sound,
            estimated_views=int(viral_potential * 50000),
            viral_potential=viral_potential,
            duration_seconds=script.duration_seconds,
        )
        self._scripts.append(adapted.to_dict())
        await self._save()
        return adapted

    def tiktok_analytics(self) -> dict:
        count = len(self._scripts)
        by_platform: dict[str, int] = {}
        by_niche: dict[str, int] = {}
        total_viral = 0.0
        total_views = 0
        for s in self._scripts:
            plat = s.get("platform", "tiktok")
            by_platform[plat] = by_platform.get(plat, 0) + 1
            niche = s.get("niche", "general")
            by_niche[niche] = by_niche.get(niche, 0) + 1
            total_viral += s.get("viral_potential", 0.0)
            total_views += s.get("estimated_views", 0)
        return {
            "total_scripts": count,
            "by_platform": by_platform,
            "avg_viral_potential": round(total_viral / count, 3) if count else 0.0,
            "avg_estimated_views": total_views // count if count else 0,
            "by_niche": by_niche,
        }

    def recent_scripts(self, limit: int = 10) -> list[dict]:
        return self._scripts[-limit:]


_instance: TikTokEngine | None = None


def get_tiktok_engine() -> TikTokEngine:
    global _instance
    if _instance is None:
        _instance = TikTokEngine()
    return _instance
