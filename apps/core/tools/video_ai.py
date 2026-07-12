"""
video_ai.py — ARIA video engine, layer 2: real AI-generated moving footage.

Layer 1 (video_engine.py) produces a *reel* from stills. Layer 2 runs an
open-weights text-to-video model (LTX-Video / Wan2.2) on rented GPU and returns
actual generated footage. It plugs in behind the same shape as layer 1
(generate(prompt) -> {success, video_bytes|video_url, ...}).

Providers, tried in order of configured credentials:
  1. Replicate  (REPLICATE_API_TOKEN) — managed open-weights on rented GPU.
  2. fal.ai     (FAL_KEY)             — same idea, different host.

Honesty: this is not free and not instant — each clip costs GPU time and takes
seconds-to-minutes. With no token configured, available() is False and callers
fall back to the layer-1 reel engine. No token is ever exposed to the browser.
"""

from __future__ import annotations

import asyncio
import base64
import logging

from apps.core.config import settings

logger = logging.getLogger("aria.video_ai")


class AIVideoProvider:
    """Text-to-video via a GPU provider (Replicate / fal.ai)."""

    @staticmethod
    def _replicate_token() -> str | None:
        return getattr(settings, "REPLICATE_API_TOKEN", None)

    @staticmethod
    def _fal_key() -> str | None:
        return getattr(settings, "FAL_KEY", None)

    def available(self) -> bool:
        return bool(self._replicate_token() or self._fal_key())

    async def generate(self, prompt: str) -> dict:
        """Return {success, video_bytes|video_url, provider, ...} or an error."""
        if self._replicate_token():
            r = await self._replicate(prompt, self._replicate_token())
            if r.get("success"):
                return r
            rep_err = r.get("error")
        else:
            rep_err = None

        if self._fal_key():
            r = await self._fal(prompt, self._fal_key())
            if r.get("success"):
                return r
            return r  # surface fal's error

        return {"success": False, "error": rep_err or "Ningún proveedor de video IA configurado"}

    # ── helpers ───────────────────────────────────────────────────
    @staticmethod
    async def _download(client, url: str) -> bytes | None:
        try:
            resp = await client.get(url, timeout=120.0)
            if resp.status_code == 200:
                return resp.content
        except Exception as exc:  # noqa: BLE001
            logger.warning("[video_ai] download failed: %s", exc)
        return None

    def _ok(self, raw: bytes | None, url: str | None, provider: str, prompt: str) -> dict:
        if raw:
            return {
                "success": True,
                "video_bytes": raw,
                "video_base64": base64.b64encode(raw).decode(),
                "content_type": "video/mp4",
                "provider": provider,
                "description": f"Footage IA generado: {prompt}",
            }
        return {
            "success": True,
            "video_url": url,
            "provider": provider,
            "description": f"Footage IA generado: {prompt}",
        }

    # ── Replicate ─────────────────────────────────────────────────
    async def _replicate(self, prompt: str, token: str) -> dict:
        import httpx

        model = getattr(settings, "REPLICATE_VIDEO_MODEL", None) or "lightricks/ltx-video"
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Prefer": "wait",  # block up to ~60s for a synchronous-ish result
        }
        try:
            async with httpx.AsyncClient(timeout=180.0) as c:
                r = await c.post(
                    f"https://api.replicate.com/v1/models/{model}/predictions",
                    headers=headers,
                    json={"input": {"prompt": prompt}},
                )
                if r.status_code not in (200, 201):
                    return {"success": False, "error": f"replicate {r.status_code}: {r.text[:200]}"}
                data = r.json()
                status = data.get("status")
                get_url = (data.get("urls") or {}).get("get")
                # Poll to completion if still running.
                for _ in range(40):
                    if status in ("succeeded", "failed", "canceled") or not get_url:
                        break
                    await asyncio.sleep(3)
                    g = await c.get(get_url, headers=headers)
                    data = g.json()
                    status = data.get("status")
                if status != "succeeded":
                    return {"success": False, "error": f"replicate status: {status}"}
                out = data.get("output")
                vurl = (
                    out[0]
                    if isinstance(out, list) and out
                    else (out if isinstance(out, str) else None)
                )
                if not vurl:
                    return {"success": False, "error": "replicate sin salida de video"}
                raw = await self._download(c, vurl)
                return self._ok(raw, vurl, "replicate", prompt)
        except Exception as exc:  # noqa: BLE001
            logger.error("[video_ai] replicate failed: %s", exc)
            return {"success": False, "error": f"replicate error: {exc}"}

    # ── fal.ai ────────────────────────────────────────────────────
    async def _fal(self, prompt: str, key: str) -> dict:
        import httpx

        model = getattr(settings, "FAL_VIDEO_MODEL", None) or "fal-ai/ltx-video"
        try:
            async with httpx.AsyncClient(timeout=180.0) as c:
                r = await c.post(
                    f"https://fal.run/{model}",
                    headers={"Authorization": f"Key {key}", "Content-Type": "application/json"},
                    json={"prompt": prompt},
                )
                if r.status_code != 200:
                    return {"success": False, "error": f"fal.ai {r.status_code}: {r.text[:200]}"}
                data = r.json()
                vurl = (data.get("video") or {}).get("url") or data.get("url")
                if not vurl:
                    return {"success": False, "error": "fal.ai sin URL de video"}
                raw = await self._download(c, vurl)
                return self._ok(raw, vurl, "fal", prompt)
        except Exception as exc:  # noqa: BLE001
            logger.error("[video_ai] fal failed: %s", exc)
            return {"success": False, "error": f"fal.ai error: {exc}"}


_provider: AIVideoProvider | None = None


def get_ai_video() -> AIVideoProvider:
    global _provider
    if _provider is None:
        _provider = AIVideoProvider()
    return _provider
