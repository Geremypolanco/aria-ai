"""
MediaPipeline — Real media generation using FFmpeg + ElevenLabs.

Reads credentials from environment (managed externally in Fly.io):
  ELEVENLABS_API_KEY  — ElevenLabs TTS API key
  OPENAI_API_KEY      — OpenAI Whisper for transcription (optional)

Pipeline stages:
  1. Script  → AI-generated narration text
  2. Audio   → ElevenLabs TTS → WAV/MP3 file
  3. Video   → FFmpeg subtitle overlay + audio merge
  4. Output  → Final MP4 ready for upload

When credentials missing: pipeline runs in "dry-run" mode,
generating metadata without actual media files.
"""

from __future__ import annotations

import asyncio
import logging
import os
import shutil
import time
import uuid
from dataclasses import dataclass, field

import httpx

from apps.core.memory.redis_client import get_cache
from apps.core.tools.ai_client import AIModel, get_ai_client

logger = logging.getLogger("aria.media_pipeline")


# ── DATACLASSES ────────────────────────────────────────────────────────────────


@dataclass
class MediaScript:
    title: str
    narration_text: str
    hook: str
    cta: str
    platform: str = "tiktok"
    script_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    word_count: int = 0
    duration_estimate_s: float = 0.0
    created_at: float = field(default_factory=time.time)

    def __post_init__(self) -> None:
        if self.word_count == 0:
            self.word_count = len(self.narration_text.split())
        if self.duration_estimate_s == 0.0:
            self.duration_estimate_s = self.word_count / 2.5

    def to_dict(self) -> dict:
        return {
            "script_id": self.script_id,
            "title": self.title,
            "narration_text": self.narration_text,
            "hook": self.hook,
            "cta": self.cta,
            "duration_estimate_s": self.duration_estimate_s,
            "platform": self.platform,
            "word_count": self.word_count,
            "created_at": self.created_at,
        }


@dataclass
class AudioAsset:
    script_id: str
    file_path: str
    asset_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    duration_s: float = 0.0
    voice_id: str = ""
    format: str = "mp3"
    size_bytes: int = 0
    elevenlabs_used: bool = False
    dry_run: bool = False
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            "asset_id": self.asset_id,
            "script_id": self.script_id,
            "file_path": self.file_path,
            "duration_s": self.duration_s,
            "voice_id": self.voice_id,
            "format": self.format,
            "size_bytes": self.size_bytes,
            "elevenlabs_used": self.elevenlabs_used,
            "dry_run": self.dry_run,
            "created_at": self.created_at,
        }


@dataclass
class VideoAsset:
    audio_asset_id: str
    file_path: str
    asset_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    width: int = 1080
    height: int = 1920
    fps: int = 30
    duration_s: float = 0.0
    format: str = "mp4"
    size_bytes: int = 0
    ffmpeg_used: bool = False
    dry_run: bool = False
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            "asset_id": self.asset_id,
            "audio_asset_id": self.audio_asset_id,
            "file_path": self.file_path,
            "width": self.width,
            "height": self.height,
            "fps": self.fps,
            "duration_s": self.duration_s,
            "format": self.format,
            "size_bytes": self.size_bytes,
            "ffmpeg_used": self.ffmpeg_used,
            "dry_run": self.dry_run,
            "created_at": self.created_at,
        }


@dataclass
class PipelineResult:
    script: dict
    audio: dict
    video: dict
    platform: str
    total_duration_s: float
    pipeline_duration_s: float
    result_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    status: str = "success"
    error: str = ""
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            "result_id": self.result_id,
            "script": self.script,
            "audio": self.audio,
            "video": self.video,
            "platform": self.platform,
            "status": self.status,
            "error": self.error,
            "total_duration_s": self.total_duration_s,
            "pipeline_duration_s": self.pipeline_duration_s,
            "created_at": self.created_at,
        }


# ── PIPELINE CLASS ──────────────────────────────────────────────────────────────


