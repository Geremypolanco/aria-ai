"""Media generation endpoints: TTS audio and vocab-illustration images."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel

from .. import auth
from ..hf_client import hf_client

# Gated behind "signed in" (any account, not a specific user_id) — these calls
# hit paid HF inference, so they shouldn't be reachable by anonymous traffic
# on a public deployment.
router = APIRouter(prefix="/api/content", tags=["content"], dependencies=[Depends(auth.require_session)])


class TTSRequest(BaseModel):
    text: str
    target_lang: str


@router.post("/tts")
async def text_to_speech(payload: TTSRequest) -> Response:
    audio = await hf_client.text_to_speech(payload.text, payload.target_lang)
    if audio is None:
        raise HTTPException(status_code=503, detail="Audio unavailable — set HF_TOKEN to enable text-to-speech")
    return Response(content=audio, media_type="audio/flac")


class ImageRequest(BaseModel):
    prompt: str


@router.post("/image")
async def generate_image(payload: ImageRequest) -> Response:
    image = await hf_client.generate_image(payload.prompt)
    if image is None:
        raise HTTPException(status_code=503, detail="Image unavailable — set HF_TOKEN to enable image generation")
    return Response(content=image, media_type="image/jpeg")


@router.post("/stt")
async def speech_to_text(request: Request) -> dict:
    """Used by the speak_repeat pronunciation exercise: the client posts the raw
    recorded audio bytes and gets back a transcript to self-check against."""
    audio_bytes = await request.body()
    content_type = request.headers.get("content-type", "audio/webm")
    text = await hf_client.speech_to_text(audio_bytes, content_type)
    return {"text": text}
