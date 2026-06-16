"""Phase 14 tests — MediaPipeline."""
from __future__ import annotations
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


def _mock_cache():
    c = MagicMock()
    c.get = AsyncMock(return_value=None)
    c.set = AsyncMock(return_value=True)
    return c


def _mock_ai(content="HOOK: Are you leaving money on the table?\nNARRATION: Most entrepreneurs overlook this simple AI hack that generates $10k monthly.\nCTA: Follow for more AI business tips."):
    ai = MagicMock()
    r = MagicMock()
    r.success = True
    r.content = content
    ai.complete = AsyncMock(return_value=r)
    return ai


@pytest.fixture
def pipeline():
    with patch("apps.video.media.media_pipeline.get_cache", return_value=_mock_cache()):
        with patch("apps.video.media.media_pipeline.get_ai_client", return_value=_mock_ai()):
            from apps.video.media.media_pipeline import MediaPipeline
            return MediaPipeline()


# ── Dataclasses ────────────────────────────────────────────────────────────────

def test_media_script_to_dict_has_required_keys(pipeline):
    from apps.video.media.media_pipeline import MediaScript
    s = MediaScript(title="Test", narration_text="Hello world, this is a test narration for AI.", hook="Are you ready?", cta="Follow now")
    d = s.to_dict()
    required = {"script_id", "title", "narration_text", "hook", "cta",
                "duration_estimate_s", "platform", "word_count"}
    assert required.issubset(d.keys())


def test_media_script_computes_word_count(pipeline):
    from apps.video.media.media_pipeline import MediaScript
    text = "one two three four five"
    s = MediaScript(title="T", narration_text=text, hook="h", cta="c")
    assert s.word_count == 5


def test_media_script_computes_duration(pipeline):
    from apps.video.media.media_pipeline import MediaScript
    text = " ".join(["word"] * 50)
    s = MediaScript(title="T", narration_text=text, hook="h", cta="c")
    assert s.duration_estimate_s == pytest.approx(20.0, rel=0.1)


def test_audio_asset_to_dict_has_required_keys(pipeline):
    from apps.video.media.media_pipeline import AudioAsset
    a = AudioAsset(script_id="abc", file_path="/tmp/test.mp3")
    d = a.to_dict()
    required = {"asset_id", "script_id", "file_path", "duration_s", "voice_id",
                "format", "size_bytes", "elevenlabs_used", "dry_run"}
    assert required.issubset(d.keys())


def test_video_asset_to_dict_has_required_keys(pipeline):
    from apps.video.media.media_pipeline import VideoAsset
    v = VideoAsset(audio_asset_id="abc", file_path="/tmp/test.mp4")
    d = v.to_dict()
    required = {"asset_id", "audio_asset_id", "file_path", "width", "height",
                "fps", "duration_s", "format", "ffmpeg_used", "dry_run"}
    assert required.issubset(d.keys())


def test_pipeline_result_to_dict_has_required_keys(pipeline):
    from apps.video.media.media_pipeline import PipelineResult
    r = PipelineResult(script={}, audio={}, video={}, platform="tiktok", status="dry_run",
                       total_duration_s=30.0, pipeline_duration_s=2.0)
    d = r.to_dict()
    required = {"result_id", "script", "audio", "video", "platform", "status",
                "error", "total_duration_s", "pipeline_duration_s"}
    assert required.issubset(d.keys())


# ── Properties ─────────────────────────────────────────────────────────────────

def test_elevenlabs_not_configured_by_default(pipeline):
    assert pipeline.elevenlabs_configured is False


def test_ffmpeg_available_returns_bool(pipeline):
    result = pipeline.ffmpeg_available
    assert isinstance(result, bool)


# ── generate_script ────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_generate_script_returns_media_script(pipeline):
    from apps.video.media.media_pipeline import MediaScript
    script = await pipeline.generate_script("AI for business", "tiktok", 60)
    assert isinstance(script, MediaScript)


@pytest.mark.asyncio
async def test_generate_script_has_title(pipeline):
    script = await pipeline.generate_script("Productivity hacks")
    assert len(script.title) > 0


@pytest.mark.asyncio
async def test_generate_script_has_hook(pipeline):
    script = await pipeline.generate_script("Marketing tips", "linkedin")
    assert len(script.hook) > 0


@pytest.mark.asyncio
async def test_generate_script_has_narration(pipeline):
    script = await pipeline.generate_script("Sales funnel")
    assert len(script.narration_text) > 0


@pytest.mark.asyncio
async def test_generate_script_has_cta(pipeline):
    script = await pipeline.generate_script("Email marketing")
    assert len(script.cta) > 0


@pytest.mark.asyncio
async def test_generate_script_positive_duration(pipeline):
    script = await pipeline.generate_script("SEO basics", duration_target_s=30)
    assert script.duration_estimate_s > 0.0


@pytest.mark.asyncio
async def test_generate_script_platform_stored(pipeline):
    script = await pipeline.generate_script("Topic", "instagram")
    assert script.platform == "instagram"


# ── generate_audio ─────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_generate_audio_returns_audio_asset(pipeline):
    from apps.video.media.media_pipeline import AudioAsset, MediaScript
    script = MediaScript(title="Test", narration_text="Hello world test narration.", hook="H", cta="C")
    audio = await pipeline.generate_audio(script)
    assert isinstance(audio, AudioAsset)


@pytest.mark.asyncio
async def test_generate_audio_dry_run_without_key(pipeline):
    from apps.video.media.media_pipeline import MediaScript
    script = MediaScript(title="Test", narration_text="Test narration content here.", hook="H", cta="C")
    audio = await pipeline.generate_audio(script)
    assert audio.dry_run is True