class MediaPipeline:
    _DEFAULT_VOICE_ID = "21m00Tcm4TlvDq8ikWAM"  # Rachel on ElevenLabs
    _REDIS_KEY = "media:pipeline:v1"
    _REDIS_TTL = 86400 * 30  # 30 days

    def __init__(self) -> None:
        self._elevenlabs_key: str = os.environ.get("ELEVENLABS_API_KEY", "")
        self._openai_key: str = os.environ.get("OPENAI_API_KEY", "")
        self._output_dir: str = os.environ.get("MEDIA_OUTPUT_DIR", "/tmp/aria_media")
        self._pipeline_log: list[dict] = []
        self._loaded: bool = False

    # ── PROPERTIES ─────────────────────────────────────────────────────────────

    @property
    def elevenlabs_configured(self) -> bool:
        return bool(self._elevenlabs_key)

    @property
    def ffmpeg_available(self) -> bool:
        return shutil.which("ffmpeg") is not None

    # ── REDIS PERSISTENCE ──────────────────────────────────────────────────────

    async def _load(self) -> None:
        """Load pipeline log from Redis."""
        if self._loaded:
            return
        try:
            cache = get_cache()
            data = await cache.get(self._REDIS_KEY)
            if isinstance(data, list):
                self._pipeline_log = data
            else:
                self._pipeline_log = []
        except Exception as exc:
            logger.warning("MediaPipeline._load failed: %s", exc)
            self._pipeline_log = []
        self._loaded = True

    async def _save(self) -> None:
        """Persist pipeline log to Redis (keep last 500 entries)."""
        try:
            cache = get_cache()
            await cache.set(
                self._REDIS_KEY,
                self._pipeline_log[-500:],
                ttl_seconds=self._REDIS_TTL,
            )
        except Exception as exc:
            logger.warning("MediaPipeline._save failed: %s", exc)

    # ── FILESYSTEM ─────────────────────────────────────────────────────────────

    async def _ensure_output_dir(self) -> None:
        """Create output directory if it doesn't exist."""
        os.makedirs(self._output_dir, exist_ok=True)

    # ── STAGE 1: SCRIPT GENERATION ─────────────────────────────────────────────

    async def generate_script(
        self,
        topic: str,
        platform: str = "tiktok",
        duration_target_s: int = 60,
    ) -> MediaScript:
        """Use AI to generate a video narration script."""
        target_words = int(duration_target_s * 2.5)

        hook = ""
        narration = ""
        cta = ""

        try:
            ai = get_ai_client()
            result = await ai.complete(
                system=f"You are a viral video scriptwriter for {platform}.",
                user=(
                    f"Write a {duration_target_s}-second script about: {topic}\n\n"
                    f"Target approximately {target_words} words for the narration.\n\n"
                    "Format:\n"
                    "HOOK: (attention-grabbing first line)\n"
                    "NARRATION: (main content, natural speaking pace)\n"
                    "CTA: (call to action)"
                ),
                model=AIModel.FAST,
                max_tokens=600,
            )

            text = result.text if hasattr(result, "text") else str(result)

            # Parse sections from the AI response
            lines = text.strip().splitlines()
            current_section = None
            section_lines: dict[str, list[str]] = {"HOOK": [], "NARRATION": [], "CTA": []}

            for line in lines:
                upper = line.upper()
                if upper.startswith("HOOK:"):
                    current_section = "HOOK"
                    remainder = line[5:].strip()
                    if remainder:
                        section_lines["HOOK"].append(remainder)
                elif upper.startswith("NARRATION:"):
                    current_section = "NARRATION"
                    remainder = line[10:].strip()
                    if remainder:
                        section_lines["NARRATION"].append(remainder)
                elif upper.startswith("CTA:"):
                    current_section = "CTA"
                    remainder = line[4:].strip()
                    if remainder:
                        section_lines["CTA"].append(remainder)
                elif current_section:
                    section_lines[current_section].append(line)

            hook = " ".join(section_lines["HOOK"]).strip()
            narration = " ".join(section_lines["NARRATION"]).strip()
            cta = " ".join(section_lines["CTA"]).strip()

            # Fallback for empty sections
            if not hook:
                hook = f"Did you know this about {topic}?"
            if not narration:
                narration = text.strip()
            if not cta:
                cta = "Follow for more!"

        except Exception as exc:
            logger.warning("generate_script AI call failed: %s", exc)
            hook = f"Did you know this about {topic}?"
            narration = (
                f"{topic} is one of the most fascinating topics you can explore today. "
                "Here's everything you need to know to get started and why it matters."
            )
            cta = "Follow for more amazing content!"

        title = f"{platform.title()} video about {topic}"

        return MediaScript(
            title=title,
            narration_text=narration,
            hook=hook,
            cta=cta,
            platform=platform,
        )

    # ── STAGE 2: AUDIO GENERATION ──────────────────────────────────────────────

    async def generate_audio(
        self,
        script: MediaScript,
        voice_id: str = "",
    ) -> AudioAsset:
        """Convert script narration to audio via ElevenLabs TTS."""
        voice_id = voice_id or self._DEFAULT_VOICE_ID

        if not self.elevenlabs_configured:
            logger.info(
                "ElevenLabs not configured — dry-run audio for script %s",
                script.script_id,
            )
            return AudioAsset(
                script_id=script.script_id,
                file_path=f"/tmp/aria_media/{script.script_id}.mp3",
                duration_s=script.duration_estimate_s,
                voice_id=voice_id,
                dry_run=True,
            )

        try:
            url = f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"
            headers = {
                "xi-api-key": self._elevenlabs_key,
                "Content-Type": "application/json",
                "Accept": "audio/mpeg",
            }
            payload = {
                "text": script.narration_text[:5000],
                "model_id": "eleven_turbo_v2",
                "voice_settings": {
                    "stability": 0.5,
                    "similarity_boost": 0.75,
                },
            }

            async with httpx.AsyncClient(timeout=60.0) as client:
                response = await client.post(url, headers=headers, json=payload)
                response.raise_for_status()

            await self._ensure_output_dir()
            file_path = os.path.join(self._output_dir, f"{script.script_id}.mp3")

            with open(file_path, "wb") as fh:
                fh.write(response.content)

            logger.info(
                "ElevenLabs audio generated: %s (%d bytes)",
                file_path,
                len(response.content),
            )

            return AudioAsset(
                script_id=script.script_id,
                file_path=file_path,
                duration_s=script.duration_estimate_s,
                voice_id=voice_id,
                size_bytes=len(response.content),
                elevenlabs_used=True,
            )

        except Exception as exc:
            logger.error("generate_audio ElevenLabs failed: %s — falling back to dry-run", exc)
            return AudioAsset(
                script_id=script.script_id,
                file_path=f"/tmp/aria_media/{script.script_id}.mp3",
                duration_s=script.duration_estimate_s,
                voice_id=voice_id,
                dry_run=True,
            )

    # ── STAGE 3: VIDEO GENERATION ──────────────────────────────────────────────

    async def generate_video(
        self,
        audio: AudioAsset,
        script: MediaScript,
        background_color: str = "0x1a1a2e",
    ) -> VideoAsset:
        """Compose video from background color + hook text + audio using FFmpeg."""
        if not self.ffmpeg_available or audio.dry_run:
            reason = "FFmpeg unavailable" if not self.ffmpeg_available else "audio is dry-run"
            logger.info("generate_video dry-run (%s) for audio %s", reason, audio.asset_id)
            return VideoAsset(
                audio_asset_id=audio.asset_id,
                file_path=f"/tmp/aria_media/{audio.asset_id}.mp4",
                duration_s=audio.duration_s,
                dry_run=True,
            )

        try:
            await self._ensure_output_dir()
            output_path = os.path.join(self._output_dir, f"{audio.asset_id}.mp4")

            # Sanitize hook text for FFmpeg drawtext (escape special chars)
            safe_hook = (
                script.hook[:50].replace("'", "\\'").replace(":", "\\:").replace("\\", "\\\\")
            )

            cmd = [
                "ffmpeg",
                "-y",
                "-f",
                "lavfi",
                "-i",
                f"color=c={background_color}:size=1080x1920:rate=30",
                "-i",
                audio.file_path,
                "-vf",
                (
                    f"drawtext=text='{safe_hook}':"
                    "fontsize=60:fontcolor=white:"
                    "x=(w-text_w)/2:y=(h-text_h)/2"
                ),
                "-shortest",
                "-c:v",
                "libx264",
                "-c:a",
                "aac",
                output_path,
            ]

            logger.info("Running FFmpeg: %s", " ".join(cmd))

            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            try:
                stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=120.0)
            except TimeoutError:
                proc.kill()
                await proc.communicate()
                raise RuntimeError("FFmpeg process timed out after 120s")

            if proc.returncode != 0:
                err_text = stderr.decode(errors="replace")
                raise RuntimeError(f"FFmpeg exited {proc.returncode}: {err_text[-500:]}")

            size_bytes = 0
            if os.path.exists(output_path):
                size_bytes = os.path.getsize(output_path)

            logger.info("FFmpeg video generated: %s (%d bytes)", output_path, size_bytes)

            return VideoAsset(
                audio_asset_id=audio.asset_id,
                file_path=output_path,
                duration_s=audio.duration_s,
                size_bytes=size_bytes,
                ffmpeg_used=True,
            )

        except Exception as exc:
            logger.error("generate_video FFmpeg failed: %s — falling back to dry-run", exc)
            return VideoAsset(
                audio_asset_id=audio.asset_id,
                file_path=f"/tmp/aria_media/{audio.asset_id}.mp4",
                duration_s=audio.duration_s,
                dry_run=True,
            )

    # ── STAGE 4: FULL PIPELINE ─────────────────────────────────────────────────

    async def run_pipeline(
        self,
        topic: str,
        platform: str = "tiktok",
    ) -> PipelineResult:
        """Run the complete script → audio → video pipeline for a single topic."""
        await self._load()
        pipeline_start = time.time()

        script: MediaScript | None = None
        audio: AudioAsset | None = None
        video: VideoAsset | None = None
        status = "success"
        error_msg = ""

        try:
            script = await self.generate_script(topic, platform=platform)
            audio = await self.generate_audio(script)
            video = await self.generate_video(audio, script)

            # Determine status based on dry-run flags
            if audio.dry_run or video.dry_run:
                status = "dry_run"

        except Exception as exc:
            logger.error("run_pipeline failed for topic '%s': %s", topic, exc)
            status = "failed"
            error_msg = str(exc)

            # Ensure we always have dicts for the result even on failure
            if script is None:
                script = MediaScript(
                    title=f"Failed: {topic}",
                    narration_text="",
                    hook="",
                    cta="",
                    platform=platform,
                )
            if audio is None:
                audio = AudioAsset(
                    script_id=script.script_id,
                    file_path="",
                    dry_run=True,
                )
            if video is None:
                video = VideoAsset(
                    audio_asset_id=audio.asset_id,
                    file_path="",
                    dry_run=True,
                )

        pipeline_duration = time.time() - pipeline_start
        total_duration = video.duration_s if video else 0.0

        result = PipelineResult(
            script=script.to_dict(),
            audio=audio.to_dict(),
            video=video.to_dict(),
            platform=platform,
            status=status,
            error=error_msg,
            total_duration_s=total_duration,
            pipeline_duration_s=pipeline_duration,
        )

        self._pipeline_log.append(result.to_dict())
        await self._save()

        return result

    # ── BATCH PIPELINE ─────────────────────────────────────────────────────────

    async def batch_pipeline(
        self,
        topics: list[str],
        platform: str = "tiktok",
    ) -> list[PipelineResult]:
        """Run the pipeline concurrently for multiple topics."""
        tasks = [self.run_pipeline(topic, platform=platform) for topic in topics]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        output: list[PipelineResult] = []
        for topic, result in zip(topics, results, strict=False):
            if isinstance(result, Exception):
                logger.error("batch_pipeline exception for '%s': %s", topic, result)
                fallback_script = MediaScript(
                    title=f"Failed: {topic}",
                    narration_text="",
                    hook="",
                    cta="",
                    platform=platform,
                )
                fallback_audio = AudioAsset(
                    script_id=fallback_script.script_id,
                    file_path="",
                    dry_run=True,
                )
                fallback_video = VideoAsset(
                    audio_asset_id=fallback_audio.asset_id,
                    file_path="",
                    dry_run=True,
                )
                output.append(
                    PipelineResult(
                        script=fallback_script.to_dict(),
                        audio=fallback_audio.to_dict(),
                        video=fallback_video.to_dict(),
                        platform=platform,
                        status="failed",
                        error=str(result),
                        total_duration_s=0.0,
                        pipeline_duration_s=0.0,
                    )
                )
            else:
                output.append(result)

        return output

    # ── STATS & QUERIES ────────────────────────────────────────────────────────

    def pipeline_stats(self) -> dict:
        """Aggregate statistics over all recorded pipeline runs."""
        total = len(self._pipeline_log)
        if total == 0:
            return {
                "total_runs": 0,
                "success_rate_pct": 0.0,
                "dry_run_rate_pct": 0.0,
                "elevenlabs_configured": self.elevenlabs_configured,
                "ffmpeg_available": self.ffmpeg_available,
                "avg_pipeline_duration_s": 0.0,
                "output_dir": self._output_dir,
            }

        successes = sum(1 for r in self._pipeline_log if r.get("status") == "success")
        dry_runs = sum(1 for r in self._pipeline_log if r.get("status") == "dry_run")
        durations = [
            r.get("pipeline_duration_s", 0.0)
            for r in self._pipeline_log
            if isinstance(r.get("pipeline_duration_s"), (int, float))
        ]
        avg_duration = sum(durations) / len(durations) if durations else 0.0

        return {
            "total_runs": total,
            "success_rate_pct": round(successes / total * 100, 1),
            "dry_run_rate_pct": round(dry_runs / total * 100, 1),
            "elevenlabs_configured": self.elevenlabs_configured,
            "ffmpeg_available": self.ffmpeg_available,
            "avg_pipeline_duration_s": round(avg_duration, 2),
            "output_dir": self._output_dir,
        }

    def recent_pipeline_results(self, limit: int = 10) -> list[dict]:
        """Return the most recent N pipeline run records."""
        return self._pipeline_log[-limit:]


# ── SINGLETON ──────────────────────────────────────────────────────────────────

_pipeline_instance: MediaPipeline | None = None


def get_media_pipeline() -> MediaPipeline:
    global _pipeline_instance
    if _pipeline_instance is None:
        _pipeline_instance = MediaPipeline()
    return _pipeline_instance
