# ARIA Video Engine

ARIA generates video in two layers, chosen automatically per request.

## Layer 1 — Reel engine (default, free, no GPU)
`apps/core/tools/video_engine.py`

Composes a **real MP4** from pieces ARIA already produces: FLUX stills → Ken
Burns pan/zoom clips → concat → optional ElevenLabs voiceover → burned-in
captions, stitched with `ffmpeg`. Deterministic, no queue, no per-clip cost.

It is a **produced reel** (motion + narration over generated stills), not AI
moving footage. Always available (ffmpeg ships in the image).

## Layer 2 — AI footage (opt-in, paid GPU)
`apps/core/tools/video_ai.py`

Runs an open-weights text-to-video model (LTX-Video / Wan2.2) on rented GPU and
returns **real generated footage**. Enabled by setting one token; costs GPU time
per clip (seconds-to-minutes).

Providers, tried in order:

| Provider | Secret to set | Default model (override) |
|---|---|---|
| **Replicate** | `REPLICATE_API_TOKEN` | `REPLICATE_VIDEO_MODEL` = `lightricks/ltx-video` |
| **fal.ai** | `FAL_KEY` | `FAL_VIDEO_MODEL` = `fal-ai/ltx-video` |

```bash
fly secrets set REPLICATE_API_TOKEN="r8_..."
# optional: fly secrets set REPLICATE_VIDEO_MODEL="wan-video/wan-2.2"
```

## Routing (in `aria_mind` `generate_video`)
1. **Layer 2** if a provider token is configured — real AI footage.
2. else **Layer 1** reel engine.
3. else the free Wan2.2 HF Space (best-effort; ZeroGPU queue).

The first success wins; each step degrades with the provider's real error, never
a silent failure.

> Honesty: without a Layer-2 token you get produced reels, not AI moving footage.
> Layer 2 is real generative video but is not free and not instant.
