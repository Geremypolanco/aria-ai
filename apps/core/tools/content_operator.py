"""
content_operator.py — ARIA's autonomous content-marketing operator (the wedge).

One coherent, verifiable loop that reuses ARIA's REAL, hosted content stack and
publishes through the owner's already-connected Zapier accounts:

    brand context → generate copy (ai_client) → generate image (FLUX → Cloudinary)
    → publish via Zapier MCP → record full observability trail (Redis)

Every run produces an auditable record answering: what did it make, why, which
tools did it call, and what happened. That trail is what makes the capability
trustworthy (and, later, sellable).

Design choices:
- No local Chromium / ffmpeg — everything is a hosted API call, so it runs inside
  ARIA's Fly container.
- Publishing is schema-driven: we read each Zapier tool's ``inputSchema`` at runtime
  and map the asset (image url / caption) onto whatever parameter names it exposes,
  instead of hardcoding Zapier's naming.
- Degrades gracefully: a missing credential yields a recorded failure, never a crash.
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import UTC, datetime
from typing import Any

import httpx

from apps.core.config import settings
from apps.core.tools.ai_client import AIModel, get_ai_client_async
from apps.core.tools.content_tools import get_content_tools
from apps.core.tools.zapier_mcp import get_zapier_mcp

logger = logging.getLogger("aria.tools.content_operator")

_RUNS_KEY = "aria:content_operator:runs"

# The operating methodology transferred from how the assistant works. This is injected
# into every generation so ARIA makes the same kind of decisions: research first, never
# fabricate, hook hard, stay honest, write native to the platform.
PLAYBOOK = (
    "You operate like an elite, honest creative director. Non-negotiable principles:\n"
    "1) RESEARCH FIRST: never invent facts, numbers, names, or events. Ground every claim "
    "in the RESEARCH provided. If the research is thin, stay general and truthful — never "
    "fabricate to sound impressive. Credibility is the asset.\n"
    "2) REFERENCE FIRST: mirror the structure of what already works for this format/platform "
    "(hook, pacing) without copying anyone.\n"
    "3) HOOK: the first line must stop the scroll and make sense on its own.\n"
    "4) HONESTY: no clickbait the content doesn't deliver; no misleading claims.\n"
    "5) PLATFORM FIT: write natively for the target platform's format and tone.\n"
    "6) VALUE OR EMOTION: give the reader something useful or something that moves them; "
    "never generic filler.\n"
    "7) CLEAR CTA at the end when it fits."
)

# The Zapier MCP server does NOT expose one tool per channel; it exposes meta-tools
# (execute_zapier_write_action, list_enabled_zapier_actions, ...). To publish we call
# `execute_zapier_write_action` with the app's `selected_api` + `action` + `params`.
# These identifiers are the stable Zapier action keys for each already-connected app.
CHANNELS: dict[str, dict[str, str]] = {
    "instagram": {"selected_api": "InstagramBusinessCLIAPI", "action": "publish_media_v2"},
    "pinterest": {"selected_api": "PinterestCLIAPI", "action": "create_pin"},
    "linkedin": {"selected_api": "LinkedInCLIAPI", "action": "share"},
    "facebook": {"selected_api": "FacebookV2CLIAPI", "action": "create_page_photo"},
}


class ContentOperator:
    def __init__(self) -> None:
        self.content = get_content_tools()
        self.mcp = get_zapier_mcp()

    # ── 0. research (never create blind) ──────────────────────────────────

    async def research(self, topic: str, n: int = 6) -> list[dict[str, str]]:
        """Ground content in current, real info (research-first) via SerpAPI.
        Returns a list of {title, snippet, link}. Empty on any failure."""
        key = getattr(settings, "SERP_API_KEY", None)
        if not key or not topic.strip():
            return []
        try:
            async with httpx.AsyncClient(timeout=25.0) as c:
                r = await c.get(
                    "https://serpapi.com/search.json",
                    params={"q": topic, "api_key": key, "engine": "google", "num": n},
                )
            if r.status_code != 200:
                return []
            items = r.json().get("organic_results", []) or []
            out = []
            for it in items[:n]:
                if it.get("snippet"):
                    out.append(
                        {
                            "title": str(it.get("title", ""))[:160],
                            "snippet": str(it.get("snippet", ""))[:300],
                            "link": str(it.get("link", "")),
                        }
                    )
            return out
        except Exception as exc:  # noqa: BLE001 - research is best-effort
            logger.debug("[ContentOperator] research failed: %s", exc)
            return []

    # ── 1. creative generation (research-first, methodology-driven) ────────

    async def generate_creative(
        self, brand: dict[str, Any], research_first: bool = True
    ) -> dict[str, Any]:
        """Research the topic, then ask the AI for a publish-ready caption + image prompt,
        under the PLAYBOOK methodology so ARIA decides like the assistant would."""
        ai = await get_ai_client_async()
        product = brand.get("product", brand.get("name", "the product"))
        audience = brand.get("audience", "founders and small business owners")

        findings = await self.research(f"{product} {audience}") if research_first else []
        research_block = ""
        if findings:
            lines = "\n".join(f"- {f['title']}: {f['snippet']}" for f in findings)
            research_block = (
                "\n\nCURRENT RESEARCH — ground your claims in this, do not contradict it, "
                f"do not invent beyond it:\n{lines}\n"
            )

        system = PLAYBOOK + "\n\nYou are a senior direct-response social media strategist."
        user = (
            f"Brand: {brand.get('name', 'SARAPH')}\n"
            f"Product: {product}\n"
            f"Price: {brand.get('price', '')}\n"
            f"Audience: {audience}\n"
            f"Offer link: {brand.get('url', '')}\n"
            f"{research_block}\n"
            "Write ONE Instagram-ready post promoting this. Return JSON with keys:\n"
            '  "hook": a 4-8 word scroll-stopping first line,\n'
            '  "caption": the full caption (120-220 words, line breaks ok, ends with a clear CTA to the link),\n'
            '  "hashtags": array of 8-12 relevant lowercase hashtags without the # sign,\n'
            '  "image_prompt": a detailed prompt for an image generator to create a premium, '
            "on-brand vertical graphic (dark, modern, high-end; describe layout and any short on-image text),\n"
            '  "reasoning": one sentence on why this angle should convert.\n'
        )
        data = await ai.complete_json(
            system=system, user=user, model=AIModel.CREATIVE, max_tokens=1200, temperature=0.85
        )
        if not data or not data.get("caption"):
            return {"success": False, "error": "AI returned no usable creative", "raw": data}

        tags = data.get("hashtags") or []
        if isinstance(tags, str):
            tags = [t.strip().lstrip("#") for t in tags.replace(",", " ").split()]
        hashtag_line = " ".join(f"#{t.lstrip('#')}" for t in tags if t)
        caption = data["caption"].strip()
        if hashtag_line and hashtag_line not in caption:
            caption = f"{caption}\n\n{hashtag_line}"

        return {
            "success": True,
            "hook": data.get("hook", ""),
            "caption": caption,
            "image_prompt": data.get("image_prompt", f"Premium marketing graphic for {product}"),
            "reasoning": data.get("reasoning", ""),
            "research_used": len(findings),
            "sources": [f["link"] for f in findings if f.get("link")][:6],
        }

    # ── 2. asset production ───────────────────────────────────────────────

    async def produce_image(self, image_prompt: str, brand_name: str) -> dict[str, Any]:
        slug = "".join(c for c in brand_name.lower() if c.isalnum())[:20] or "brand"
        public_id = f"aria/{slug}-{uuid.uuid4().hex[:8]}"
        # Primary: FLUX → Cloudinary (branded storage).
        result = await self.content.generate_and_upload_image(image_prompt, public_id=public_id)
        if result.get("success") and result.get("image_url"):
            return result
        # Fallback: Pollinations returns a ready-to-use public image URL with no auth
        # and no dependency on HF's (deprecated) inference host.
        import urllib.parse

        prompt_enc = urllib.parse.quote(image_prompt[:400])
        url = (
            f"https://image.pollinations.ai/prompt/{prompt_enc}"
            "?width=1080&height=1350&nologo=true&model=flux"
        )
        return {
            "success": True,
            "image_url": url,
            "source": "pollinations",
            "fallback_reason": result.get("error"),
        }

    # ── 3. publishing (via Zapier meta-tools) ─────────────────────────────

    @staticmethod
    def _channel_params(
        channel: str, image_url: str, caption: str, extra: dict[str, Any]
    ) -> dict[str, Any]:
        """Build the `params` payload for a channel's Zapier write action."""
        if channel == "instagram":
            return {"media": [image_url], "caption": caption}
        if channel == "facebook":
            return {"photo_url": image_url, "message": caption}
        if channel == "linkedin":
            # LinkedIn's share action is text-first; an image only attaches via a
            # penalised link-card, so we post the caption as a native text update.
            return {"comment": caption, "visibility__code": "anyone"}
        if channel == "pinterest":
            params: dict[str, Any] = {
                "image_url": image_url,
                "description": caption,
                "title": (extra.get("title") or caption.split("\n", 1)[0])[:100],
            }
            if extra.get("board_id"):
                params["board_id"] = extra["board_id"]
            if extra.get("source_url"):
                params["source_url"] = extra["source_url"]
            return params
        return {"image_url": image_url, "caption": caption}

    async def publish(
        self, channels: list[str], image_url: str, caption: str, extra: dict[str, Any] | None = None
    ) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        extra = extra or {}
        if not self.mcp.configured:
            return [
                {"channel": ch, "success": False, "error": "ZAPIER_MCP_URL not configured"}
                for ch in channels
            ]

        for ch in channels:
            spec = CHANNELS.get(ch)
            if not spec:
                results.append({"channel": ch, "success": False, "error": "unknown channel"})
                continue
            params = self._channel_params(ch, image_url, caption, extra)
            out = await self.mcp.call_tool(
                "execute_zapier_write_action",
                {
                    "selected_api": spec["selected_api"],
                    "action": spec["action"],
                    "instructions": f"Publish this {ch} post promoting the brand.",
                    "params": params,
                    "output": "The URL/permalink and ID of the published post, or any error.",
                },
            )
            results.append(
                {
                    "channel": ch,
                    "action": spec["action"],
                    "params_keys": list(params.keys()),
                    "success": out.get("success", False),
                    "error": out.get("error"),
                    "response": (out.get("text") or "")[:800],
                }
            )
        return results

    # ── 4. orchestration + observability ──────────────────────────────────

    async def run_once(
        self,
        brand: dict[str, Any],
        channels: list[str] | None = None,
        dry_run: bool = False,
    ) -> dict[str, Any]:
        channels = channels or ["instagram"]
        record: dict[str, Any] = {
            "id": uuid.uuid4().hex,
            "ts": datetime.now(UTC).isoformat(),
            "brand": brand.get("name", "unknown"),
            "channels": channels,
            "dry_run": dry_run,
            "steps": [],
            "assets": {},
            "results": [],
            "success": False,
        }

        def step(name: str, ok: bool, **info: Any) -> None:
            record["steps"].append({"step": name, "ok": ok, **info})

        # 1. creative
        creative = await self.generate_creative(brand)
        step("generate_copy", creative.get("success", False), error=creative.get("error"))
        if not creative.get("success"):
            record["error"] = creative.get("error")
            await self._save(record)
            return record
        record["assets"]["caption"] = creative["caption"]
        record["assets"]["hook"] = creative["hook"]
        record["reasoning"] = creative.get("reasoning", "")
        record["research_used"] = creative.get("research_used", 0)
        record["sources"] = creative.get("sources", [])
        step("research", True, sources=creative.get("research_used", 0))

        # 2. image
        img = await self.produce_image(creative["image_prompt"], brand.get("name", "brand"))
        step(
            "generate_image",
            img.get("success", False),
            error=img.get("error"),
            image_url=img.get("image_url"),
        )
        if not img.get("success") or not img.get("image_url"):
            record["error"] = img.get("error", "image generation failed")
            await self._save(record)
            return record
        record["assets"]["image_url"] = img["image_url"]

        # 3. publish (or stop before it on a dry run)
        if dry_run:
            step("publish", True, note="dry_run — skipped actual publish")
            record["success"] = True
            await self._save(record)
            return record

        results = await self.publish(
            channels, img["image_url"], creative["caption"], extra=brand.get("publish_extra")
        )
        record["results"] = results
        for r in results:
            step(
                f"publish:{r['channel']}",
                r.get("success", False),
                tool=r.get("tool"),
                error=r.get("error"),
            )
        record["success"] = any(r.get("success") for r in results)

        await self._save(record)
        return record

    async def _save(self, record: dict[str, Any]) -> None:
        """Append the run to the observability log (best-effort, capped at 200)."""
        try:
            from apps.core.memory.redis_client import get_cache

            cache = get_cache()
            await cache.rpush(_RUNS_KEY, json.dumps(record, ensure_ascii=False))
            await cache.ltrim(_RUNS_KEY, -200, -1)
        except Exception as exc:  # noqa: BLE001 - logging must never break the run
            logger.debug("[ContentOperator] could not persist run: %s", exc)

    async def recent_runs(self, limit: int = 20) -> list[dict[str, Any]]:
        try:
            from apps.core.memory.redis_client import get_cache

            raw = await get_cache().lrange(_RUNS_KEY, -limit, -1)
            out = []
            for item in raw:
                try:
                    out.append(json.loads(item))
                except (json.JSONDecodeError, TypeError):
                    continue
            return list(reversed(out))
        except Exception as exc:  # noqa: BLE001
            logger.debug("[ContentOperator] could not read runs: %s", exc)
            return []


_operator: ContentOperator | None = None


def get_content_operator() -> ContentOperator:
    global _operator
    if _operator is None:
        _operator = ContentOperator()
    return _operator
