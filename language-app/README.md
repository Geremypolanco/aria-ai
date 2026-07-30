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
    config.py         env-based settings (HF_TOKEN, Google OAuth, model IDs, ports)
    auth.py              Google Sign-In + signed session/state cookies (no server-side store)
    models.py          Pydantic/enum domain models (CEFR levels, exercise types)
    db.py               SQLite persistence (stdlib sqlite3, zero extra deps)
    curriculum.py    language-agnostic skill tree + HF prompt templates
    srs.py               SM-2 spaced repetition + XP/streak/leveling logic
    hf_client.py      HF Inference API wrapper: chat, text-to-image, TTS, STT
    routers/             auth, users, lessons, content (media), progress, conversation (WebSocket)
  frontend/            vanilla HTML/CSS/JS SPA — no build step
  tests/                  pytest suite (SRS, curriculum, auth, and full API flow)
  fly.toml, Dockerfile     deploy config for Lingua's own Fly.io app/domain
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

### Google Sign-In setup

Lingua has its own Google OAuth client — **not shared with ARIA's own Google
login**. Create a dedicated one:

1. https://console.cloud.google.com/apis/credentials → **Create Credentials**
   → **OAuth client ID** → Application type **Web application**.
2. Under **Authorized redirect URIs**, add:

   ```
   https://lingua-ai-coach.fly.dev/auth/google/callback
   ```

   That's the exact value to register — it comes from the domain in
   `fly.toml` (see [Domain & deployment](#domain--deployment) below). If you
   deploy under a different Fly app name or a custom domain, use
   `https://<your-domain>/auth/google/callback` instead.

   Also add this one so sign-in works from a local dev server too:

   ```
   http://localhost:8100/auth/google/callback
   ```

3. Copy the generated **Client ID** and **Client secret** into `.env`:
   ```
   GOOGLE_CLIENT_ID=...
   GOOGLE_CLIENT_SECRET=...
   ```
4. Generate a session secret (required for sessions to survive a restart /
   work across more than one instance) and add it too:
   ```
   python -c "import secrets; print(secrets.token_hex(32))"
   ```

Without `GOOGLE_CLIENT_ID`/`GOOGLE_CLIENT_SECRET` set, the app automatically
falls back to a `/auth/dev-login?email=you@example.com` endpoint so you can
still sign in locally (and so the test suite doesn't need real Google
credentials). That fallback disables itself the moment real Google
credentials are configured, unless you explicitly opt back in with
`LINGUA_ALLOW_DEV_LOGIN=1` — a real deployment should never ship that on by
accident.

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

## Domain & deployment

Lingua deploys to **its own Fly.io app/domain**, entirely separate from
ARIA's `aria-ai.fly.dev`:

- `language-app/fly.toml` declares app `lingua-ai-coach` → **`lingua-ai-coach.fly.dev`**.
- `language-app/Dockerfile` is a standalone image built from this directory only.
- `.github/workflows/deploy-language-app.yml` deploys only when `language-app/`
  changes, using its own `FLY_API_TOKEN_LINGUA` secret (never ARIA's
  `FLY_API_TOKEN`), so it can't ever collide with or accidentally redeploy
  ARIA's app.

To ship it:

```bash
cd language-app
fly apps create lingua-ai-coach   # or pick another name — see fly.toml's header comment
fly volumes create lingua_data --size 1 --region ord   # persists SQLite across deploys
fly secrets set GOOGLE_CLIENT_ID=... GOOGLE_CLIENT_SECRET=... LINGUA_SESSION_SECRET=... HF_TOKEN=...
fly deploy
```

If you rename the Fly app or bring your own domain, update **both**
`LINGUA_PUBLIC_BASE_URL` (in `fly.toml`/secrets) **and** the redirect URI
registered in Google Cloud Console to match — they must always agree.

For CI-driven deploys, set these repo secrets: `FLY_API_TOKEN_LINGUA`,
`LINGUA_GOOGLE_CLIENT_ID`, `LINGUA_GOOGLE_CLIENT_SECRET`, `LINGUA_SESSION_SECRET`.

## Independence from ARIA

This directory is a self-contained product:

- Own `requirements.txt`, own `.env.example`, own `pytest.ini`.
- Own SQLite storage — no Supabase/Postgres dependency.
- Own FastAPI app (`backend/main.py`) and static frontend — does not import
  from, mount into, or modify `apps/core/main.py`, `apps/core/templates/app.html`,
  or `apps/core/templates/index.html` (ARIA's own hot files).
- Own Google OAuth client, own session cookies/secret, own domain (see
  [Domain & deployment](#domain--deployment)) — none of it shared with ARIA's
  own Google login or `aria-ai.fly.dev` deployment.
- Runs on its own port (`8100` by default) and deploys independently of
  ARIA's Docker/Fly/Vercel setup.
