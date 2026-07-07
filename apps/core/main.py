"""
ARIA AI — Autonomous Intelligence Platform.
Full-featured FastAPI server with AI integration, chat, and web interface.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
from contextlib import asynccontextmanager, suppress
from datetime import datetime

import uvicorn
from fastapi import FastAPI, Form, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, PlainTextResponse, RedirectResponse
from pydantic import BaseModel

from apps.core.config import settings

# ── ADMIN AUTH (server-side gate for the owner-only control panel) ─────────
_ADMIN_COOKIE = "aria_admin"


def _admin_token() -> str:
    """Deterministic session token derived from the admin password. An attacker who
    doesn't know ADMIN_PASSWORD cannot forge it."""
    pw = (getattr(settings, "ADMIN_PASSWORD", None) or "").encode()
    return hmac.new(pw or b"unset", b"aria-admin-session-v1", hashlib.sha256).hexdigest()


def _is_admin(request: Request) -> bool:
    if not getattr(settings, "ADMIN_PASSWORD", None):
        return False  # locked until an admin password is configured
    return hmac.compare_digest(request.cookies.get(_ADMIN_COOKIE, ""), _admin_token())


_LOGIN_HTML = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>ARIA · Admin</title><style>
*{{margin:0;box-sizing:border-box;font-family:system-ui,-apple-system,Segoe UI,Roboto,sans-serif}}
body{{min-height:100vh;display:flex;align-items:center;justify-content:center;
background:radial-gradient(120% 90% at 20% 10%,rgba(124,58,237,.35),transparent 45%),#0a0a0f;color:#f1f5f9}}
.card{{width:360px;max-width:92vw;background:rgba(17,17,24,.85);border:1px solid rgba(255,255,255,.1);
border-radius:18px;padding:36px 30px;box-shadow:0 30px 80px -20px rgba(0,0,0,.7)}}
h1{{font-size:22px;margin-bottom:6px}} p{{color:#94a3b8;font-size:14px;margin-bottom:22px}}
input{{width:100%;padding:13px 15px;border-radius:11px;border:1px solid rgba(255,255,255,.14);
background:rgba(255,255,255,.04);color:#fff;font-size:15px;margin-bottom:14px}}
button{{width:100%;padding:13px;border:0;border-radius:11px;font-weight:600;font-size:15px;cursor:pointer;
background:linear-gradient(92deg,#7c3aed,#2563eb);color:#fff}}
.err{{color:#fb7185;font-size:13px;margin-bottom:12px}} .mut{{color:#64748b;font-size:12px;margin-top:16px;text-align:center}}
</style></head><body><form class="card" method="post" action="/admin/login">
<h1>Control panel</h1><p>Admin access only.</p>
{error}<input type="password" name="password" placeholder="Admin password" autofocus required>
<button type="submit">Sign in</button>
<div class="mut">{notice}</div></form></body></html>"""

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


def _serve_control_panel() -> HTMLResponse:
    path = os.path.join(os.path.dirname(__file__), "templates", "dashboard.html")
    try:
        with open(path, encoding="utf-8") as f:
            return HTMLResponse(f.read())
    except FileNotFoundError:
        return HTMLResponse("<h1>Panel</h1><p>Not found</p>")


@app.get("/dashboard")
async def dashboard_redirect():
    # The control panel is now owner-only; old links land on the gate.
    return RedirectResponse("/admin", status_code=307)


@app.get("/admin/login", response_class=HTMLResponse)
async def admin_login_page():
    notice = (
        "ARIA · Autonomous Intelligence"
        if getattr(settings, "ADMIN_PASSWORD", None)
        else "⚠️ Set ADMIN_PASSWORD on the server to enable access."
    )
    return HTMLResponse(_LOGIN_HTML.format(error="", notice=notice))


@app.post("/admin/login")
async def admin_login(password: str = Form(...)):
    real = getattr(settings, "ADMIN_PASSWORD", None)
    if not real:
        return HTMLResponse(
            _LOGIN_HTML.format(
                error='<div class="err">Panel locked: set ADMIN_PASSWORD.</div>',
                notice="",
            ),
            status_code=403,
        )
    if not hmac.compare_digest(password, real):
        return HTMLResponse(
            _LOGIN_HTML.format(error='<div class="err">Incorrect password.</div>', notice=""),
            status_code=401,
        )
    resp = RedirectResponse("/admin", status_code=303)
    resp.set_cookie(
        _ADMIN_COOKIE,
        _admin_token(),
        httponly=True,
        secure=True,
        samesite="lax",
        max_age=60 * 60 * 24 * 7,
    )
    return resp


@app.get("/admin/logout")
async def admin_logout():
    resp = RedirectResponse("/admin/login", status_code=303)
    resp.delete_cookie(_ADMIN_COOKIE)
    return resp


@app.get("/admin")
async def admin_panel(request: Request):
    if not _is_admin(request):
        return RedirectResponse("/admin/login", status_code=307)
    return _serve_control_panel()


# ── PUBLIC SIGNUP (waitlist until user accounts + billing ship) ────────────
_SIGNUP_HTML = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>ARIA · Access</title><style>
*{{margin:0;box-sizing:border-box;font-family:system-ui,-apple-system,Segoe UI,Roboto,sans-serif}}
body{{min-height:100vh;display:flex;align-items:center;justify-content:center;
background:radial-gradient(120% 90% at 80% 10%,rgba(37,99,235,.30),transparent 45%),
radial-gradient(120% 90% at 10% 90%,rgba(124,58,237,.30),transparent 45%),#0a0a0f;color:#f1f5f9}}
.card{{width:420px;max-width:92vw;background:rgba(17,17,24,.85);border:1px solid rgba(255,255,255,.1);
border-radius:20px;padding:40px 34px;text-align:center;box-shadow:0 30px 80px -20px rgba(0,0,0,.7)}}
h1{{font-size:26px;margin-bottom:10px}} p{{color:#94a3b8;font-size:15px;margin-bottom:24px;line-height:1.5}}
input{{width:100%;padding:14px 16px;border-radius:12px;border:1px solid rgba(255,255,255,.14);
background:rgba(255,255,255,.04);color:#fff;font-size:15px;margin-bottom:14px}}
button{{width:100%;padding:14px;border:0;border-radius:12px;font-weight:600;font-size:15px;cursor:pointer;
background:linear-gradient(92deg,#7c3aed,#2563eb);color:#fff}} a{{color:#a78bfa;text-decoration:none}}
.mut{{color:#64748b;font-size:13px;margin-top:18px}}</style></head><body>
<form class="card" method="post" action="/signup">
<h1>{title}</h1><p>{sub}</p>{body}</form></body></html>"""


@app.get("/signup", response_class=HTMLResponse)
async def signup_page():
    body = (
        '<input type="email" name="email" placeholder="tu@email.com" required autofocus>'
        '<button type="submit">Join the access list</button>'
        '<div class="mut">Are you the admin? <a href="/admin/login">Open the panel</a></div>'
    )
    return HTMLResponse(
        _SIGNUP_HTML.format(
            title="Be first to use ARIA",
            sub="We're opening access in waves. Leave your email and we'll let you know when your plan is ready.",
            body=body,
        )
    )


@app.post("/signup", response_class=HTMLResponse)
async def signup_submit(email: str = Form(...)):
    with suppress(Exception):
        from apps.core.memory.redis_client import get_cache

        await get_cache().rpush("aria:waitlist", email.strip().lower())
    return HTMLResponse(
        _SIGNUP_HTML.format(
            title="You're in! 🎉",
            sub="You're on the list. We'll email you when your access is ready.",
            body='<a href="/" style="display:inline-block;margin-top:6px">← Back</a>',
        )
    )


# ── USER OAUTH LOGIN (Google / GitHub) → per-user dashboard ────────────────
@app.get("/login", response_class=HTMLResponse)
async def login_page():
    from apps.core import auth

    g = (
        '<a class="btn" href="/auth/google"><span>Continue with Google</span></a>'
        if auth.google_enabled()
        else ""
    )
    gh = (
        '<a class="btn gh" href="/auth/github"><span>Continue with GitHub</span></a>'
        if auth.github_enabled()
        else ""
    )
    body = g + gh or '<p style="color:#fb7185">Login not configured.</p>'
    html = f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>ARIA · Sign in</title><style>
*{{margin:0;box-sizing:border-box;font-family:system-ui,-apple-system,Segoe UI,Roboto,sans-serif}}
body{{min-height:100vh;display:flex;align-items:center;justify-content:center;
background:radial-gradient(120% 90% at 80% 10%,rgba(37,99,235,.28),transparent 45%),
radial-gradient(120% 90% at 10% 90%,rgba(124,58,237,.30),transparent 45%),#0a0a0f;color:#f1f5f9}}
.card{{width:400px;max-width:92vw;background:rgba(17,17,24,.85);border:1px solid rgba(255,255,255,.1);
border-radius:20px;padding:42px 34px;text-align:center;box-shadow:0 30px 80px -20px rgba(0,0,0,.7)}}
h1{{font-size:26px;margin-bottom:8px}} p{{color:#94a3b8;font-size:15px;margin-bottom:26px}}
.btn{{display:flex;align-items:center;justify-content:center;gap:10px;width:100%;padding:14px;
border-radius:12px;border:1px solid rgba(255,255,255,.16);background:rgba(255,255,255,.06);
color:#fff;text-decoration:none;font-weight:600;font-size:15px;margin-bottom:12px}}
.btn:hover{{background:rgba(255,255,255,.12)}} .btn.gh{{background:#161b22;border-color:#30363d}}
.mut{{color:#64748b;font-size:12px;margin-top:18px}} a.lnk{{color:#a78bfa;text-decoration:none}}
</style></head><body><div class="card"><h1>Sign in to ARIA</h1>
<p>Access your personal workspace.</p>{body}
<div class="mut">By continuing you agree to use ARIA responsibly. <a class="lnk" href="/">← Home</a></div>
</div></body></html>"""
    return HTMLResponse(html)


@app.get("/auth/google")
async def auth_google():
    from apps.core import auth

    url = auth.google_authorize_url()
    return RedirectResponse(url or "/login?e=google_off", status_code=307)


@app.get("/auth/github")
async def auth_github():
    from apps.core import auth

    url = auth.github_authorize_url()
    return RedirectResponse(url or "/login?e=github_off", status_code=307)


async def _finish_login(profile: dict | None):
    from apps.core import auth

    if not profile or not profile.get("email"):
        return RedirectResponse("/login?e=failed", status_code=303)
    await auth.remember_user(profile)
    resp = RedirectResponse("/app", status_code=303)
    resp.set_cookie(
        auth.USER_COOKIE,
        auth.sign_user(profile["email"], profile.get("name", ""), profile.get("provider", "")),
        httponly=True,
        secure=True,
        samesite="lax",
        max_age=60 * 60 * 24 * 30,
    )
    return resp


@app.get("/auth/google/callback")
async def auth_google_cb(request: Request):
    from apps.core import auth

    if not auth.check_state(request.query_params.get("state")):
        return RedirectResponse("/login?e=state", status_code=303)
    code = request.query_params.get("code")
    if not code:
        return RedirectResponse("/login?e=nocode", status_code=303)
    return await _finish_login(await auth.google_exchange(code))


@app.get("/auth/github/callback")
async def auth_github_cb(request: Request):
    from apps.core import auth

    if not auth.check_state(request.query_params.get("state")):
        return RedirectResponse("/login?e=state", status_code=303)
    code = request.query_params.get("code")
    if not code:
        return RedirectResponse("/login?e=nocode", status_code=303)
    return await _finish_login(await auth.github_exchange(code))


@app.get("/logout")
async def user_logout():
    from apps.core import auth

    resp = RedirectResponse("/", status_code=303)
    resp.delete_cookie(auth.USER_COOKIE)
    return resp


def _safe_name(s: str) -> str:
    """Sanitize an OAuth-provided display value for safe embedding in HTML/JS.
    Strips characters that could break out of an HTML attribute or JS string."""
    s = (s or "").strip()
    for ch in ('"', "'", "<", ">", "\\", "\n", "\r", "\t", "`"):
        s = s.replace(ch, "")
    return s[:40]


@app.get("/app", response_class=HTMLResponse)
async def user_app(request: Request):
    from apps.core import auth

    user = auth.verify_user(request.cookies.get(auth.USER_COOKIE))
    if not user:
        return RedirectResponse("/login", status_code=307)

    email = _safe_name(user.get("email", ""))
    name = _safe_name(user.get("name") or email.split("@")[0] or "there")
    first = name.split(" ")[0] if name else "there"
    initial = (first[:1] or "Y").upper()
    plan = "Free"

    path = os.path.join(os.path.dirname(__file__), "templates", "app.html")
    try:
        with open(path, encoding="utf-8") as f:
            html = f.read()
    except FileNotFoundError:
        return HTMLResponse(f"<h1>Hi {name}</h1><p>Workspace template missing.</p>")

    html = (
        html.replace("__NAME__", name)
        .replace("__FIRST__", first)
        .replace("__INITIAL__", initial)
        .replace("__EMAIL__", email)
        .replace("__PLAN__", plan)
    )
    return HTMLResponse(html)


# ── API ROUTES ────────────────────────────────────────────
@app.get("/health")
async def health():
    return {
        "status": "ok",
        "version": "3.0.0",
        "ts": datetime.utcnow().isoformat(),
        "env": settings.ENVIRONMENT,
    }


@app.get("/metrics")
async def prometheus_metrics():
    """Prometheus text-format metrics for scraping."""
    try:
        from apps.core.observability.metrics import get_metrics

        body = get_metrics().to_prometheus()
    except Exception:
        body = "# HELP aria_up ARIA process is up\n# TYPE aria_up gauge\naria_up 1\n"
    return PlainTextResponse(body, media_type="text/plain; version=0.0.4")


@app.get("/api/v1/metrics")
async def json_metrics():
    """Structured JSON metrics for the dashboard / API consumers."""
    try:
        from apps.core.observability.metrics import get_metrics

        return get_metrics().to_dict()
    except Exception as e:
        logger.warning(f"metrics to_dict failed: {e}")
        return {"requests_total": 0, "income": {}, "ai": {}}


@app.post("/api/v1/chat")
async def chat(req: ChatRequest):
    """Chat with ARIA — routed through the real cognitive brain (tools + identity),
    so it actually executes (e.g. generate_image) and knows who it is."""
    import base64
    import time

    start = time.time()
    try:
        from apps.core.cognition.aria_mind import get_aria_mind

        resp = await get_aria_mind().handle(req.message, req.session_id or "default")
        elapsed = int((time.time() - start) * 1000)
        media_type = None
        media_b64 = None
        if resp.image_bytes:
            media_type, media_b64 = "image", base64.b64encode(resp.image_bytes).decode()
        return {
            "reply": resp.text or resp.caption or "",
            "model_used": resp.tool_used or "aria",
            "processing_time_ms": elapsed,
            "media_type": media_type,
            "media_base64": media_b64,
        }
    except Exception as e:
        logger.error(f"Chat (aria_mind) error: {e}")
        # Fallback to the lightweight brain if the cognitive path errors (e.g. Redis quota).
        try:
            from apps.core.agent_brain import get_agent

            reply = await get_agent().think(req.message)
            return {"reply": reply, "model_used": "fallback", "processing_time_ms": 0}
        except Exception as e2:
            logger.error(f"Chat fallback error: {e2}")
            return {"reply": f"⚠️ Error: {e}", "model_used": "none", "processing_time_ms": 0}


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


class RunRequest(BaseModel):
    mission: str
    agent: str = "auto"
    use_pipeline: bool = True


@app.post("/api/v1/run")
async def run_mission(req: RunRequest):
    """Execute a mission using ARIA's execution engine."""
    import time

    start = time.time()
    try:
        from apps.core.execution_engine import get_executor

        executor = get_executor()
        result = await executor.execute(req.mission)
        elapsed = int((time.time() - start) * 1000)
        return {
            "success": result["success"],
            "result": {
                "summary": result["result"][:500] if result.get("result") else "",
                "understanding": (
                    result["understanding"][:300] if result.get("understanding") else ""
                ),
                "tool_plan": result.get("tool_plan", {}),
            },
            "processing_time_ms": elapsed,
        }
    except Exception as e:
        logger.error(f"Run error: {e}")
        return {"success": False, "error": str(e)}


@app.get("/api/v1/tools")
async def list_tools():
    """List all available tools."""
    from apps.core.tool_registry import TOOL_REGISTRY

    tools_by_cat = {}
    for tid, t in TOOL_REGISTRY.items():
        cat = t["category"]
        if cat not in tools_by_cat:
            tools_by_cat[cat] = []
        tools_by_cat[cat].append({"id": tid, "name": t["name"], "description": t["description"]})
    return {"tools": tools_by_cat, "count": len(TOOL_REGISTRY)}


# ── CONTENT OPERATOR (autonomous content-marketing wedge) ─────────────
class ContentOperateRequest(BaseModel):
    name: str = "SARAPH"
    product: str
    price: str | None = None
    audience: str | None = None
    url: str | None = None
    channels: list[str] | None = None
    dry_run: bool = False


@app.post("/api/v1/content/operate")
async def content_operate(req: ContentOperateRequest):
    """Run one autonomous content cycle: generate copy + image, optionally publish
    via Zapier MCP, and record a full observability trail. dry_run skips publishing."""
    try:
        from apps.core.tools.content_operator import get_content_operator

        brand = {
            "name": req.name,
            "product": req.product,
            "price": req.price,
            "audience": req.audience,
            "url": req.url,
        }
        return await get_content_operator().run_once(
            brand, channels=req.channels, dry_run=req.dry_run
        )
    except Exception as e:
        logger.error(f"Content operate error: {e}")
        return {"success": False, "error": str(e)}


@app.get("/api/v1/content/runs")
async def content_runs(limit: int = 20):
    """Return recent content-operator runs (the observability trail)."""
    try:
        from apps.core.tools.content_operator import get_content_operator

        runs = await get_content_operator().recent_runs(limit=limit)
        return {"count": len(runs), "runs": runs}
    except Exception as e:
        logger.error(f"Content runs error: {e}")
        return {"error": str(e)}


@app.get("/api/v1/content/selftest")
async def content_selftest():
    """Check that the Zapier MCP bridge is reachable and list available tools."""
    try:
        from apps.core.tools.zapier_mcp import get_zapier_mcp

        return await get_zapier_mcp().self_test()
    except Exception as e:
        logger.error(f"Content selftest error: {e}")
        return {"ok": False, "error": str(e)}


# ── WEBSOCKET ─────────────────────────────────────────────
@app.websocket("/ws/chat")
async def websocket_chat(ws: WebSocket):
    await ws.accept()
    try:
        from apps.core.cognition.aria_mind import get_aria_mind

        mind = get_aria_mind()
        while True:
            data = await ws.receive_text()
            msg = json.loads(data)
            resp = await mind.handle(msg.get("message", ""), msg.get("session_id", "ws"))
            await ws.send_json({"reply": resp.text or resp.caption or "", "tool": resp.tool_used})
    except WebSocketDisconnect:
        logger.info("WebSocket disconnected")
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
        with suppress(Exception):
            await ws.send_json({"error": str(e)})


# ── MAIN ──────────────────────────────────────────────────
if __name__ == "__main__":
    port = int(os.getenv("PORT", "8000"))
    uvicorn.run("apps.core.main:app", host="0.0.0.0", port=port, reload=False)
