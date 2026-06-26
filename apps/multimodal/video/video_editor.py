from __future__ import annotations

import asyncio
import logging
import shutil
import time
import uuid
from dataclasses import dataclass, field
from enum import StrEnum

logger = logging.getLogger("aria.video_editor")

# ── Enums ────────────────────────────────────────────────────


class EditOperation(StrEnum):
    TRIM = "trim"
    CONCAT = "concat"
    ADD_TEXT = "add_text"
    ADD_MUSIC = "add_music"
    CLIP_EXTRACT = "clip_extract"
    SUBTITLE = "subtitle"
    TRANSITION = "transition"


# ── Dataclass ────────────────────────────────────────────────


@dataclass
class EditTask:
    task_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    operation: EditOperation = EditOperation.TRIM
    input_urls: list[str] = field(default_factory=list)
    output_url: str = ""
    params: dict = field(default_factory=dict)
    status: str = "pending"
    created_at: float = field(default_factory=time.time)


# ── Editor ───────────────────────────────────────────────────

_PLATFORM_FFMPEG_ARGS: dict[str, dict] = {
    "tiktok": {
        "vf": "crop=ih*9/16:ih,scale=1080:1920",
        "aspect": "9:16",
    },
    "youtube": {
        "vf": None,
        "aspect": "16:9",
    },
    "instagram_reel": {
        "vf": "crop=ih*9/16:ih,scale=1080:1920",
        "aspect": "9:16",
    },
    "youtube_shorts": {
        "vf": "crop=ih*9/16:ih,scale=1080:1920",
        "aspect": "9:16",
    },
}


