# Lingua — AI Language Coach

A standalone language-learning app, **independent from the ARIA product** in
this repository (no shared code, database, or deployment — see
[Independence from ARIA](#independence-from-aria) below).

Lingua teaches any language, beginner to native speaker, blending two proven
methodologies:

- **Duolingo-style** gamified skill tree, spaced repetition, XP, streaks, and hearts.
- **Rosetta Stone-style** immersion: early lessons teach meaning through images
  and audio only, with translations introduced gradually as the learner advances.

On top of that, a Hugging Face model powers three things static courses can't do:

1. **Personalized exercises** — generated per lesson from the learner's level,
   native/target language pair, stated interests, and recent mistakes, instead
   of one fixed script for everyone.
2. **Real audio and images** — text-to-speech per phrase and generated
   illustrations per vocabulary item.
3. **Live spoken conversation practice** ("Talk Live") — push-to-talk voice
   chat with an AI tutor: your speech is transcribed, the model replies in the
   target language at your level (with gentle corrections), and the reply is
   spoken back to you while an avatar animates — the practical equivalent of
   a video-call conversation partner, without requiring full video generation.

## Architecture

```
language-app/
  backend/
    main.py          FastAPI app + static frontend mount
    config.py         env-based settings (HF_TOKEN, model IDs, ports)
    models.py          Pydantic/enum domain models (CEFR levels, exercise types)
    db.py               SQLite persistence (stdlib sqlite3, zero extra deps)
    curriculum.py    language-agnostic skill tree + HF prompt templates
    srs.py               SM-2 spaced repetition + XP/streak/leveling logic
    hf_client.py      HF Inference API wrapper: chat, text-to-image, TTS, STT
    routers/             users, lessons, content (media), progress, conversation (WebSocket)
  frontend/            vanilla HTML/CSS/JS SPA — no build step
  tests/                  pytest suite (SRS, curriculum, and full API flow)
```

### Why SQLite instead of ARIA's Supabase/Postgres?

Because this is meant to run and ship as its own product. It has no runtime
dependency on ARIA's infrastructure, credentials, or schema — clone this
directory alone and it works.

## Setup

```bash
cd language-app
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # then add your HF_TOKEN
```

Get a Hugging Face token at https://huggingface.co/settings/tokens (read
access is enough — it's used against the free-tier serverless Inference API /
Inference Providers).

### Run

```bash
uvicorn backend.main:app --reload --port 8100
# or: python -m backend.main
```

Then open http://localhost:8100/.

Without `HF_TOKEN` set, the app still runs in **demo mode**: the skill tree,
gamification, and lesson flow all work end-to-end, but exercises use
placeholder template text and there's no audio/image/voice generation. Set
`HF_TOKEN` for the real, personalized experience.

### Test

```bash
pytest
```

The test suite (SRS scheduling, curriculum/prompt logic, and a full
onboarding→lesson→progress API flow) runs entirely offline against an
isolated temp SQLite file per test — no HF network calls, no shared state
with dev data.

## Models used (all via Hugging Face Inference API, overridable via env vars)

| Purpose                          | Default model                       |
|-----------------------------------|--------------------------------------|
| Exercise generation / tutor chat  | `Qwen/Qwen2.5-7B-Instruct`           |
| Vocabulary illustrations          | `black-forest-labs/FLUX.1-schnell`  |
| Speech-to-text (conversation mode)| `openai/whisper-large-v3`           |
| Text-to-speech                    | `facebook/mms-tts-<lang>` (per target language) |

## How personalization actually works

- **Curriculum** (`curriculum.py`) defines a language-agnostic topic/skill
  tree across CEFR levels A1→C2 plus a "native polish" tier. The *content* for
  each topic is generated on demand by the chat model for the learner's
  specific language pair — so one curriculum serves every language, rather
  than hand-authored word lists per language.
- **Interests** the learner enters at onboarding are woven into example
  sentences and conversation small talk.
- **Mistakes** are tracked per vocabulary item (`vocab_progress` table, SM-2
  scheduling in `srs.py`); recently-missed items are surfaced both as spaced
  review and as material the next lesson's prompt explicitly re-practices.
- **Level-appropriate immersion**: A1 lessons never show a translation (image
  + audio + target text only, Rosetta Stone-style); translations appear from
  A2; free-form conversation exercises unlock at B1.

## Independence from ARIA

This directory is a self-contained product:

- Own `requirements.txt`, own `.env.example`, own `pytest.ini`.
- Own SQLite storage — no Supabase/Postgres dependency.
- Own FastAPI app (`backend/main.py`) and static frontend — does not import
  from, mount into, or modify `apps/core/main.py`, `apps/core/templates/app.html`,
  or `apps/core/templates/index.html` (ARIA's own hot files).
- Runs on its own port (`8100` by default) and can be deployed independently
  of ARIA's Docker/Fly/Vercel setup.
