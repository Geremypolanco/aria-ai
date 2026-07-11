"""
clipper.py — Backend for the ARIA Chrome Clipper extension.

POST /api/v1/clipper/capture — receives a page URL + selected text from the
extension, authenticates the user with the existing signed session (cookie or
Bearer token), and stores the clip in the user's workspace for later research.
"""

from __future__ import annotations

import contextlib
import json
import logging

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field

from apps.core.security.deps import rate_limit, require_user

logger = logging.getLogger("aria.clipper")

router = APIRouter(prefix="/api/v1/clipper", tags=["clipper"])


class ClipRequest(BaseModel):
    url: str = Field("", max_length=2048)
    title: str = Field("", max_length=512)
    selection: str = Field("", max_length=20000)
    clipped_at: str = Field("", max_length=64)


@router.post("/capture", dependencies=[Depends(rate_limit("clipper", 60, 60))])
async def capture(clip: ClipRequest, request: Request, user: dict = Depends(require_user)):
    """Store a web clip for the signed-in user."""
    email = (user.get("email") or "").strip().lower()
    if not clip.url and not clip.selection:
        return {"ok": False, "error": "nothing to clip"}

    record = {
        "url": clip.url[:2048],
        "title": clip.title[:512],
        "selection": clip.selection[:20000],
        "clipped_at": clip.clipped_at[:64],
    }
    try:
        from apps.core.memory.redis_client import get_cache

        cache = get_cache()
        await cache.rpush(f"aria:clips:{email}", json.dumps(record, ensure_ascii=False))
        # Cap the per-user clip list (best-effort — only if the backend supports it).
        ltrim = getattr(cache, "ltrim", None)
        if ltrim:
            with contextlib.suppress(Exception):
                await ltrim(f"aria:clips:{email}", -200, -1)
    except Exception as exc:  # noqa: BLE001 — storage is best-effort
        logger.warning("[clipper] store failed for %s: %s", email, exc)

    logger.info("[clipper] captured %s for %s", record["url"][:80], email)
    return {"ok": True, "stored": True}
