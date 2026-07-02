"""
ARIA AI — Núcleo del Sistema Operativo.
FastAPI app con endpoints REST + WebSocket, dashboard, landing page y orquestación.
"""
from __future__ import annotations

import asyncio
import logging
import os
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Any

import uvicorn
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

# ── Config ────────────────────────────────────────────────
from apps.core.config import settings

logger = logging.getLogger("aria.core")

# ── LIFESPAN ──────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("🚀 ARIA AI iniciando...")
    # Startup tasks here
    yield
    logger.info("🛑 ARIA AI deteniéndose...")

# ── APP ───────────────────────────────────────────────────
app = FastAPI(
    title="ARIA AI — Autonomous Intelligence Platform",
    version="3.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── STATIC FILES (if any) ────────────────────────────────
static_dir = os.path.join(os.path.dirname(__file__), "static")
os.makedirs(static_dir, exist_ok=True)

# ── ROUTES ────────────────────────────────────────────────
@app.get("/", response_class=HTMLResponse)
async def root():
    """Landing page profesional."""
    template_path = os.path.join(os.path.dirname(__file__), "templates", "index.html")
    try:
        with open(template_path, encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        return HTMLResponse("<h1>ARIA AI</h1><p>Sistema en línea. Template no encontrado.</p>")

@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard():
    """Dashboard de control profesional."""
    template_path = os.path.join(os.path.dirname(__file__), "templates", "dashboard.html")
    try:
        with open(template_path, encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        return HTMLResponse("<h1>Dashboard</h1><p>Template no encontrado.</p>")

@app.get("/health")
async def health():
    return {
        "status": "ok",
        "version": "3.0.0",
        "timestamp": datetime.utcnow().isoformat(),
        "environment": settings.ENVIRONMENT,
    }

@app.get("/api/status")
async def api_status():
    """API status endpoint."""
    return {
        "aria": "running",
        "version": "3.0.0",
        "ts": datetime.utcnow().isoformat(),
        "agents": {"registered": 0},
        "scheduler": {"running": False, "jobs": []},
    }

# ── MAIN ──────────────────────────────────────────────────
if __name__ == "__main__":
    port = int(os.getenv("PORT", "8000"))
    logger.info(f"Starting ARIA AI on port {port}...")
    uvicorn.run("apps.core.main:app", host="0.0.0.0", port=port, reload=False)