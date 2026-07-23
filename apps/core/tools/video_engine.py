"""
video_engine.py — ARIA's own video engine (layer 1: produced reels via ffmpeg).

No external video API and no GPU: it composes a *real* MP4 from pieces ARIA
already produces — FLUX images (with Ken Burns pan/zoom motion), an optional
ElevenLabs voiceover, and burned-in captions — stitched with ffmpeg. Reliable,
free, deterministic, no queue.

This is honest about what it is: a produced reel (motion + narration over
generated stills), NOT AI-generated moving footage. Layer 2 — true text-to-video
via open-weights models on a rented GPU — plugs in later behind the same
`generate()` interface.
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import re
import shutil
import subprocess
import tempfile

logger = logging.getLogger("aria.video_engine")

_FONT_CANDIDATES = (
    "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf",
)

W, H, FPS = 1280, 720, 30


class VideoEngine:
    """Compose a produced reel from generated stills + voiceover via ffmpeg."""

    # ── environment ───────────────────────────────────────────────
    @staticmethod
    def ffmpeg_bin() -> str | None:
        """Locate an ffmpeg binary: system first, then the pip-bundled static one."""
        found = shutil.which("ffmpeg")
        if found:
            return found
        try:
            import imageio_ffmpeg

            return imageio_ffmpeg.get_ffmpeg_exe()
        except Exception:
            return None

    @staticmethod
    def _font() -> str | None:
        for f in _FONT_CANDIDATES:
            if os.path.exists(f):
                return f
        return None

    _drawtext_cache: dict[str, bool] = {}

    @classmethod
    def _supports_drawtext(cls, ffmpeg: str) -> bool:
        """Some minimal ffmpeg builds (e.g. imageio-ffmpeg) lack drawtext; the
        production apt build has it. Probe once so captions degrade gracefully."""
        if ffmpeg not in cls._drawtext_cache:
            try:
                out = subprocess.run(
                    [ffmpeg, "-hide_banner", "-filters"], capture_output=True, timeout=20
                )
                cls._drawtext_cache[ffmpeg] = b"drawtext" in out.stdout
            except Exception:
                cls._drawtext_cache[ffmpeg] = False
        return cls._drawtext_cache[ffmpeg]

    # ── scene planning ────────────────────────────────────────────
    async def _plan(self, topic: str, n_scenes: int) -> list[dict]:
        """Break a topic into N visual scenes (image prompt + caption + narration).

        Uses the AI client; degrades to simple deterministic variations so the
        engine always has something to render.
        """
        try:
            from apps.core.tools.ai_client import AIModel, get_ai_client

            ai = get_ai_client()
            resp = await ai.complete(
                system=("You are a short-form video director. Return STRICT JSON only."),
                user=(
                    f"Topic: {topic}\n"
                    f"Design {n_scenes} sequential scenes for a short vertical-friendly "
                    "reel. For each scene give a vivid image-generation prompt, a very "
                    "short on-screen caption (<= 6 words), and one narration sentence. "
                    'Return JSON: {"scenes":[{"image_prompt":"...","caption":"...",'
                    '"narration":"..."}]}'
                ),
                model=AIModel.CREATIVE,
            )
            if getattr(resp, "success", False) and resp.content:
                m = re.search(r"\{.*\}", resp.content, re.DOTALL)
                if m:
                    scenes = json.loads(m.group(0)).get("scenes", [])
                    scenes = [s for s in scenes if s.get("image_prompt")][:n_scenes]
                    if scenes:
                        return scenes
        except Exception as exc:  # noqa: BLE001
            logger.warning("[video] scene planning fell back: %s", exc)

        # Deterministic fallback: cinematic variations on the raw topic.
        angles = [
            "cinematic wide establishing shot",
            "dynamic close-up, shallow depth of field",
            "dramatic low-angle hero shot",
            "warm golden-hour lighting, motion blur",
            "vibrant high-energy composition",
        ]
        return [
            {
                "image_prompt": f"{topic}, {angles[i % len(angles)]}, high detail, 8k",
                "caption": "",
                "narration": "",
            }
            for i in range(n_scenes)
        ]

    # ── public API ────────────────────────────────────────────────
    async def generate(
        self,
        topic: str,
        *,
        n_scenes: int = 4,
        seconds_per_scene: float = 4.0,
        with_voice: bool = True,
        with_captions: bool = True,
    ) -> dict:
        """Produce an MP4 reel for `topic`. Returns {success, video_bytes, ...}."""
        ffmpeg = self.ffmpeg_bin()
        if not ffmpeg:
            return {"success": False, "error": "ffmpeg is not available on the server"}

        scenes = await self._plan(topic, max(1, min(n_scenes, 6)))

        from apps.core.tools.content_tools import ContentTools

        ct = ContentTools()
        rendered: list[tuple[bytes, dict]] = []
        for s in scenes:
            r = await ct.flux_generate_image(s["image_prompt"])
            if r.get("success") and r.get("image_bytes"):
                rendered.append((r["image_bytes"], s))
        if not rendered:
            return {"success": False, "error": "Could not generate any image for the video"}

        audio_bytes: bytes | None = None
        if with_voice:
            narration = " ".join(s.get("narration", "") for _, s in rendered).strip()
            if narration:
                tts = await ct.elevenlabs_tts(narration)
                if tts.get("success") and tts.get("audio_base64"):
                    audio_bytes = base64.b64decode(tts["audio_base64"])

        try:
            mp4 = await asyncio.to_thread(
                self._compose, ffmpeg, rendered, audio_bytes, seconds_per_scene, with_captions
            )
        except Exception as exc:  # noqa: BLE001
            logger.error("[video] ffmpeg compose failed: %s", exc)
            return {"success": False, "error": f"Failed to compose the video: {exc}"}
        if not mp4:
            return {"success": False, "error": "ffmpeg did not produce the video"}

        return {
            "success": True,
            "video_bytes": mp4,
            "video_base64": base64.b64encode(mp4).decode(),
            "content_type": "video/mp4",
            "scenes": len(rendered),
            "has_audio": audio_bytes is not None,
            "description": f"Generated reel: {topic}",
        }

    # ── ffmpeg composition (blocking; run via asyncio.to_thread) ───
    def _run(self, args: list[str]) -> None:
        proc = subprocess.run(args, capture_output=True, timeout=300)
        if proc.returncode != 0:
            raise RuntimeError(proc.stderr.decode("utf-8", "replace")[-500:])

    def _scene_clip(
        self, ffmpeg: str, img_path: str, out_path: str, sps: float, caption: str
    ) -> None:
        frames = max(1, int(sps * FPS))
        # Fill the frame (cover), then a slow Ken Burns zoom.
        vf = (
            f"scale={W}:{H}:force_original_aspect_ratio=increase,"
            f"crop={W}:{H},"
            f"zoompan=z='min(zoom+0.0012,1.15)':d={frames}:s={W}x{H}:fps={FPS}"
        )
        font = self._font()
        cap_file = None
        if caption and font and self._supports_drawtext(ffmpeg):
            cap_file = out_path + ".txt"
            with open(cap_file, "w", encoding="utf-8") as fh:
                fh.write(caption)
            # textfile avoids all drawtext escaping pitfalls.
            vf += (
                f",drawtext=fontfile='{font}':textfile='{cap_file}':"
                "fontcolor=white:fontsize=44:box=1:boxcolor=black@0.45:boxborderw=18:"
                "x=(w-text_w)/2:y=h-text_h-70"
            )
        self._run(
            [
                ffmpeg,
                "-y",
                "-loop",
                "1",
                "-i",
                img_path,
                "-t",
                f"{sps}",
                "-vf",
                vf,
                "-c:v",
                "libx264",
                "-pix_fmt",
                "yuv420p",
                "-r",
                str(FPS),
                out_path,
            ]
        )
        if cap_file and os.path.exists(cap_file):
            os.remove(cap_file)

    def _compose(
        self,
        ffmpeg: str,
        rendered: list[tuple[bytes, dict]],
        audio_bytes: bytes | None,
        sps: float,
        with_captions: bool,
    ) -> bytes | None:
        with tempfile.TemporaryDirectory() as tmp:
            clips: list[str] = []
            for i, (img, scene) in enumerate(rendered):
                img_path = os.path.join(tmp, f"img_{i}.png")
                with open(img_path, "wb") as fh:
                    fh.write(img)
                clip = os.path.join(tmp, f"clip_{i}.mp4")
                caption = scene.get("caption", "") if with_captions else ""
                self._scene_clip(ffmpeg, img_path, clip, sps, caption)
                clips.append(clip)

            concat_list = os.path.join(tmp, "list.txt")
            with open(concat_list, "w", encoding="utf-8") as fh:
                for c in clips:
                    fh.write(f"file '{c}'\n")

            silent = os.path.join(tmp, "silent.mp4")
            self._run(
                [
                    ffmpeg,
                    "-y",
                    "-f",
                    "concat",
                    "-safe",
                    "0",
                    "-i",
                    concat_list,
                    "-c",
                    "copy",
                    silent,
                ]
            )

            out = os.path.join(tmp, "final.mp4")
            if audio_bytes:
                audio_path = os.path.join(tmp, "voice.mp3")
                with open(audio_path, "wb") as fh:
                    fh.write(audio_bytes)
                self._run(
                    [
                        ffmpeg,
                        "-y",
                        "-i",
                        silent,
                        "-i",
                        audio_path,
                        "-c:v",
                        "copy",
                        "-c:a",
                        "aac",
                        "-shortest",
                        out,
                    ]
                )
            else:
                out = silent

            with open(out, "rb") as fh:
                return fh.read()


_engine: VideoEngine | None = None


def get_video_engine() -> VideoEngine:
    global _engine
    if _engine is None:
        _engine = VideoEngine()
    return _engine
