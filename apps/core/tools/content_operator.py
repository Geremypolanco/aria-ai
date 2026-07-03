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

from apps.core.tools.ai_client import AIModel, get_ai_client_async
from apps.core.tools.content_tools import get_content_tools
from apps.core.tools.zapier_mcp import get_zapier_mcp

logger = logging.getLogger("aria.tools.content_operator")

_RUNS_KEY = "aria:content_operator:runs"

# Per-channel discovery hints. `find` = keywords that must all appear in the Zapier
# tool name; `needs` = extra args the channel requires that we can't infer.
CHANNELS: dict[str, dict[str, Any]] = {
    "instagram": {"find": ["instagram", "photo"], "needs": []},
    "facebook": {"find": ["facebook", "photo"], "needs": []},
    "linkedin": {"find": ["linkedin", "create"], "needs": []},
    "twitter": {"find": ["twitter", "tweet"], "needs": []},
}

# Parameter-name intents used to map our asset onto an unknown tool schema.
_IMAGE_HINTS = ("media", "image", "photo", "picture", "url", "file")
_TEXT_HINTS = ("caption", "text", "message", "content", "comment", "description")


class ContentOperator:
    def __init__(self) -> None:
        self.content = get_content_tools()
        self.mcp = get_zapier_mcp()

    # ── 1. creative generation ────────────────────────────────────────────

    async def generate_creative(self, brand: dict[str, Any]) -> dict[str, Any]:
        """Ask the AI for a publish-ready caption + image prompt for this brand."""
        ai = await get_ai_client_async()
        system = (
            "You are a senior direct-response social media strategist. You write "
            "thumb-stopping, high-converting organic posts. You never sound like a "
            "generic AI. Hooks are specific and a little contrarian."
        )
        product = brand.get("product", brand.get("name", "the product"))
        user = (
            f"Brand: {brand.get('name', 'SARAPH')}\n"
            f"Product: {product}\n"
            f"Price: {brand.get('price', '')}\n"
            f"Audience: {brand.get('audience', 'founders and small business owners')}\n"
            f"Offer link: {brand.get('url', '')}\n\n"
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
        }

    # ── 2. asset production ───────────────────────────────────────────────

    async def produce_image(self, image_prompt: str, brand_name: str) -> dict[str, Any]:
        slug = "".join(c for c in brand_name.lower() if c.isalnum())[:20] or "brand"
        public_id = f"aria/{slug}-{uuid.uuid4().hex[:8]}"
        return await self.content.generate_and_upload_image(image_prompt, public_id=public_id)

    # ── 3. publishing (schema-driven) ─────────────────────────────────────

    @staticmethod
    def _build_args(
        schema: dict[str, Any], image_url: str, caption: str, extra: dict[str, Any]
    ) -> dict[str, Any]:
        """Map (image_url, caption) onto a tool's inputSchema property names."""
        props: dict[str, Any] = (schema or {}).get("properties", {}) or {}
        args: dict[str, Any] = {}

        def _match(hints: tuple[str, ...]) -> str | None:
            # Prefer required properties, then any, that contain a hint keyword.
            required = set((schema or {}).get("required", []) or [])
            ordered = sorted(props.keys(), key=lambda k: (k not in required, k))
            for key in ordered:
                low = key.lower()
                if any(h in low for h in hints):
                    return key
            return None

        img_key = _match(_IMAGE_HINTS)
        if img_key:
            prop = props.get(img_key, {})
            is_array = prop.get("type") == "array" or "list" in str(prop.get("type", ""))
            args[img_key] = [image_url] if is_array else image_url

        txt_key = _match(_TEXT_HINTS)
        if txt_key and txt_key != img_key:
            args[txt_key] = caption

        # Caller-supplied required extras (e.g. a pinterest board_id) win.
        args.update({k: v for k, v in (extra or {}).items() if v is not None})
        return args

    async def publish(
        self, channels: list[str], image_url: str, caption: str, extra: dict[str, Any] | None = None
    ) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        if not self.mcp.configured:
            for ch in channels:
                results.append(
                    {"channel": ch, "success": False, "error": "ZAPIER_MCP_URL not configured"}
                )
            return results

        try:
            tools = await self.mcp.list_tools()
        except Exception as exc:  # noqa: BLE001
            for ch in channels:
                results.append(
                    {"channel": ch, "success": False, "error": f"MCP unreachable: {exc}"}
                )
            return results

        by_name = {str(t.get("name", "")).lower(): t for t in tools}

        for ch in channels:
            spec = CHANNELS.get(ch)
            if not spec:
                results.append({"channel": ch, "success": False, "error": "unknown channel"})
                continue
            kws = [k.lower() for k in spec["find"]]
            match = next((t for n, t in by_name.items() if all(k in n for k in kws)), None)
            if not match:
                results.append(
                    {"channel": ch, "success": False, "error": f"no Zapier tool matching {kws}"}
                )
                continue
            args = self._build_args(match.get("inputSchema", {}), image_url, caption, extra or {})
            out = await self.mcp.call_tool(match["name"], args)
            results.append(
                {
                    "channel": ch,
                    "tool": match["name"],
                    "args_keys": list(args.keys()),
                    "success": out.get("success", False),
                    "error": out.get("error"),
                    "response": (out.get("text") or "")[:600],
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
