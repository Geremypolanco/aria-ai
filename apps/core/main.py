"""
ARIA AI — Autonomous Intelligence Platform.
Full-featured FastAPI server with AI integration, chat, and web interface.
"""
from __future__ import annotations

import logging
import os
import json
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Any

import uvicorn
from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel

from apps.core.config import settings

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("aria")

# ── LIFESPAN ──────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("🚀 ARIA AI v3.0 starting...")
    # Warm up the AI client
    try:
        from apps.core.tools.ai_client import get_ai_client
        client = get_ai_client()
        if client:
            logger.info("✅ AI Client initialized")
    except Exception as e:
        logger.warning(f"⚠️ AI Client init: {e}")
    yield
    logger.info("🛑 ARIA AI shutting down...")

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

# ── MODELS ────────────────────────────────────────────────
class ChatRequest(BaseModel):
    message: str
    session_id: str = "default"

class ChatResponse(BaseModel):
    reply: str
    model_used: str = ""
    processing_time_ms: int = 0

# ── FRONTEND ROUTES ───────────────────────────────────────
@app.get("/", response_class=HTMLResponse)
async def root():
    path = os.path.join(os.path.dirname(__file__), "templates", "index.html")
    try:
        with open(path, encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        return HTMLResponse("<h1>ARIA AI</h1><p>Online</p>")

@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard():
    path = os.path.join(os.path.dirname(__file__), "templates", "dashboard.html")
    try:
        with open(path, encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        return HTMLResponse("<h1>Dashboard</h1><p>Not found</p>")

# ── API ROUTES ────────────────────────────────────────────
@app.get("/health")
async def health():
    return {
        "status": "ok",
        "version": "3.0.0",
        "ts": datetime.utcnow().isoformat(),
        "env": settings.ENVIRONMENT,
    }

@app.post("/api/v1/chat")
async def chat(req: ChatRequest):
    """Chat with ARIA AI."""
    import time
    start = time.time()
    try:
        from apps.core.agent_brain import get_agent
        agent = get_agent()
        reply = await agent.think(req.message)
        elapsed = int((time.time() - start) * 1000)
        return {
            "reply": reply,
            "model_used": "huggingface+groq",
            "processing_time_ms": elapsed,
        }
    except Exception as e:
        logger.error(f"Chat error: {e}")
        return {"reply": f"⚠️ Error: {str(e)}", "model_used": "none", "processing_time_ms": 0}

@app.post("/api/v1/code")
async def generate_code(req: ChatRequest):
    """Generate code with ARIA."""
    import time
    start = time.time()
    try:
        from apps.core.agent_brain import get_agent
        agent = get_agent()
        reply = await agent.generate_code(req.message)
        elapsed = int((time.time() - start) * 1000)
        return {"reply": reply, "processing_time_ms": elapsed}
    except Exception as e:
        return {"reply": f"Error: {e}"}

@app.post("/api/v1/research")
async def research(req: ChatRequest):
    """Research a topic with ARIA."""
    import time
    start = time.time()
    try:
        from apps.core.agent_brain import get_agent
        agent = get_agent()
        reply = await agent.research(req.message)
        elapsed = int((time.time() - start) * 1000)
        return {"reply": reply, "processing_time_ms": elapsed}
    except Exception as e:
        return {"reply": f"Error: {e}"}

@app.get("/api/v1/status")
async def api_status():
    """Full system status."""
    status = {"aria": "running", "version": "3.0.0", "ts": datetime.utcnow().isoformat()}
    try:
        from apps.core.tools.ai_client import get_ai_client
        client = get_ai_client()
        if client:
            status["ai"] = client.get_health_summary()
    except Exception as e:
        status["ai"] = {"error": str(e)}
    return status

# ── WEBSOCKET ─────────────────────────────────────────────
@app.websocket("/ws/chat")
async def websocket_chat(ws: WebSocket):
    await ws.accept()
    try:
        from apps.core.agent_brain import get_agent
        agent = get_agent()
        while True:
            data = await ws.receive_text()
            msg = json.loads(data)
            reply = await agent.think(msg.get("message", ""))
            await ws.send_json({"reply": reply})
    except WebSocketDisconnect:
        logger.info("WebSocket disconnected")
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
        try:
            await ws.send_json({"error": str(e)})
        except Exception:
            pass

# ── MAIN ──────────────────────────────────────────────────
if __name__ == "__main__":
    port = int(os.getenv("PORT", "8000"))
    uvicorn.run("apps.core.main:app", host="0.0.0.0", port=port, reload=False)