@pytest.mark.asyncio
async def test_generate_audio_has_file_path(pipeline):
    from apps.video.media.media_pipeline import MediaScript
    script = MediaScript(title="T", narration_text="Short narration text.", hook="H", cta="C")
    audio = await pipeline.generate_audio(script)
    assert len(audio.file_path) > 0


@pytest.mark.asyncio
async def test_generate_audio_not_elevenlabs_used_dry_run(pipeline):
    from apps.video.media.media_pipeline import MediaScript
    script = MediaScript(title="T", narration_text="Test content.", hook="H", cta="C")
    audio = await pipeline.generate_audio(script)
    assert audio.elevenlabs_used is False


# ── generate_video ─────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_generate_video_returns_video_asset(pipeline):
    from apps.video.media.media_pipeline import AudioAsset, MediaScript, VideoAsset
    script = MediaScript(title="T", narration_text="Content.", hook="H", cta="C")
    audio = AudioAsset(script_id="test", file_path="/tmp/test.mp3", dry_run=True)
    video = await pipeline.generate_video(audio, script)
    assert isinstance(video, VideoAsset)


@pytest.mark.asyncio
async def test_generate_video_dry_run_when_audio_dry(pipeline):
    from apps.video.media.media_pipeline import AudioAsset, MediaScript
    script = MediaScript(title="T", narration_text="Content.", hook="H", cta="C")
    audio = AudioAsset(script_id="test", file_path="/tmp/test.mp3", dry_run=True)
    video = await pipeline.generate_video(audio, script)
    assert video.dry_run is True


@pytest.mark.asyncio
async def test_generate_video_has_file_path(pipeline):
    from apps.video.media.media_pipeline import AudioAsset, MediaScript
    script = MediaScript(title="T", narration_text="Content.", hook="H", cta="C")
    audio = AudioAsset(script_id="test", file_path="/tmp/audio.mp3", dry_run=True)
    video = await pipeline.generate_video(audio, script)
    assert len(video.file_path) > 0


@pytest.mark.asyncio
async def test_generate_video_1080x1920_format(pipeline):
    from apps.video.media.media_pipeline import AudioAsset, MediaScript
    script = MediaScript(title="T", narration_text="Content.", hook="H", cta="C")
    audio = AudioAsset(script_id="test", file_path="/tmp/audio.mp3", dry_run=True)
    video = await pipeline.generate_video(audio, script)
    assert video.width == 1080
    assert video.height == 1920


# ── run_pipeline ───────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_run_pipeline_returns_result(pipeline):
    from apps.video.media.media_pipeline import PipelineResult
    result = await pipeline.run_pipeline("AI business tips", "tiktok")
    assert isinstance(result, PipelineResult)


@pytest.mark.asyncio
async def test_run_pipeline_has_result_id(pipeline):
    result = await pipeline.run_pipeline("Marketing")
    assert len(result.result_id) > 0


@pytest.mark.asyncio
async def test_run_pipeline_platform_stored(pipeline):
    result = await pipeline.run_pipeline("Topic", "instagram")
    assert result.platform == "instagram"


@pytest.mark.asyncio
async def test_run_pipeline_has_status(pipeline):
    result = await pipeline.run_pipeline("SEO tips")
    assert result.status in ("success", "failed", "dry_run")


@pytest.mark.asyncio
async def test_run_pipeline_has_script(pipeline):
    result = await pipeline.run_pipeline("Email list building")
    assert isinstance(result.script, dict)


@pytest.mark.asyncio
async def test_run_pipeline_stores_in_log(pipeline):
    await pipeline._load()
    await pipeline.run_pipeline("Topic")
    assert len(pipeline._pipeline_log) == 1


@pytest.mark.asyncio
async def test_multiple_pipelines_accumulate(pipeline):
    await pipeline._load()
    await pipeline.run_pipeline("Topic A")
    await pipeline.run_pipeline("Topic B")
    assert len(pipeline._pipeline_log) == 2


# ── batch_pipeline ─────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_batch_pipeline_returns_list(pipeline):
    results = await pipeline.batch_pipeline(["Topic A", "Topic B", "Topic C"])
    assert isinstance(results, list)
    assert len(results) == 3


@pytest.mark.asyncio
async def test_batch_pipeline_all_results(pipeline):
    from apps.video.media.media_pipeline import PipelineResult
    results = await pipeline.batch_pipeline(["T1", "T2"])
    assert all(isinstance(r, PipelineResult) for r in results)


# ── pipeline_stats ─────────────────────────────────────────────────────────────

def test_pipeline_stats_has_required_keys(pipeline):
    stats = pipeline.pipeline_stats()
    required = {"total_runs", "success_rate_pct", "dry_run_rate_pct",
                "elevenlabs_configured", "ffmpeg_available", "avg_pipeline_duration_s", "output_dir"}
    assert required.issubset(stats.keys())


def test_pipeline_stats_elevenlabs_false_by_default(pipeline):
    stats = pipeline.pipeline_stats()
    assert stats["elevenlabs_configured"] is False


@pytest.mark.asyncio
async def test_pipeline_stats_reflect_runs(pipeline):
    await pipeline._load()
    await pipeline.run_pipeline("Stats topic")
    stats = pipeline.pipeline_stats()
    assert stats["total_runs"] == 1


def test_recent_pipeline_results_returns_list(pipeline):
    result = pipeline.recent_pipeline_results(limit=5)
    assert isinstance(result, list)


@pytest.mark.asyncio
async def test_recent_pipeline_results_after_run(pipeline):
    await pipeline._load()
    await pipeline.run_pipeline("Recent test")
    result = pipeline.recent_pipeline_results(limit=5)
    assert len(result) >= 1
