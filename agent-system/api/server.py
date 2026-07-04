"""
ARIA Agent System — FastAPI Server.
Endpoints REST para gestión de tareas + WebSocket para streaming de logs.
"""
from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from core.config.settings import settings
from core.messaging.bus import MessageBus

logger = logging.getLogger("aria.api")

# ── Global message bus ────────────────────────────────────
bus = MessageBus()


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("ARIA Agent System API iniciando...")
    await bus.start()
    yield
    await bus.stop()
    logger.info("ARIA Agent System API deteniéndose...")


app = FastAPI(
    title="ARIA Agent System API",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
async def health():
    return {
        "status": "ok",
        "service": "aria-agent-system",
        "version": "0.1.0",
    }
