"""
voice_profile.py — Identity Fine-Tuning endpoints.

POST /api/v1/user/voice-profile — upload a compressed audio sample (+ optional
    style guidelines); routes the audio to ElevenLabs (or a stub) and stores the
    resulting voice_id + style guidelines against the user.
GET  /api/v1/user/voice-profile — fetch the signed-in user's voice profile.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, File, Form, UploadFile
from fastapi.responses import JSONResponse

from apps.core.security.deps import rate_limit, require_user
from apps.core.services.identity_profile_service import (
    clone_voice_elevenlabs,
    get_voice_profile,
    save_voice_profile,
    update_style_guidelines,
)

logger = logging.getLogger("aria.voice_profile")

router = APIRouter(prefix="/api/v1/user", tags=["identity"])

_MAX_AUDIO_BYTES = 15 * 1024 * 1024  # 15 MB
_ALLOWED = {
    "audio/mpeg",
    "audio/mp3",
    "audio/mp4",
    "audio/m4a",
    "audio/wav",
    "audio/webm",
    "audio/ogg",
}


@router.post("/voice-profile", dependencies=[Depends(rate_limit("voice", 10, 60))])
async def create_voice_profile(
    audio: UploadFile = File(...),
    style_guidelines: str = Form(""),
    user: dict = Depends(require_user),
):
    """Clone the user's voice from an audio sample and save their style profile."""
    email = (user.get("email") or "").strip().lower()

    if audio.content_type and audio.content_type not in _ALLOWED:
        return JSONResponse(
            {"ok": False, "error": f"unsupported audio type: {audio.content_type}"}, status_code=415
        )
    data = await audio.read()
    if not data:
        return JSONResponse({"ok": False, "error": "empty audio file"}, status_code=400)
    if len(data) > _MAX_AUDIO_BYTES:
        return JSONResponse({"ok": False, "error": "audio too large (max 15 MB)"}, status_code=413)

    voice_id, is_real = await clone_voice_elevenlabs(
        data, audio.filename or "sample.mp3", name=f"ARIA voice · {email}"
    )
    profile = await save_voice_profile(
        email,
        voice_id=voice_id,
        style_guidelines=style_guidelines.strip()[:20000],
        sample_filename=audio.filename or "",
    )
    return {
        "ok": True,
        "voice_id": voice_id,
        "cloned": is_real,  # False → stub (set ELEVENLABS_API_KEY for a real clone)
        "profile": profile.to_dict(),
    }


@router.patch("/voice-profile", dependencies=[Depends(rate_limit("voice", 20, 60))])
async def patch_style(style_guidelines: str = Form(...), user: dict = Depends(require_user)):
    """Update only the brand style guidelines (no new audio)."""
    email = (user.get("email") or "").strip().lower()
    profile = await update_style_guidelines(email, style_guidelines.strip()[:20000])
    return {"ok": True, "profile": profile.to_dict()}


@router.get("/voice-profile")
async def read_voice_profile(user: dict = Depends(require_user)):
    email = (user.get("email") or "").strip().lower()
    profile = await get_voice_profile(email)
    return {"ok": True, "profile": profile}
