"""Lingua — a standalone AI language-learning app (separate product from ARIA).

Combines Duolingo's gamified, adaptive skill-tree methodology with Rosetta
Stone's image/audio immersion approach, powered by Hugging Face models for
personalized exercise generation, illustrations, speech, and live spoken
conversation practice.

Run directly with:  python -m backend.main   (from language-app/)
or:                  uvicorn backend.main:app --reload --port 8100
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .config import settings
from .hf_client import hf_client
from .routers import auth as auth_router
from .routers import content, conversation, lessons, progress, users

logger = logging.getLogger("lingua.main")

_FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"


@asynccontextmanager
async def lifespan(app: FastAPI):
    redirect_uri = f"{settings.public_base_url}/auth/google/callback"
    if settings.google_configured:
        logger.info("Google Sign-In enabled. Redirect URI: %s", redirect_uri)
    else:
        logger.warning(
            "Google Sign-In not configured (GOOGLE_CLIENT_ID/SECRET unset). "
            "Register this exact redirect URI in Google Cloud Console once you set them: %s "
            "— dev-login fallback is %s.",
            redirect_uri,
            "enabled" if settings.dev_login_enabled else "disabled",
        )
    yield
    await hf_client.aclose()


app = FastAPI(title="Lingua — AI Language Coach", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router.router)
app.include_router(users.router)
app.include_router(lessons.router)
app.include_router(content.router)
app.include_router(progress.router)
app.include_router(conversation.router)


@app.get("/api/health")
def health() -> dict:
    return {
        "status": "ok",
        "hf_configured": settings.hf_configured,
        "google_configured": settings.google_configured,
    }


if _FRONTEND_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(_FRONTEND_DIR)), name="static")

    @app.get("/")
    def index() -> FileResponse:
        return FileResponse(str(_FRONTEND_DIR / "index.html"))


def main() -> None:
    uvicorn.run("backend.main:app", host=settings.host, port=settings.port, reload=False)


if __name__ == "__main__":
    main()
