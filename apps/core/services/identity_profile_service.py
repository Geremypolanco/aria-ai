"""
identity_profile_service.py — Voice cloning + brand-voice style fine-tuning.

Stores, per user, a cloned `voice_id` (from ElevenLabs) plus free-text
`style_guidelines` (the brand's writing rules / idioms) so ARIA can generate
content in the user's own voice and style.

Persistence: the shared cache (keyed `aria:voice_profile:{email}`), with a
best-effort mirror to Supabase if configured. A matching SQL schema for the
`voice_identity` table lives in `database/voice_identity.sql`.

The ElevenLabs call is real when `ELEVENLABS_API_KEY` is set, and a clearly
labeled stub otherwise (no broken placeholder, no fabricated success).
"""

from __future__ import annotations

import json
import logging
import secrets
from datetime import UTC, datetime

from pydantic import BaseModel, Field

from apps.core.config import settings

logger = logging.getLogger("aria.identity")

_KEY = "aria:voice_profile:{email}"
ELEVENLABS_ADD_VOICE_URL = "https://api.elevenlabs.io/v1/voices/add"


class VoiceIdentity(BaseModel):
    """Voice + style profile coupled to a user (by email)."""

    user_email: str
    voice_id: str = ""
    provider: str = "elevenlabs"
    sample_filename: str = ""
    style_guidelines: str = Field("", max_length=20000)
    created_at: str = ""
    updated_at: str = ""

    def to_dict(self) -> dict:
        return self.model_dump()


def _now() -> str:
    return datetime.now(UTC).isoformat()


# ── ElevenLabs voice cloning ──────────────────────────────────────
async def clone_voice_elevenlabs(audio: bytes, filename: str, name: str) -> tuple[str, bool]:
    """Create a cloned voice from an audio sample.

    Returns (voice_id, is_real). When no API key is configured, returns a stub
    voice id so the flow completes end-to-end without fabricating a real clone.
    """
    api_key = getattr(settings, "ELEVENLABS_API_KEY", None)
    if not api_key:
        stub_id = "stub-voice-" + secrets.token_hex(6)
        logger.info("[identity] ELEVENLABS_API_KEY unset — issued stub voice_id %s", stub_id)
        return stub_id, False
    try:
        import httpx

        async with httpx.AsyncClient(timeout=60.0) as c:
            r = await c.post(
                ELEVENLABS_ADD_VOICE_URL,
                headers={"xi-api-key": api_key},
                data={"name": name},
                files={"files": (filename or "sample.mp3", audio, "audio/mpeg")},
            )
            r.raise_for_status()
            voice_id = r.json().get("voice_id", "")
            logger.info("[identity] cloned voice %s for %s", voice_id, name)
            return voice_id, True
    except Exception as exc:  # noqa: BLE001
        logger.warning("[identity] ElevenLabs clone failed: %s", exc)
        return "stub-voice-" + secrets.token_hex(6), False


# ── persistence ───────────────────────────────────────────────────
async def save_voice_profile(
    email: str,
    *,
    voice_id: str,
    style_guidelines: str,
    sample_filename: str = "",
    provider: str = "elevenlabs",
) -> VoiceIdentity:
    email = (email or "").strip().lower()
    existing = await get_voice_profile(email)
    created = (existing or {}).get("created_at") or _now()
    profile = VoiceIdentity(
        user_email=email,
        voice_id=voice_id,
        provider=provider,
        sample_filename=sample_filename,
        style_guidelines=style_guidelines or (existing or {}).get("style_guidelines", ""),
        created_at=created,
        updated_at=_now(),
    )
    payload = json.dumps(profile.to_dict(), ensure_ascii=False)
    try:
        from apps.core.memory.redis_client import get_cache

        await get_cache().set(_KEY.format(email=email), payload, ttl_seconds=60 * 60 * 24 * 365)
    except Exception as exc:  # noqa: BLE001
        logger.warning("[identity] cache save failed: %s", exc)
    # Best-effort Supabase mirror (table: voice_identity).
    try:
        from apps.core.memory.supabase_client import get_supabase  # type: ignore

        sb = get_supabase()
        if sb is not None:
            sb.table("voice_identity").upsert(profile.to_dict()).execute()
    except Exception:
        pass
    return profile


async def get_voice_profile(email: str) -> dict | None:
    email = (email or "").strip().lower()
    try:
        from apps.core.memory.redis_client import get_cache

        raw = await get_cache().get(_KEY.format(email=email))
        if raw:
            return json.loads(raw) if isinstance(raw, str) else raw
    except Exception as exc:  # noqa: BLE001
        logger.debug("[identity] get failed: %s", exc)
    return None


async def update_style_guidelines(email: str, style_guidelines: str) -> VoiceIdentity:
    existing = await get_voice_profile(email) or {}
    return await save_voice_profile(
        email,
        voice_id=existing.get("voice_id", ""),
        style_guidelines=style_guidelines,
        sample_filename=existing.get("sample_filename", ""),
        provider=existing.get("provider", "elevenlabs"),
    )
