"""
ARIA Agent System — FastAPI Server completo.
Conecta: agents, tools, sandbox, vault, browser, DB, WebSocket.
"""
from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from api.routes import router as api_router
from api.websocket import router as ws_router
from agents.lifecycle import LifecycleManager
from core.config.settings import settings
from core.db.connection import close_db
from core.messaging.bus import MessageBus
from core.vault.client import VaultClient, get_vault_client
from sandbox.manager import SandboxManager
from browser.manager import BrowserManager
from tools.registry import ToolRegistry

logger = logging.getLogger("aria.api")

# ── Singletons globales ──────────────────────────────────
bus = MessageBus()
lifecycle = LifecycleManager(bus=bus)
sandbox = SandboxManager()
browser = BrowserManager()
tool_registry = ToolRegistry()
vault_client: VaultClient | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Ciclo de vida completo del servidor."""
    global vault_client

    logger.info("ARIA Agent System v0.2.0 iniciando...")

    # 1. Inicializar Vault
    try:
        vault_client = await get_vault_client()
        logger.info("Vault conectado")
    except Exception as e:
        logger.warning("Vault no disponible: %s", e)

    # 2. Inicializar Sandbox
    try:
        await sandbox.start()
        logger.info("SandboxManager iniciado")
    except Exception as e:
        logger.warning("Sandbox no disponible: %s", e)

    # 3. Inicializar Browser
    try:
        await browser.start()
        logger.info("BrowserManager iniciado")
    except Exception as e:
        logger.warning("Browser no disponible: %s", e)

    # 4. Inicializar Tool Registry
    await tool_registry.initialize(
        sandbox=sandbox if sandbox.active_containers >= 0 else None,
        vault=vault_client,
        browser_url="http://browser:9222",
    )
    logger.info("ToolRegistry: %d herramientas registradas", len(tool_registry.list_tools()))

    # 5. Iniciar LifecycleManager (que arranca bus + agentes)
    await lifecycle.start()
    logger.info("LifecycleManager iniciado con %d agentes", len(lifecycle.agents))

    logger.info("ARIA Agent System listo en puerto %d", settings.API_PORT)
    yield

    # ── Shutdown ──
    logger.info("ARIA Agent System deteniéndose...")
    await lifecycle.stop()
    await sandbox.stop()
    await browser.stop()
    await close_db()
    logger.info("ARIA Agent System detenido")


app = FastAPI(
    title="ARIA Agent System API",
    version="0.2.0",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Routers
app.include_router(api_router)
app.include_router(ws_router)


@app.get("/")
async def root():
    return {
        "service": "ARIA Agent System",
        "version": "0.2.0",
        "docs": "/docs",
        "health": "/health",
    }


@app.get("/health")
async def health():
    return {
        "status": "ok",
        "service": "aria-agent-system",
        "version": "0.2.0",
        "agents": lifecycle.stats,
        "tools": len(tool_registry.list_tools()),
        "sandbox": sandbox.stats if sandbox else {"status": "unavailable"},
        "browser": browser.stats if browser else {"status": "unavailable"},
    }