"""Thin wrapper around Hugging Face's Inference API for the four modalities
this app needs: chat/text generation (tutor + exercise authoring), text-to-image
(vocabulary flashcards), text-to-speech, and speech-to-text (conversation mode).

Falls back to a small local template generator when HF_TOKEN isn't configured,
so the app is fully runnable/demoable offline — but every call here is a real
HF request when a token is present (no mocked "success" responses).
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re

import httpx

from .config import settings
from .curriculum import LessonRequest, build_exercise_generation_prompt
from .models import Exercise, ExerciseType

logger = logging.getLogger("lingua.hf_client")

# ISO 639-1 -> MMS-TTS ISO 639-3 code, for the languages most likely to be
# picked in a demo. Falls back to English if a target language isn't mapped.
_MMS_LANG_CODES = {
    "en": "eng",
    "es": "spa",
    "fr": "fra",
    "de": "deu",
    "it": "ita",
    "pt": "por",
    "ja": "jpn",
    "ko": "kor",
    "zh": "cmn",
    "ru": "rus",
    "ar": "ara",
    "nl": "nld",
    "sv": "swe",
    "pl": "pol",
    "tr": "tur",
    "hi": "hin",
}


class HFClientError(RuntimeError):
    pass


class HFClient:
    def __init__(self) -> None:
        self._http = httpx.AsyncClient(timeout=settings.request_timeout_s)
        os.makedirs(settings.cache_dir, exist_ok=True)

    async def aclose(self) -> None:
        await self._http.aclose()

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {settings.hf_token}"}

    def _cache_path(self, namespace: str, key: str, ext: str) -> str:
        digest = hashlib.sha256(key.encode()).hexdigest()[:32]
        return os.path.join(settings.cache_dir, f"{namespace}-{digest}.{ext}")

    # ── Chat / text generation ──────────────────────────────────────────

    async def chat(self, messages: list[dict[str, str]], max_tokens: int = 700, temperature: float = 0.7) -> str:
        if not settings.hf_configured:
            raise HFClientError("HF_TOKEN not configured")
        resp = await self._http.post(
            settings.hf_chat_endpoint,
            headers=self._headers(),
            json={
                "model": settings.chat_model,
                "messages": messages,
                "max_tokens": max_tokens,
                "temperature": temperature,
            },
        )
        if resp.status_code != 200:
            raise HFClientError(f"HF chat HTTP {resp.status_code}: {resp.text[:300]}")
        data = resp.json()
        return data["choices"][0]["message"]["content"]

    async def generate_exercises(self, req: LessonRequest) -> list[Exercise]:
        prompt = build_exercise_generation_prompt(req)
        if settings.hf_configured:
            try:
                raw = await self.chat(
                    [
                        {"role": "system", "content": "You output only valid JSON, nothing else."},
                        {"role": "user", "content": prompt},
                    ],
                    max_tokens=1500,
                )
                return _parse_exercises(raw)
            except Exception:
                logger.exception("HF exercise generation failed, using offline fallback content")
        return _fallback_exercises(req)

    async def conversation_reply(self, system_prompt: str, history: list[dict[str, str]]) -> str:
        if not settings.hf_configured:
            return (
                "(demo mode — set HF_TOKEN to enable the real AI tutor) "
                "That's great, tell me more!"
            )
        messages = [{"role": "system", "content": system_prompt}, *history]
        return await self.chat(messages, max_tokens=300, temperature=0.8)

    # ── Text-to-image (vocab flashcards) ────────────────────────────────

    async def generate_image(self, prompt: str) -> bytes | None:
        cache_path = self._cache_path("img", prompt, "jpg")
        if os.path.exists(cache_path):
            with open(cache_path, "rb") as f:
                return f.read()
        if not settings.hf_configured:
            return None
        try:
            resp = await self._http.post(
                f"{settings.hf_models_endpoint}/{settings.image_model}",
                headers=self._headers(),
                json={"inputs": prompt},
            )
            if resp.status_code == 200 and resp.headers.get("content-type", "").startswith("image"):
                with open(cache_path, "wb") as f:
                    f.write(resp.content)
                return resp.content
            logger.warning("HF image generation HTTP %s: %s", resp.status_code, resp.text[:200])
        except Exception:
            logger.exception("HF image generation failed")
        return None

    # ── Text-to-speech ──────────────────────────────────────────────────

    async def text_to_speech(self, text: str, target_lang: str) -> bytes | None:
        lang_code = _MMS_LANG_CODES.get(target_lang.lower()[:2], "eng")
        model = f"{settings.tts_model_prefix}-{lang_code}"
        cache_path = self._cache_path("tts", f"{model}:{text}", "flac")
        if os.path.exists(cache_path):
            with open(cache_path, "rb") as f:
                return f.read()
        if not settings.hf_configured:
            return None
        try:
            resp = await self._http.post(
                f"{settings.hf_models_endpoint}/{model}",
                headers=self._headers(),
                json={"inputs": text},
            )
            if resp.status_code == 200 and resp.headers.get("content-type", "").startswith("audio"):
                with open(cache_path, "wb") as f:
                    f.write(resp.content)
                return resp.content
            logger.warning("HF TTS HTTP %s (%s): %s", resp.status_code, model, resp.text[:200])
        except Exception:
            logger.exception("HF TTS failed")
        return None

    # ── Speech-to-text ───────────────────────────────────────────────────

    async def speech_to_text(self, audio_bytes: bytes, content_type: str = "audio/webm") -> str:
        if not settings.hf_configured:
            return ""
        try:
            resp = await self._http.post(
                f"{settings.hf_models_endpoint}/{settings.stt_model}",
                headers={**self._headers(), "Content-Type": content_type},
                content=audio_bytes,
            )
            if resp.status_code == 200:
                data = resp.json()
                return data.get("text", "").strip()
            logger.warning("HF STT HTTP %s: %s", resp.status_code, resp.text[:200])
        except Exception:
            logger.exception("HF STT failed")
        return ""


def _parse_exercises(raw: str) -> list[Exercise]:
    cleaned = re.sub(r"^```(json)?|```$", "", raw.strip(), flags=re.MULTILINE).strip()
    items = json.loads(cleaned)
    exercises = []
    for i, item in enumerate(items):
        exercises.append(
            Exercise(
                id=f"ex-{i}-{item.get('vocab_key', i)}",
                type=ExerciseType(item["type"]),
                prompt=item.get("prompt", ""),
                target_text=item.get("target_text", ""),
                native_text=item.get("native_text", ""),
                options=item.get("options", []) or [],
                correct_answer=item.get("correct_answer", item.get("target_text", "")),
                image_prompt=item.get("image_prompt", ""),
                audio_text=item.get("audio_text", item.get("target_text", "")),
                vocab_key=item.get("vocab_key", f"item-{i}"),
            )
        )
    return exercises


def _fallback_exercises(req: LessonRequest) -> list[Exercise]:
    """Deterministic, network-free content so the app works with no HF_TOKEN
    (useful for local dev/demo/tests). Clearly lower quality than the real
    LLM-generated, personalized content."""
    from .curriculum import exercise_mix_for

    mix = exercise_mix_for(req.unit.level)
    exercises = []
    for i, ex_type in enumerate(mix):
        word = f"{req.unit.topic.split()[0].lower()}_{i}"
        target = f"[{req.target_lang}] {req.unit.topic} example {i + 1}"
        native = f"[{req.native_lang}] {req.unit.topic} example {i + 1}"
        exercises.append(
            Exercise(
                id=f"ex-{i}-{word}",
                type=ex_type,
                prompt=f"Practice: {req.unit.topic}",
                target_text=target,
                native_text=native if req.unit.level.uses_translation else "",
                options=[target, f"{target} (alt A)", f"{target} (alt B)"]
                if ex_type in (ExerciseType.MULTIPLE_CHOICE, ExerciseType.IMAGE_MATCH)
                else [],
                correct_answer=target,
                image_prompt=f"a simple, clear illustration of {req.unit.topic}, item {i + 1}",
                audio_text=target,
                vocab_key=f"{req.unit.id}.{word}",
            )
        )
    return exercises


hf_client = HFClient()