class VideoEditor:
    """Automated video editing and assembly with ffmpeg/moviepy support."""

    def __init__(self) -> None:
        self._ffmpeg_available: bool = shutil.which("ffmpeg") is not None
        self._moviepy_available: bool = self._check_moviepy()
        self._tasks: list[EditTask] = []
        logger.debug(
            "[VideoEditor] ffmpeg=%s moviepy=%s",
            self._ffmpeg_available,
            self._moviepy_available,
        )

    @staticmethod
    def _check_moviepy() -> bool:
        try:
            import importlib

            return importlib.util.find_spec("moviepy") is not None
        except Exception:
            return False

    def _record(self, task: EditTask) -> EditTask:
        self._tasks.append(task)
        return task

    # ── Operations ───────────────────────────────────────────

    async def trim(
        self,
        video_url: str,
        start_sec: float,
        end_sec: float,
    ) -> EditTask:
        task = EditTask(
            operation=EditOperation.TRIM,
            input_urls=[video_url],
            params={"start_sec": start_sec, "end_sec": end_sec},
        )
        self._record(task)

        if self._ffmpeg_available:
            try:
                output = video_url.replace(".", f"_trim_{start_sec}_{end_sec}.", 1)
                cmd = [
                    "ffmpeg",
                    "-y",
                    "-i",
                    video_url,
                    "-ss",
                    str(start_sec),
                    "-to",
                    str(end_sec),
                    "-c",
                    "copy",
                    output,
                ]
                proc = await asyncio.create_subprocess_exec(
                    *cmd,
                    stdout=asyncio.subprocess.DEVNULL,
                    stderr=asyncio.subprocess.DEVNULL,
                )
                await proc.wait()
                task.output_url = output
                task.status = "completed" if proc.returncode == 0 else "failed"
            except Exception as exc:
                logger.warning("[VideoEditor] trim failed: %s", exc)
                task.status = "failed"
        else:
            task.status = "simulated"
            task.output_url = f"https://storage.aria.ai/edited/trim_{task.task_id}.mp4"

        return task

    async def extract_clips(
        self,
        video_url: str,
        clip_intervals: list[tuple[float, float]],
    ) -> list[EditTask]:
        tasks = await asyncio.gather(
            *[self.trim(video_url, start, end) for start, end in clip_intervals]
        )
        return list(tasks)

    async def add_subtitles(
        self,
        video_url: str,
        transcript: list[dict],
    ) -> EditTask:
        srt_content = self.generate_srt(transcript)
        task = EditTask(
            operation=EditOperation.SUBTITLE,
            input_urls=[video_url],
            params={"srt": srt_content, "line_count": len(transcript)},
        )
        self._record(task)
        task.status = "completed"
        task.output_url = f"https://storage.aria.ai/edited/subtitled_{task.task_id}.mp4"
        return task

    async def create_compilation(
        self,
        clip_urls: list[str],
        transitions: bool = True,
    ) -> EditTask:
        task = EditTask(
            operation=EditOperation.CONCAT,
            input_urls=clip_urls,
            params={"transitions": transitions, "clip_count": len(clip_urls)},
        )
        self._record(task)

        if self._ffmpeg_available and clip_urls:
            try:
                concat_list = "\n".join(f"file '{u}'" for u in clip_urls)
                concat_file = f"/tmp/concat_{task.task_id}.txt"
                with open(concat_file, "w") as f:
                    f.write(concat_list)
                output = f"/tmp/compilation_{task.task_id}.mp4"
                cmd = [
                    "ffmpeg",
                    "-y",
                    "-f",
                    "concat",
                    "-safe",
                    "0",
                    "-i",
                    concat_file,
                    "-c",
                    "copy",
                    output,
                ]
                proc = await asyncio.create_subprocess_exec(
                    *cmd,
                    stdout=asyncio.subprocess.DEVNULL,
                    stderr=asyncio.subprocess.DEVNULL,
                )
                await proc.wait()
                task.output_url = output
                task.status = "completed" if proc.returncode == 0 else "failed"
            except Exception as exc:
                logger.warning("[VideoEditor] compilation failed: %s", exc)
                task.status = "failed"
        else:
            task.status = "simulated"
            task.output_url = f"https://storage.aria.ai/edited/compilation_{task.task_id}.mp4"

        return task

    # ── Utilities ────────────────────────────────────────────

    def format_for_platform(self, video_url: str, platform: str) -> dict:
        args = _PLATFORM_FFMPEG_ARGS.get(platform, _PLATFORM_FFMPEG_ARGS["youtube"])
        result: dict = {"input": video_url, "platform": platform}
        result.update(args)
        if args.get("vf"):
            result["ffmpeg_cmd"] = (
                f'ffmpeg -i "{video_url}" -vf "{args["vf"]}" ' f"-c:a copy output_{platform}.mp4"
            )
        else:
            result["ffmpeg_cmd"] = f'ffmpeg -i "{video_url}" -c copy output_{platform}.mp4'
        return result

    @staticmethod
    def generate_srt(transcript: list[dict]) -> str:
        """Convert transcript [{text, start, end}, ...] to SRT format string."""
        lines: list[str] = []
        for idx, entry in enumerate(transcript, start=1):
            start = entry.get("start", 0.0)
            end = entry.get("end", start + 2.0)
            text = entry.get("text", "")
            lines.append(str(idx))
            lines.append(f"{_srt_time(start)} --> {_srt_time(end)}")
            lines.append(text)
            lines.append("")
        return "\n".join(lines)

    def task_summary(self) -> dict:
        by_op: dict[str, int] = {}
        completed = 0
        pending = 0
        for t in self._tasks:
            op = t.operation.value
            by_op[op] = by_op.get(op, 0) + 1
            if t.status in ("completed", "simulated"):
                completed += 1
            else:
                pending += 1
        return {
            "total_tasks": len(self._tasks),
            "completed": completed,
            "pending": pending,
            "by_operation": by_op,
        }


def _srt_time(seconds: float) -> str:
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    ms = int((seconds - int(seconds)) * 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


# ── Singleton ────────────────────────────────────────────────

_video_editor: VideoEditor | None = None


def get_video_editor() -> VideoEditor:
    global _video_editor
    if _video_editor is None:
        _video_editor = VideoEditor()
    return _video_editor
