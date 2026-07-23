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
from fastapi.responses import (
    FileResponse,
    HTMLResponse,
    JSONResponse,
    PlainTextResponse,
    RedirectResponse,
    StreamingResponse,
)
from pydantic import BaseModel

from apps.core.config import settings

# ── ADMIN AUTH (server-side gate for the owner-only control panel) ─────────
_ADMIN_COOKIE = "aria_admin"

# The owner is admin automatically when signed in via OAuth with one of these
# emails (no separate password needed). Extra emails can be added via OWNER_EMAIL.
OWNER_EMAILS = {"geremypolancod@gmail.com"}


def _owner_emails() -> set[str]:
    emails = {e.lower() for e in OWNER_EMAILS}
    extra = (getattr(settings, "OWNER_EMAIL", "") or "").strip().lower()
    if extra:
        emails.add(extra)
    return emails


def _admin_token() -> str:
    """Deterministic session token derived from the admin password. An attacker who
    doesn't know ADMIN_PASSWORD cannot forge it."""
    pw = (getattr(settings, "ADMIN_PASSWORD", None) or "").encode()
    return hmac.new(pw or b"unset", b"aria-admin-session-v1", hashlib.sha256).hexdigest()


def _is_owner_user(request: Request) -> bool:
    """True when the visitor is signed in (Google/GitHub OAuth) as the owner."""
    try:
        from apps.core import auth

        u = auth.verify_user(request.cookies.get(auth.USER_COOKIE))
        email = ((u or {}).get("email") or "").strip().lower()
        return bool(email) and email in _owner_emails()
    except Exception:
        return False


def _is_admin(request: Request) -> bool:
    # The owner, signed in via OAuth, is always admin.
    if _is_owner_user(request):
        return True
    if not getattr(settings, "ADMIN_PASSWORD", None):
        return False  # locked until an admin password is configured
    return hmac.compare_digest(request.cookies.get(_ADMIN_COOKIE, ""), _admin_token())


def _current_user(request: Request) -> dict | None:
    """The signed-in user (verified session cookie), or None."""
    try:
        from apps.core import auth

        return auth.verify_user(request.cookies.get(auth.USER_COOKIE))
    except Exception:
        return None


# ── lightweight in-process rate limiter (no external dependency) ───────────
# Sliding-window per (client-ip, bucket). Protects expensive/public endpoints
# from abuse and cost blow-ups. For multi-instance deployments a shared store
# (Redis) would be stronger, but this bounds abuse on a single instance.
import time as _time  # noqa: E402
from collections import defaultdict, deque  # noqa: E402

_RATE_HITS: dict[str, deque] = defaultdict(deque)


def _client_ip(request: Request) -> str:
    fwd = request.headers.get("x-forwarded-for", "")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _rate_ok(request: Request, bucket: str, limit: int, window: float) -> bool:
    """Return True if this client is under `limit` requests in `window` seconds."""
    key = f"{bucket}:{_client_ip(request)}"
    now = _time.time()
    hits = _RATE_HITS[key]
    while hits and hits[0] <= now - window:
        hits.popleft()
    if len(hits) >= limit:
        return False
    hits.append(now)
    if len(_RATE_HITS) > 5000:  # crude memory cap
        for k in list(_RATE_HITS.keys())[:1000]:
            if not _RATE_HITS[k]:
                del _RATE_HITS[k]
    return True


def _json_for_script(obj) -> str:
    """json.dumps, but safe to embed inside an inline <script> — escapes the
    characters that could otherwise break out of the script context (XSS)."""
    out = json.dumps(obj)
    for a, b in (
        ("<", "\\u003c"),
        (">", "\\u003e"),
        ("&", "\\u0026"),
        ("\u2028", "\\u2028"),
        ("\u2029", "\\u2029"),
    ):
        out = out.replace(a, b)
    return out


# \u2500\u2500 Global Panic + AI burn-rate accounting \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
# Global "panic" freeze \u2014 flipped by the owner from the God Mode console to halt
# all user missions instantly. In-process (best-effort mirrored to cache).
_PANIC: dict[str, bool] = {"on": False}

# Conservative model used to *price* usage for the burn-rate cap. We may run on
# free/flat tiers, but the cap accounts against a paid-model rate to protect
# margin \u2014 the admin UI labels this "estimated".
_BILLING_MODEL = "claude-haiku-4-5"


async def _record_ai_cost(email: str, plan: str, prompt: str, reply: str) -> None:
    """Estimate + record the AI cost of a chat turn and enforce the burn cap."""
    if not email:
        return
    try:
        from apps.core.ops.cost_ledger import get_ledger, notify_burn_cap

        led = get_ledger()
        in_tokens = max(1, len(prompt) // 4)
        out_tokens = max(1, len(reply) // 4)
        led.record(email, _BILLING_MODEL, in_tokens, out_tokens)
        was_frozen = led.is_frozen(email)
        if led.evaluate(email, plan) and not was_frozen:
            frac = led.usage_fraction(email, plan)
            await notify_burn_cap(email, plan, frac)
            logger.info("[cost] burn-cap freeze for %s at %.0f%%", email, frac * 100)
    except Exception as exc:  # noqa: BLE001 \u2014 accounting must never break chat
        logger.debug("[cost] record failed: %s", exc)


def _log_workflow_run(
    email: str, goal: str, subtasks: list, tokens: int, duration_ms: int, ok: bool
) -> None:
    """Record a finished Deep Workflow for the user's usage panel (best-effort)."""
    with suppress(Exception):
        from apps.core.ops.workflow_ledger import get_workflow_ledger

        subs = subtasks or []
        get_workflow_ledger().record(
            email,
            goal=goal,
            subtasks=len(subs),
            verified=sum(1 for s in subs if s.get("verified")),
            repaired=sum(1 for s in subs if s.get("repaired")),
            tokens=tokens or 0,
            duration_ms=duration_ms or 0,
            ok=bool(ok),
        )


_LOGIN_HTML = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>ARIA · Admin</title><style>
*{{margin:0;box-sizing:border-box;font-family:system-ui,-apple-system,Segoe UI,Roboto,sans-serif}}
body{{min-height:100vh;display:flex;align-items:center;justify-content:center;
background:radial-gradient(120% 90% at 20% 10%,rgba(21,224,106,.10),transparent 45%),#ffffff;color:#0a0f0c}}
.card{{width:360px;max-width:92vw;background:#ffffff;border:1px solid #e5ece8;
border-radius:18px;padding:36px 30px;box-shadow:0 1px 2px rgba(10,20,15,.05),0 24px 60px -20px rgba(10,20,15,.18)}}
h1{{font-size:22px;margin-bottom:6px;color:#0a0f0c}} p{{color:#52605a;font-size:14px;margin-bottom:22px}}
input{{width:100%;padding:13px 15px;border-radius:11px;border:1px solid #d7e0da;
background:#fff;color:#0a0f0c;font-size:15px;margin-bottom:14px}}
input:focus{{outline:0;border-color:#9fe9c6;box-shadow:0 0 0 4px rgba(21,224,106,.14)}}
button{{width:100%;padding:13px;border:0;border-radius:11px;font-weight:700;font-size:15px;cursor:pointer;
background:#15E06A;color:#04150d;box-shadow:0 8px 24px -6px rgba(21,224,106,.45)}}
.err{{color:#e11d48;font-size:13px;margin-bottom:12px}} .mut{{color:#6b756f;font-size:12px;margin-top:16px;text-align:center}}
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
    logger.info("ARIA AI v3.0 starting...")
    # Warm up the AI client
    try:
        from apps.core.tools.ai_client import get_ai_client

        client = get_ai_client()
        if client:
            logger.info("AI Client initialized")
    except Exception as e:
        logger.warning(f"AI Client init: {e}")

    # Connector health semaphore — ping external APIs every 30 minutes so the
    # dashboard can hold queued posts when a platform is globally down.
    health_task = None

    async def _health_loop():
        import asyncio as _a

        from apps.core.ops.connector_health import CHECK_INTERVAL_SECONDS, check_all

        while True:
            try:
                await check_all()
            except Exception as exc:  # noqa: BLE001
                logger.debug("[health] loop check failed: %s", exc)
            await _a.sleep(CHECK_INTERVAL_SECONDS)

    try:
        import asyncio as _asyncio

        health_task = _asyncio.create_task(_health_loop())
    except Exception as e:  # noqa: BLE001
        logger.warning(f"health loop not started: {e}")

    # In-process mission worker — convenient for single-container dev. In
    # production run dedicated worker containers instead (see SCALE_ARCH.md) and
    # set ARIA_INPROCESS_WORKER=0. Enabled by default only when no REDIS_URL
    # (i.e. single-instance), so multi-container deploys don't double-process.
    worker_task = None
    worker_stop = None
    want_worker = os.environ.get(
        "ARIA_INPROCESS_WORKER", "1" if not getattr(settings, "REDIS_URL", None) else "0"
    ) not in ("0", "false", "False", "")
    if want_worker:
        try:
            import asyncio as _asyncio

            from apps.core.scale.worker import run_forever

            worker_stop = _asyncio.Event()
            worker_task = _asyncio.create_task(run_forever(stop=worker_stop))
            logger.info("🧵 in-process mission worker started")
        except Exception as e:  # noqa: BLE001
            logger.warning(f"in-process worker not started: {e}")

    yield

    if health_task is not None:
        health_task.cancel()
    if worker_stop is not None:
        worker_stop.set()
    if worker_task is not None:
        worker_task.cancel()
    logger.info("ARIA AI shutting down...")


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


@app.middleware("http")
async def _no_cache_html(request: Request, call_next):
    """Never cache HTML documents, so UI/design updates always reach the browser
    (mobile browsers were serving stale cached pages). Static assets/API are
    unaffected."""
    resp = await call_next(request)
    if resp.headers.get("content-type", "").startswith("text/html"):
        resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        resp.headers["Pragma"] = "no-cache"
    return resp


# ── Feature routers (modular) ─────────────────────────────────────
try:
    from apps.core.routes.clipper import router as clipper_router
    from apps.core.routes.missions import router as missions_router
    from apps.core.routes.voice_profile import router as voice_router
    from apps.core.webhooks.webhook_monitor_controller import router as webhook_router

    app.include_router(clipper_router)
    app.include_router(voice_router)
    app.include_router(webhook_router)
    app.include_router(missions_router)
except Exception as _exc:  # noqa: BLE001 — never let an optional router break boot
    logging.getLogger("aria").warning("feature routers not fully loaded: %s", _exc)


# ── MODELS ────────────────────────────────────────────────
class ChatRequest(BaseModel):
    message: str
    session_id: str = "default"
    persona: str | None = None  # team-member id → ARIA answers as that professional


class ChatResponse(BaseModel):
    reply: str
    model_used: str = ""
    processing_time_ms: int = 0


class SupportRequest(BaseModel):
    message: str
    session_id: str = "support"


class ProfileRequest(BaseModel):
    name: str = ""
    work: str = ""
    goals: list[str] = []
    plan: str = "free"


class ConnectorRequest(BaseModel):
    app: str = ""


# ── FRONTEND ROUTES ───────────────────────────────────────
_STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")


@app.get("/", response_class=HTMLResponse)
async def root():
    path = os.path.join(os.path.dirname(__file__), "templates", "index.html")
    try:
        with open(path, encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        return HTMLResponse("<h1>ARIA AI</h1><p>Online</p>")


@app.get("/og-cover.png")
async def og_cover():
    """Branded 1200x630 social-share card for link unfurls (Open Graph / Twitter)."""
    path = os.path.join(_STATIC_DIR, "og-cover.png")
    if not os.path.exists(path):
        return PlainTextResponse("not found", status_code=404)
    return FileResponse(
        path, media_type="image/png", headers={"Cache-Control": "public, max-age=86400"}
    )


@app.get("/favicon.svg")
async def favicon_svg():
    path = os.path.join(_STATIC_DIR, "favicon.svg")
    if not os.path.exists(path):
        return PlainTextResponse("not found", status_code=404)
    return FileResponse(
        path, media_type="image/svg+xml", headers={"Cache-Control": "public, max-age=604800"}
    )


@app.get("/aria-launch.webm")
async def aria_launch_video():
    """Short branded launch clip of ARIA running a mission (used for social/video)."""
    path = os.path.join(_STATIC_DIR, "aria-launch.webm")
    if not os.path.exists(path):
        return PlainTextResponse("not found", status_code=404)
    return FileResponse(
        path, media_type="video/webm", headers={"Cache-Control": "public, max-age=86400"}
    )


@app.get("/proof-hero.png")
async def proof_hero_image():
    """A real image ARIA generated on prod — used as proof in social posts."""
    path = os.path.join(_STATIC_DIR, "proof-hero.png")
    if not os.path.exists(path):
        return PlainTextResponse("not found", status_code=404)
    return FileResponse(
        path, media_type="image/png", headers={"Cache-Control": "public, max-age=86400"}
    )


@app.get("/api/v1/team")
async def api_team():
    """ARIA's team of AI professionals — a roster you can put to work."""
    from apps.core import team

    return {"team": team.public_team()}


@app.get("/team/{member_id}.png")
async def team_avatar(member_id: str):
    """Avatar for a team professional (generated by ARIA), served from static/team."""
    safe = "".join(c for c in member_id if c.isalnum())  # no path traversal
    path = os.path.join(_STATIC_DIR, "team", f"{safe}.png")
    if not os.path.exists(path):
        return PlainTextResponse("not found", status_code=404)
    return FileResponse(
        path, media_type="image/png", headers={"Cache-Control": "public, max-age=86400"}
    )


@app.get("/saraph", response_class=HTMLResponse)
async def saraph_page():
    """Official page for SARAPH — the AI studio behind ARIA."""
    path = os.path.join(os.path.dirname(__file__), "templates", "saraph.html")
    try:
        with open(path, encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        return HTMLResponse("<h1>SARAPH</h1><p>Maker of ARIA.</p>")


# ── LEGAL PAGES (required to launch a paid product) ────────
# Premium dark-mode legal pages live as styled HTML files under templates/legal/
# and are served at /legal/{terms,privacy,refund-policy}. Legacy short paths
# (/terms, /privacy, /refunds) 301-redirect to the canonical /legal/* URLs so
# there is a single source of truth.
_LEGAL_CONTACT = "litesaraph@gmail.com"

_LEGAL_FILES = {
    "terms": "terms.html",
    "privacy": "privacy.html",
    "refund-policy": "refund-policy.html",
}


def _serve_legal(slug: str) -> HTMLResponse:
    filename = _LEGAL_FILES.get(slug)
    if not filename:
        return HTMLResponse("<h1>Not found</h1>", status_code=404)
    path = os.path.join(os.path.dirname(__file__), "templates", "legal", filename)
    try:
        with open(path, encoding="utf-8") as f:
            return HTMLResponse(f.read())
    except FileNotFoundError:
        return HTMLResponse(
            f"<h1>ARIA · {slug.title()}</h1><p>Page unavailable.</p>", status_code=404
        )


@app.get("/legal", response_class=HTMLResponse)
async def legal_index():
    return RedirectResponse("/legal/terms", status_code=307)


@app.get("/legal/{slug}", response_class=HTMLResponse)
async def legal_page(slug: str):
    # Tolerate an optional .html suffix (/legal/terms.html).
    return _serve_legal(slug[:-5] if slug.endswith(".html") else slug)


# Backward-compatible redirects to the canonical /legal/* URLs.
@app.get("/terms")
async def terms():
    return RedirectResponse("/legal/terms", status_code=301)


@app.get("/privacy")
async def privacy():
    return RedirectResponse("/legal/privacy", status_code=301)


@app.get("/refunds")
async def refunds():
    return RedirectResponse("/legal/refund-policy", status_code=301)


def _serve_control_panel() -> HTMLResponse:
    # God Mode console; falls back to the legacy dashboard if the template is absent.
    for tpl in ("admin.html", "dashboard.html"):
        path = os.path.join(os.path.dirname(__file__), "templates", tpl)
        try:
            with open(path, encoding="utf-8") as f:
                return HTMLResponse(f.read())
        except FileNotFoundError:
            continue
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
        else "Set ADMIN_PASSWORD on the server to enable access."
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


# ── GOD MODE: data + operator actions ─────────────────────────────
async def _fly_instance_count() -> int | None:
    """Live Fly.io machine count for this app, or None if not configured."""
    token = os.environ.get("FLY_API_TOKEN") or getattr(settings, "FLY_API_TOKEN", None)
    app_name = os.environ.get("FLY_APP_NAME", "aria-ai")
    if not token:
        return None
    try:
        import httpx

        async with httpx.AsyncClient(timeout=8.0) as c:
            r = await c.get(
                f"https://api.machines.dev/v1/apps/{app_name}/machines",
                headers={"Authorization": f"Bearer {token}"},
            )
            if r.status_code == 200:
                return len([m for m in r.json() if m.get("state") == "started"])
    except Exception as exc:  # noqa: BLE001
        logger.debug("[admin] fly count failed: %s", exc)
    return None


async def _list_users() -> list[dict]:
    """Signed-up users recorded at login (best-effort; empty if none)."""
    users: list[dict] = []
    try:
        from apps.core.memory.redis_client import get_cache

        raw = await get_cache().lrange("aria:users", 0, 500)
        seen = set()
        for item in raw or []:
            try:
                u = json.loads(item)
            except Exception:
                continue
            em = (u.get("email") or "").strip().lower()
            if em and em not in seen:
                seen.add(em)
                users.append(
                    {"email": em, "name": u.get("name", ""), "provider": u.get("provider", "")}
                )
    except Exception as exc:  # noqa: BLE001
        logger.debug("[admin] list users failed: %s", exc)
    return users


@app.get("/admin/api/overview")
async def admin_overview(request: Request):
    """Real operational data for the God Mode console (admin-gated)."""
    if not _is_admin(request):
        return JSONResponse({"error": "forbidden"}, status_code=403)

    from apps.core.ops.connector_health import get_store
    from apps.core.ops.cost_ledger import get_ledger

    led = get_ledger()

    # Revenue (real, from metrics if tracked) vs estimated API spend.
    revenue = 0.0
    try:
        from apps.core.observability.metrics import get_metrics

        income = get_metrics().to_dict().get("income", {}) or {}
        revenue = float(income.get("revenue_usd", 0.0) or 0.0)
    except Exception:
        revenue = 0.0
    api_spend = round(sum(led._cost.values()), 2)  # month-to-date estimated

    users = await _list_users()
    return {
        "net_margin_usd": round(revenue - api_spend, 2),
        "revenue_usd": round(revenue, 2),
        "estimated_api_spend_usd": api_spend,
        "fly_instances": await _fly_instance_count(),  # None if FLY_API_TOKEN unset
        "users": users,
        "user_count": len(users),
        "frozen_users": led.frozen_users(),
        "connectors": get_store().get_all(),
        "panic": _PANIC["on"],
    }


@app.post("/admin/panic")
async def admin_panic(request: Request):
    """Global Panic Button — instantly freeze all user missions. Owner-only."""
    if not _is_owner_user(request):
        return JSONResponse({"error": "forbidden"}, status_code=403)
    _PANIC["on"] = True
    logger.warning("[admin] GLOBAL PANIC engaged by owner")
    return {"ok": True, "panic": True}


@app.post("/admin/unpanic")
async def admin_unpanic(request: Request):
    if not _is_owner_user(request):
        return JSONResponse({"error": "forbidden"}, status_code=403)
    _PANIC["on"] = False
    logger.warning("[admin] global panic released by owner")
    return {"ok": True, "panic": False}


_IMPERSONATOR_COOKIE = "aria_impersonator"


@app.post("/admin/impersonate")
async def admin_impersonate(request: Request, email: str = Form(...)):
    """Enter a user's dashboard for support. Owner-only. The real owner session
    is preserved in a signed cookie so it can be restored."""
    from apps.core import auth

    if not _is_owner_user(request):
        return JSONResponse({"error": "forbidden"}, status_code=403)
    target = _safe_name(email).strip().lower()
    if not target or "@" not in target:
        return JSONResponse({"error": "invalid email"}, status_code=400)
    owner = auth.verify_user(request.cookies.get(auth.USER_COOKIE)) or {}
    resp = RedirectResponse("/app", status_code=303)
    # Remember who we really are (signed) so /admin/stop-impersonate can restore.
    resp.set_cookie(
        _IMPERSONATOR_COOKIE,
        auth.sign_user(owner.get("email", ""), owner.get("name", ""), "owner"),
        httponly=True,
        secure=True,
        samesite="lax",
        max_age=60 * 60,
    )
    # Become the target user.
    resp.set_cookie(
        auth.USER_COOKIE,
        auth.sign_user(target, target.split("@")[0], "impersonated"),
        httponly=True,
        secure=True,
        samesite="lax",
        max_age=60 * 60,
    )
    logger.warning("[admin] owner impersonating %s", target)
    return resp


@app.get("/admin/stop-impersonate")
async def admin_stop_impersonate(request: Request):
    """Restore the owner session after impersonation."""
    from apps.core import auth

    orig = auth.verify_user(request.cookies.get(_IMPERSONATOR_COOKIE))
    resp = RedirectResponse("/admin", status_code=303)
    if orig and orig.get("email"):
        resp.set_cookie(
            auth.USER_COOKIE,
            auth.sign_user(orig["email"], orig.get("name", ""), "google"),
            httponly=True,
            secure=True,
            samesite="lax",
            max_age=60 * 60 * 24 * 30,
        )
    else:
        resp.delete_cookie(auth.USER_COOKIE)
    resp.delete_cookie(_IMPERSONATOR_COOKIE)
    return resp


@app.get("/api/v1/connectors/health")
async def connectors_health():
    """Connector health for the preventive banner. Refreshes lazily if stale
    (>30 min) so queued posts can be held when a platform is globally down."""
    import time as _t

    from apps.core.ops.connector_health import CHECK_INTERVAL_SECONDS, check_all, get_store

    store = get_store()
    statuses = store.get_all()
    newest = max((s.get("checked_at") or 0 for s in statuses.values()), default=0)
    if (_t.time() - newest) > CHECK_INTERVAL_SECONDS:
        try:
            statuses = await check_all(store=store)
        except Exception as exc:  # noqa: BLE001
            logger.debug("[health] refresh failed: %s", exc)
    return {"connectors": statuses, "offline": store.offline()}


# ── Real user accounts: email + password signup/login (+ OAuth) ────────────
def _esc_html(s: str) -> str:
    return (
        (s or "")
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


_ARIA_MARK = (
    '<svg width="38" height="38" viewBox="0 0 100 100" fill="none" aria-hidden="true">'
    '<defs><linearGradient id="am1" x1="26" y1="6" x2="70" y2="88" gradientUnits="userSpaceOnUse">'
    '<stop offset="0" stop-color="#5fe6c2"/><stop offset=".5" stop-color="#12b7a6"/>'
    '<stop offset="1" stop-color="#057a52"/></linearGradient></defs>'
    '<g stroke-linecap="round" stroke-linejoin="round" fill="none">'
    '<path d="M23 83 C 29 52, 40 28, 49 13 C 57 26, 64 36, 70 46" stroke="url(#am1)" stroke-width="12.5"/>'
    '<path d="M70 46 C 79 61, 74 79, 56 78 C 41 77, 39 58, 53 53 C 63 50, 70 50, 70 46 Z" '
    'stroke="url(#am1)" stroke-width="12.5"/></g></svg>'
)


def _auth_page(mode: str, error: str = "", email: str = "") -> str:
    """Shared signup/login page — real email accounts + optional OAuth buttons."""
    from apps.core import auth

    is_signup = mode == "signup"
    title = "Create your account" if is_signup else "Welcome back"
    sub = (
        "Start free — no card. You land in your workspace in seconds."
        if is_signup
        else "Sign in to your ARIA workspace."
    )
    action = "/signup" if is_signup else "/login"
    submit = "Create account & start" if is_signup else "Sign in"
    name_field = (
        '<input name="name" placeholder="Your name" autocomplete="name" required>'
        if is_signup
        else ""
    )
    pw_auto = "new-password" if is_signup else "current-password"
    pw_hint = ' minlength="8"' if is_signup else ""
    err = f'<div class="err">{_esc_html(error)}</div>' if error else ""
    ev = _esc_html(email)
    oauth = ""
    if auth.google_enabled():
        oauth += '<a class="btn" href="/auth/google">Continue with Google</a>'
    if auth.github_enabled():
        oauth += '<a class="btn gh" href="/auth/github">Continue with GitHub</a>'
    oauth_block = f'<div class="divider"><span>or</span></div>{oauth}' if oauth else ""
    switch = (
        'Already have an account? <a class="lnk" href="/login">Sign in</a>'
        if is_signup
        else 'New to ARIA? <a class="lnk" href="/signup">Create a free account</a>'
    )
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>ARIA · {title}</title>
<link rel="icon" href="/favicon.svg" type="image/svg+xml"><link rel="apple-touch-icon" href="/favicon.svg"><meta name="theme-color" content="#fafaf9"><style>
*{{margin:0;box-sizing:border-box;font-family:'Inter',system-ui,-apple-system,Segoe UI,Roboto,sans-serif}}
body{{min-height:100vh;display:flex;align-items:center;justify-content:center;padding:20px;
background:radial-gradient(120% 90% at 50% -10%,rgba(16,185,129,.14),transparent 55%),
radial-gradient(90% 70% at 90% 100%,rgba(245,158,11,.08),transparent 60%),#fafaf9;color:#1c1917}}
.card{{width:420px;max-width:100%;background:#fff;border:1px solid #e7e5e4;border-radius:22px;
padding:38px 32px;box-shadow:0 1px 2px rgba(28,25,23,.04),0 26px 64px -22px rgba(28,25,23,.16)}}
.brand{{display:flex;align-items:center;gap:11px;margin-bottom:22px}}
.brand .wm{{font-size:20px;font-weight:300;letter-spacing:.3em;padding-left:.3em}}
h1{{font-size:23px;margin-bottom:7px;letter-spacing:-.01em}} .sub{{color:#78716c;font-size:14.5px;margin-bottom:22px}}
label{{display:block;font-size:12px;font-weight:600;color:#44403c;margin:0 0 6px}}
input{{width:100%;padding:13px 15px;border-radius:12px;border:1px solid #d6d3d1;background:#fff;
color:#1c1917;font-size:15px;margin-bottom:14px;transition:border .15s,box-shadow .15s}}
input:focus{{outline:0;border-color:#a7f3d0;box-shadow:0 0 0 4px rgba(16,185,129,.14)}}
button{{width:100%;padding:14px;border:0;border-radius:12px;font-weight:700;font-size:15px;cursor:pointer;
background:#1c1917;color:#fff;box-shadow:0 8px 24px -6px rgba(28,25,23,.35);transition:transform .15s,box-shadow .15s,opacity .15s}}
button:hover{{transform:translateY(-1px);box-shadow:0 12px 28px -6px rgba(28,25,23,.4)}}
button:disabled{{opacity:.6;cursor:not-allowed;transform:none}}
.err{{background:#fef2f2;border:1px solid #fecaca;color:#b91c1c;font-size:13.5px;padding:10px 13px;
border-radius:11px;margin-bottom:16px}}
.divider{{display:flex;align-items:center;gap:12px;margin:18px 0;color:#a8a29e;font-size:12px}}
.divider::before,.divider::after{{content:"";flex:1;height:1px;background:#e7e5e4}}
.btn{{display:flex;align-items:center;justify-content:center;width:100%;padding:13px;border-radius:12px;
border:1px solid #d6d3d1;background:#fff;color:#1c1917;text-decoration:none;font-weight:600;
font-size:14.5px;margin-bottom:11px;transition:background .15s}}
.btn:hover{{background:#fafaf9}}
.switch{{text-align:center;font-size:14px;color:#57534e;margin-top:18px}}
.mut{{color:#a8a29e;font-size:11.5px;margin-top:16px;text-align:center;line-height:1.7}}
a.lnk{{color:#047857;text-decoration:none;font-weight:600}} a.lnk:hover{{text-decoration:underline}}
</style></head><body><div class="card">
<div class="brand">{_ARIA_MARK}<span class="wm">ARIA</span></div>
<h1>{title}</h1><p class="sub">{sub}</p>
{err}
<form method="post" action="{action}" autocomplete="on" onsubmit="var b=this.querySelector('button[type=submit]');b.disabled=true;b.textContent='Please wait…';">
{name_field}
<input type="email" name="email" placeholder="you@email.com" value="{ev}" autocomplete="email" required autofocus>
<input type="password" name="password" placeholder="Password" autocomplete="{pw_auto}"{pw_hint} required>
<button type="submit">{submit}</button>
</form>
{oauth_block}
<div class="switch">{switch}</div>
<div class="mut">By continuing you agree to our <a class="lnk" href="/legal/terms">Terms</a> &amp;
<a class="lnk" href="/legal/privacy">Privacy</a>. <a class="lnk" href="/">← Home</a></div>
</div></body></html>"""


def _auth_success_redirect(email: str, name: str, provider: str) -> RedirectResponse:
    from apps.core import auth

    resp = RedirectResponse("/app", status_code=303)
    resp.set_cookie(
        auth.USER_COOKIE,
        auth.sign_user(email, name, provider),
        httponly=True,
        secure=True,
        samesite="lax",
        max_age=60 * 60 * 24 * 30,
    )
    return resp


@app.get("/signup", response_class=HTMLResponse)
async def signup_page(request: Request):
    if _current_user(request):
        return RedirectResponse("/app", status_code=303)
    return HTMLResponse(_auth_page("signup"))


@app.post("/signup")
async def signup_submit(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    name: str = Form(""),
):
    if not _rate_ok(request, "signup", 10, 3600):
        return HTMLResponse(
            _auth_page("signup", "Too many attempts — please wait a minute.", email),
            status_code=429,
        )
    from apps.core import auth, auth_accounts

    ok, err = await auth_accounts.create_account(email, password, name)
    if not ok:
        return HTMLResponse(_auth_page("signup", err, email), status_code=400)
    with suppress(Exception):
        await auth.remember_user(
            {"email": email.strip().lower(), "name": name, "provider": "email"}
        )
    return _auth_success_redirect(email.strip().lower(), name.strip(), "email")


@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    if _current_user(request):
        return RedirectResponse("/app", status_code=303)
    return HTMLResponse(_auth_page("login"))


@app.post("/login")
async def login_submit(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
):
    if not _rate_ok(request, "login", 20, 900):
        return HTMLResponse(
            _auth_page("login", "Too many attempts — please wait a moment.", email),
            status_code=429,
        )
    from apps.core import auth_accounts

    profile = await auth_accounts.verify_credentials(email, password)
    if not profile:
        return HTMLResponse(_auth_page("login", "Wrong email or password.", email), status_code=401)
    return _auth_success_redirect(profile["email"], profile.get("name", ""), "email")


def _oauth_redirect(url: str | None, state: str, fallback: str) -> RedirectResponse:
    """Redirect to the provider, binding `state` to the browser via a cookie."""
    if not url:
        return RedirectResponse(fallback, status_code=307)
    resp = RedirectResponse(url, status_code=307)
    from apps.core import auth

    resp.set_cookie(
        auth.OAUTH_STATE_COOKIE,
        state,
        httponly=True,
        secure=True,
        samesite="lax",
        max_age=auth.STATE_MAX_AGE,
    )
    return resp


@app.get("/auth/google")
async def auth_google():
    from apps.core import auth

    state = auth.make_state()
    return _oauth_redirect(auth.google_authorize_url(state), state, "/login?e=google_off")


@app.get("/auth/github")
async def auth_github():
    from apps.core import auth

    state = auth.make_state()
    return _oauth_redirect(auth.github_authorize_url(state), state, "/login?e=github_off")


async def _finish_login(profile: dict | None):
    from apps.core import auth

    if not profile or not profile.get("email"):
        return RedirectResponse("/login?e=failed", status_code=303)
    await auth.remember_user(profile)
    resp = RedirectResponse("/app", status_code=303)
    resp.set_cookie(
        auth.USER_COOKIE,
        auth.sign_user(
            profile["email"],
            profile.get("name", ""),
            profile.get("provider", ""),
            profile.get("picture", ""),
        ),
        httponly=True,
        secure=True,
        samesite="lax",
        max_age=60 * 60 * 24 * 30,
    )
    return resp


@app.get("/auth/google/callback")
async def auth_google_cb(request: Request):
    from apps.core import auth

    cookie_state = request.cookies.get(auth.OAUTH_STATE_COOKIE)
    if not auth.check_state(request.query_params.get("state"), cookie_state):
        return RedirectResponse("/login?e=state", status_code=303)
    code = request.query_params.get("code")
    if not code:
        return RedirectResponse("/login?e=nocode", status_code=303)
    # Connector-link flow: Google/YouTube connectors reuse this callback. The
    # login path below is unchanged when the aria_glink cookie is absent.
    glink = request.cookies.get("aria_glink")
    if glink:
        from apps.core.connectors import oauth_hub as hub

        user = auth.verify_user(request.cookies.get(auth.USER_COOKIE))
        if not user:
            return RedirectResponse("/login", status_code=303)
        token = await auth.google_token_exchange(code) if glink in hub.PROVIDERS else None
        status = "connected"
        if not token or not token.get("access_token"):
            status = "error"
        else:
            email = (user.get("email") or "").strip().lower()
            await hub.save_token(email, glink, token)
        resp = RedirectResponse(f"/app?conn={glink}&s={status}", status_code=303)
        resp.delete_cookie(auth.OAUTH_STATE_COOKIE)
        resp.delete_cookie("aria_glink")
        return resp
    resp = await _finish_login(await auth.google_exchange(code))
    resp.delete_cookie(auth.OAUTH_STATE_COOKIE)
    return resp


@app.get("/auth/github/callback")
async def auth_github_cb(request: Request):
    from apps.core import auth

    cookie_state = request.cookies.get(auth.OAUTH_STATE_COOKIE)
    if not auth.check_state(request.query_params.get("state"), cookie_state):
        return RedirectResponse("/login?e=state", status_code=303)
    code = request.query_params.get("code")
    if not code:
        return RedirectResponse("/login?e=nocode", status_code=303)
    resp = await _finish_login(await auth.github_exchange(code))
    resp.delete_cookie(auth.OAUTH_STATE_COOKIE)
    return resp


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

    raw_email = (user.get("email") or "").strip().lower()
    profile = await _get_profile(raw_email)

    # Prefer the name the user chose during onboarding, else the OAuth name.
    chosen = profile.get("name") if profile else ""
    name = _safe_name(chosen or user.get("name") or raw_email.split("@")[0] or "there")
    email = _safe_name(user.get("email", ""))
    first = name.split(" ")[0] if name else "there"
    initial = (first[:1] or "Y").upper()
    # Real account photo (from Google/GitHub OAuth, carried in the signed cookie),
    # falling back to the initial. The URL is provider-issued and lives in an
    # HMAC-signed cookie; still require https + strip quotes/brackets defensively.
    picture = (user.get("picture") or "").strip()
    if picture.startswith("https://") and '"' not in picture and "<" not in picture:
        avatar_html = f'<img class="avimg" src="{picture}" alt="" referrerpolicy="no-referrer">'
    else:
        avatar_html = initial
    is_owner = raw_email in _owner_emails()
    plan_map = {"pro": "Pro", "business": "Business"}
    plan = "Business" if is_owner else plan_map.get(await _get_user_plan(raw_email), "Free")
    onboarded = "true" if (profile and profile.get("onboarded")) else "false"
    profile_json = _json_for_script(
        {
            "work": (profile.get("work", "") if profile else ""),
            "goals": (profile.get("goals", []) if profile else []),
        }
    )

    path = os.path.join(os.path.dirname(__file__), "templates", "app.html")
    try:
        with open(path, encoding="utf-8") as f:
            html = f.read()
    except FileNotFoundError:
        return HTMLResponse(f"<h1>Hi {name}</h1><p>Workspace template missing.</p>")

    # The admin link is rendered server-side ONLY for the owner — non-owners
    # never receive the markup at all (not merely CSS-hidden).
    admin_link = (
        '<a href="/admin" class="navlink">'
        '<svg viewBox="0 0 24 24" class="h-4 w-4" fill="none" stroke="currentColor" '
        'stroke-width="1.8"><path d="M12 3l7 3v6c0 4-3 7-7 9-4-2-7-5-7-9V6l7-3z"/></svg>'
        "Admin panel</a>"
        if is_owner
        else ""
    )

    html = (
        html.replace("__NAME__", name)
        .replace("__FIRST__", first)
        .replace("__AVATAR__", avatar_html)
        .replace("__INITIAL__", initial)
        .replace("__EMAIL__", email)
        .replace("__PLAN__", plan)
        .replace("__ONBOARDED__", onboarded)
        .replace("__PROFILE_JSON__", profile_json)
        .replace("__IS_OWNER__", "true" if is_owner else "false")
        .replace("__ADMIN_LINK__", admin_link)
    )
    return HTMLResponse(html)


# ── BILLING (Stripe Checkout, subscription) ───────────────
_PLAN_KEY = "aria:plan:{email}"

# Researched, margin-positive tiers (2026 market: entry premium ~$20, teams $25-30/seat).
# ARIA does more than chat (it also researches + publishes), so a slight premium holds.
BILLING_PLANS = {
    "pro": {"name": "ARIA Pro", "cents": 2900},  # $29 / month
    "business": {"name": "ARIA Business", "cents": 9900},  # $99 / month
}


async def _get_user_plan(email: str) -> str:
    if not email:
        return "free"
    try:
        from apps.core.memory.redis_client import get_cache

        val = await get_cache().get(_PLAN_KEY.format(email=email))
        return val if val in ("free", "pro", "business") else "free"
    except Exception:
        return "free"


async def _set_user_plan(email: str, plan: str) -> None:
    try:
        from apps.core.memory.redis_client import get_cache

        await get_cache().set(_PLAN_KEY.format(email=email), plan, ttl_seconds=45 * 24 * 3600)
    except Exception as e:
        logger.warning(f"set_user_plan failed: {e}")


# Free-plan daily message cap — the concrete reason to upgrade to Pro.
FREE_DAILY_LIMIT = 15


async def _consume_free_quota(email: str) -> tuple[bool, int]:
    """Count today's message for a Free user. Returns (allowed, remaining).
    Fails open (allowed) if the cache is unavailable."""
    try:
        from apps.core.memory.redis_client import get_cache

        cache = get_cache()
        key = f"aria:usage:{email}:{datetime.utcnow():%Y%m%d}"
        count = await cache.increment(key)
        if count == 1:
            await cache.expire(key, 2 * 24 * 3600)
        return (count <= FREE_DAILY_LIMIT, max(0, FREE_DAILY_LIMIT - count))
    except Exception:
        return (True, FREE_DAILY_LIMIT)


# ── USER PROFILE (onboarding + personalization) ───────────
async def _get_profile(email: str) -> dict:
    if not email:
        return {}
    try:
        from apps.core.memory.redis_client import get_cache

        val = await get_cache().get(f"aria:profile:{email}")
        if isinstance(val, dict):
            return val
        if isinstance(val, str) and val:
            return json.loads(val)
    except Exception:
        pass
    return {}


async def _save_profile(email: str, data: dict) -> None:
    try:
        from apps.core.memory.redis_client import get_cache

        await get_cache().set(f"aria:profile:{email}", data, ttl_seconds=365 * 24 * 3600)
    except Exception as e:
        logger.warning(f"save_profile failed: {e}")


def _profile_context(profile: dict) -> str:
    """A concise personalization note fed to ARIA so it addresses the user by
    name and tailors help to their work and goals."""
    if not profile:
        return ""
    parts = []
    if profile.get("name"):
        parts.append(f"su nombre es {profile['name']}")
    if profile.get("work"):
        parts.append(f"se dedica a: {profile['work']}")
    if profile.get("goals"):
        parts.append("quiere ayuda con: " + ", ".join(profile["goals"][:6]))
    if not parts:
        return ""
    return (
        "[Perfil del usuario — personaliza tu respuesta y, cuando sea natural, "
        "dirígete a él por su nombre: " + "; ".join(parts) + ".]"
    )


# Mandatory pre-checkout acknowledgement (strict no-refund policy). Every path
# to Stripe passes through this gate — the modal sends agreed=1 inline; direct
# links (onboarding, deep-links) are stopped here and shown the interstitial.
NO_REFUND_ACK = (
    "Entiendo y acepto la política estricta de no reembolso de ARIA debido a los "
    "costes inmediatos de renderizado y cómputo de IA."
)


def _checkout_confirm_page(tier: str, plan: dict) -> HTMLResponse:
    price = f"${plan['cents'] // 100}/mo"
    go = f"/billing/checkout?tier={tier}&amp;agreed=1"
    html = f"""<!doctype html><html lang="es"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>ARIA · Confirmar {plan['name']}</title><style>
*{{margin:0;box-sizing:border-box;font-family:system-ui,-apple-system,Segoe UI,Roboto,sans-serif}}
body{{min-height:100vh;display:flex;align-items:center;justify-content:center;
background:#ffffff;color:#3f3f46;padding:20px}}
.card{{width:460px;max-width:94vw;background:#ffffff;border:1px solid #e4e4e7;border-radius:18px;
padding:32px 28px;box-shadow:0 1px 2px rgba(24,24,27,.04),0 24px 60px -20px rgba(24,24,27,.15)}}
h1{{font-size:22px;margin-bottom:4px;color:#18181b}} .price{{color:#52525b;font-size:14px;margin-bottom:22px}}
.price b{{color:#18181b}}
.ack{{display:flex;gap:12px;align-items:flex-start;background:#f3f8f5;border:1px solid #e5ece8;
border-radius:12px;padding:14px 14px;margin-bottom:20px}}
.ack input{{margin-top:3px;width:18px;height:18px;accent-color:#15E06A;flex:0 0 auto;cursor:pointer}}
.ack label{{font-size:13.5px;line-height:1.55;color:#3f4a44;cursor:pointer}}
.btn{{display:block;width:100%;text-align:center;padding:13px;border-radius:12px;border:0;
background:#15E06A;color:#04150d;font-weight:700;font-size:15px;box-shadow:0 8px 24px -6px rgba(21,224,106,.45);
text-decoration:none;cursor:pointer;transition:filter .15s}}
.btn[aria-disabled="true"]{{opacity:.4;pointer-events:none}}
.sub{{text-align:center;margin-top:14px;font-size:12.5px}}
.sub a{{color:#71717a;text-decoration:none;margin:0 8px}} .sub a:hover{{color:#18181b}}
</style></head><body><div class="card">
<h1>Confirmar {plan['name']}</h1>
<div class="price"><b>{price}</b> · renovación mensual · cancela cuando quieras</div>
<div class="ack">
  <input type="checkbox" id="ack" onchange="document.getElementById('go').setAttribute('aria-disabled', this.checked?'false':'true')">
  <label for="ack">{NO_REFUND_ACK}</label>
</div>
<a id="go" class="btn" aria-disabled="true" href="{go}">Continuar al pago seguro →</a>
<div class="sub"><a href="/app">← Volver</a><a href="/legal/refund-policy">Política de reembolso</a>
<a href="/legal/terms">Términos</a></div>
</div></body></html>"""
    return HTMLResponse(html)


@app.get("/billing/checkout")
async def billing_checkout(request: Request, tier: str = "pro", agreed: str = ""):
    """Start a Stripe Checkout session for the given ARIA subscription tier.

    Gated by a mandatory strict-no-refund acknowledgement: without `agreed=1`
    we render the confirmation interstitial instead of creating the session."""
    from apps.core import auth

    user = auth.verify_user(request.cookies.get(auth.USER_COOKIE))
    if not user:
        return RedirectResponse("/login", status_code=307)

    tier = tier if tier in BILLING_PLANS else "pro"
    plan = BILLING_PLANS[tier]

    # Enforce the no-refund acknowledgement before any charge can start.
    if agreed.lower() not in ("1", "true", "yes", "on"):
        return _checkout_confirm_page(tier, plan)

    key = getattr(settings, "STRIPE_SECRET_KEY", None)
    if not key:
        # Billing not configured yet — send the user back with a clear flag.
        return RedirectResponse("/app?billing=unavailable", status_code=303)

    email = (user.get("email") or "").strip().lower()
    base = (getattr(settings, "ARIA_BASE_URL", None) or "https://aria-ai.fly.dev").rstrip("/")
    tier_key = tier if tier in BILLING_PLANS else "pro"
    try:
        import stripe

        stripe.api_key = key
        session = stripe.checkout.Session.create(
            mode="subscription",
            customer_email=email or None,
            line_items=[
                {
                    "quantity": 1,
                    "price_data": {
                        "currency": "usd",
                        "unit_amount": plan["cents"],
                        "recurring": {"interval": "month"},
                        "product_data": {"name": plan["name"]},
                    },
                }
            ],
            allow_promotion_codes=True,
            success_url=base + "/billing/success?session_id={CHECKOUT_SESSION_ID}",
            cancel_url=base + "/app?billing=cancel",
            metadata={"email": email, "tier": tier_key},
        )
        return RedirectResponse(session.url, status_code=303)
    except Exception as e:
        logger.error(f"Stripe checkout error: {e}")
        return RedirectResponse("/app?billing=error", status_code=303)


@app.get("/billing/success")
async def billing_success(request: Request, session_id: str = ""):
    """Verify the completed Checkout session server-side, then mark the user Pro."""
    from apps.core import auth

    user = auth.verify_user(request.cookies.get(auth.USER_COOKIE))
    key = getattr(settings, "STRIPE_SECRET_KEY", None)
    if user and key and session_id:
        try:
            import stripe

            stripe.api_key = key
            s = stripe.checkout.Session.retrieve(session_id)
            paid = s.get("payment_status") == "paid" or s.get("status") == "complete"
            email = (user.get("email") or "").strip().lower()
            tier = (s.get("metadata") or {}).get("tier", "pro")
            if tier not in BILLING_PLANS:
                tier = "pro"
            if paid and email:
                await _set_user_plan(email, tier)
        except Exception as e:
            logger.error(f"Stripe verify error: {e}")
    return RedirectResponse("/app?billing=success", status_code=303)


@app.post("/api/v1/profile")
async def save_onboarding_profile(req: ProfileRequest, request: Request):
    """Persist the first-login onboarding answers used to personalize ARIA."""
    from apps.core import auth

    user = auth.verify_user(request.cookies.get(auth.USER_COOKIE))
    if not user:
        return {"ok": False, "error": "unauthenticated"}
    email = (user.get("email") or "").strip().lower()
    data = {
        "name": _safe_name(req.name)[:60] or (user.get("name") or ""),
        "work": _safe_name(req.work)[:60],
        "goals": [_safe_name(g)[:40] for g in (req.goals or []) if g][:8],
        "plan": req.plan if req.plan in ("free", "pro", "business") else "free",
        "onboarded": True,
    }
    await _save_profile(email, data)
    return {"ok": True}


@app.post("/api/v1/connectors/request")
async def request_connector(req: ConnectorRequest, request: Request):
    """Record a user's request to connect an external app (connectors waitlist)."""
    from apps.core import auth

    user = auth.verify_user(request.cookies.get(auth.USER_COOKIE))
    email = (user.get("email") or "").strip().lower() if user else "anon"
    app_id = _safe_name(req.app)[:40]
    if not app_id:
        return {"ok": False, "error": "missing app"}
    try:
        from apps.core.memory.redis_client import get_cache

        await get_cache().rpush(
            "aria:connector_requests", json.dumps({"email": email, "app": app_id})
        )
    except Exception as e:
        logger.warning(f"connector request failed: {e}")
    return {"ok": True}


# ── CONNECTOR HUB — real one-click OAuth connect (like Claude's connectors) ──
@app.get("/api/v1/connectors/status")
async def connectors_status(request: Request):
    """Per-connector state for the signed-in user: connected / ready / setup."""
    from apps.core import auth
    from apps.core.connectors import oauth_hub as hub

    user = auth.verify_user(request.cookies.get(auth.USER_COOKIE))
    email = (user.get("email") or "").strip().lower() if user else ""
    return {"connectors": await hub.status_for(email)}


@app.get("/connectors/{pid}/connect")
async def connector_connect(pid: str, request: Request):
    """Kick off the real OAuth consent flow for a provider."""
    from apps.core import auth
    from apps.core.connectors import oauth_hub as hub

    user = auth.verify_user(request.cookies.get(auth.USER_COOKIE))
    if not user:
        return RedirectResponse("/login", status_code=307)
    p = hub.PROVIDERS.get(pid)
    if not p:
        return RedirectResponse("/app?conn=unknown&s=error", status_code=303)
    # Not configured, or a non-redirect provider (shopify per-store / zapier key).
    if p.special or not hub.is_configured(pid):
        return RedirectResponse(f"/app?conn={pid}&s=setup", status_code=303)
    # Google-based connectors reuse the already-registered login callback
    # (/auth/google/callback) so the owner needn't register a separate connector
    # redirect URI — this is what caused the "redirect_uri_mismatch" errors.
    if pid in ("google", "youtube") and auth.google_enabled():
        gstate = auth.make_state()
        gurl = auth.google_connector_authorize_url(gstate, p.scope)
        if gurl:
            resp = RedirectResponse(gurl, status_code=307)
            resp.set_cookie(
                auth.OAUTH_STATE_COOKIE,
                gstate,
                httponly=True,
                secure=True,
                samesite="lax",
                max_age=600,
            )
            resp.set_cookie(
                "aria_glink",
                pid,
                httponly=True,
                secure=True,
                samesite="lax",
                max_age=600,
            )
            return resp
    state = auth.make_state()
    url, verifier = hub.build_authorize(pid, state)
    resp = RedirectResponse(url, status_code=307)
    resp.set_cookie(
        hub.STATE_COOKIE,
        f"{pid}|{state}|{verifier}",
        httponly=True,
        secure=True,
        samesite="lax",
        max_age=600,
    )
    return resp


@app.get("/connectors/{pid}/callback")
async def connector_callback(
    pid: str, request: Request, code: str = "", state: str = "", error: str = ""
):
    """Handle the provider redirect: verify state, exchange code, store token."""
    from apps.core import auth
    from apps.core.connectors import oauth_hub as hub

    user = auth.verify_user(request.cookies.get(auth.USER_COOKIE))
    if not user:
        return RedirectResponse("/login", status_code=307)
    if error or not code or pid not in hub.PROVIDERS:
        return RedirectResponse(f"/app?conn={pid}&s=error", status_code=303)
    cookie = request.cookies.get(hub.STATE_COOKIE, "")
    try:
        c_pid, c_state, verifier = cookie.split("|", 2)
    except ValueError:
        return RedirectResponse(f"/app?conn={pid}&s=error", status_code=303)
    if c_pid != pid or not auth.check_state(state, c_state):
        return RedirectResponse(f"/app?conn={pid}&s=error", status_code=303)
    token = await hub.exchange_code(pid, code, verifier)
    if not token or not token.get("access_token"):
        return RedirectResponse(f"/app?conn={pid}&s=error", status_code=303)
    email = (user.get("email") or "").strip().lower()
    await hub.save_token(email, pid, token)
    resp = RedirectResponse(f"/app?conn={pid}&s=connected", status_code=303)
    resp.delete_cookie(hub.STATE_COOKIE)
    return resp


@app.post("/api/v1/connectors/{pid}/disconnect")
async def connector_disconnect(pid: str, request: Request):
    """Remove a stored connector token for the signed-in user."""
    from apps.core import auth
    from apps.core.connectors import oauth_hub as hub

    user = auth.verify_user(request.cookies.get(auth.USER_COOKIE))
    if not user:
        return {"ok": False, "error": "unauthenticated"}
    email = (user.get("email") or "").strip().lower()
    await hub.disconnect(email, pid)
    return {"ok": True}


@app.post("/api/v1/account/delete")
async def delete_account(request: Request):
    """Delete the signed-in user's stored data (profile + plan) and sign out."""
    from apps.core import auth

    user = auth.verify_user(request.cookies.get(auth.USER_COOKIE))
    if not user:
        return {"ok": False, "error": "unauthenticated"}
    email = (user.get("email") or "").strip().lower()
    try:
        from apps.core.memory.redis_client import get_cache

        cache = get_cache()
        for key in (f"aria:profile:{email}", _PLAN_KEY.format(email=email)):
            with suppress(Exception):
                await cache.delete(key)
    except Exception as e:
        logger.warning(f"delete_account failed: {e}")
    resp = JSONResponse({"ok": True})
    resp.delete_cookie(auth.USER_COOKIE)
    return resp


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
async def chat(req: ChatRequest, request: Request):
    """Chat with ARIA — routed through the real cognitive brain (tools + identity),
    so it actually executes (e.g. generate_image) and knows who it is."""
    import base64
    import time

    start = time.time()

    # Rate limit + require sign-in (prevents anonymous/abusive LLM cost).
    if not _rate_ok(request, "chat", 30, 60):
        return {
            "reply": "You're sending messages too fast. Please wait a moment and try again.",
            "model_used": "ratelimited",
            "processing_time_ms": 0,
            "media_type": None,
            "media_base64": None,
        }
    if not _current_user(request):
        return {
            "reply": "Please sign in to use ARIA.",
            "model_used": "auth",
            "processing_time_ms": 0,
            "media_type": None,
            "media_base64": None,
        }

    # Personalize + enforce plan limits from the signed-in user.
    user_context = ""
    email = ""
    plan = "free"
    try:
        from apps.core import auth

        u = auth.verify_user(request.cookies.get(auth.USER_COOKIE))
        if u:
            email = (u.get("email") or "").strip().lower()
            user_context = _profile_context(await _get_profile(email))
            plan = "business" if email in _owner_emails() else await _get_user_plan(email)
    except Exception:
        user_context = ""

    # Free plan has a daily message cap — the reason to upgrade to Pro.
    if email and plan == "free":
        allowed, remaining = await _consume_free_quota(email)
        if not allowed:
            return {
                "reply": (
                    f"You've reached today's free limit of {FREE_DAILY_LIMIT} messages.\n\n"
                    "Upgrade to **Pro** for **unlimited** ARIA — unlimited chat, images, "
                    "video & voice, and autonomous multi-channel publishing.\n\n"
                    "Open the menu → **Upgrade**, or continue tomorrow when your free "
                    "messages reset."
                ),
                "model_used": "limit",
                "processing_time_ms": 0,
                "media_type": None,
                "media_base64": None,
            }

    # Global panic freeze + AI burn-rate cap (paid plans frozen over budget).
    if _PANIC["on"]:
        return {
            "reply": "ARIA is temporarily paused by an operator. Please try again shortly.",
            "model_used": "paused",
            "processing_time_ms": 0,
            "media_type": None,
            "media_base64": None,
        }
    if email and plan in ("pro", "business"):
        from apps.core.ops.cost_ledger import get_ledger

        if get_ledger().is_frozen(email):
            return {
                "reply": (
                    "You've reached this month's AI usage cap for your plan, so new "
                    "missions are paused to protect your account. Upgrade for more "
                    "capacity, or your allowance resets at the start of next month."
                ),
                "model_used": "burn_cap",
                "processing_time_ms": 0,
                "media_type": None,
                "media_base64": None,
            }

    # If a team professional is selected, prepend their persona so ARIA works as them.
    if req.persona:
        from apps.core import team as _team

        pctx = _team.persona_context(req.persona)
        if pctx:
            user_context = f"{pctx}\n\n{user_context}".strip()

    try:
        from apps.core.cognition.aria_mind import get_aria_mind

        resp = await get_aria_mind().handle(
            req.message, req.session_id or "default", user_context=user_context or None
        )
        elapsed = int((time.time() - start) * 1000)
        media_type = None
        media_b64 = None
        if resp.image_bytes:
            media_type, media_b64 = "image", base64.b64encode(resp.image_bytes).decode()
        reply_text = resp.text or resp.caption or ""
        await _record_ai_cost(email, plan, req.message, reply_text)
        return {
            "reply": reply_text,
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
            return {"reply": f"Error: {e}", "model_used": "none", "processing_time_ms": 0}


@app.post("/api/v1/support/chat")
async def support_chat(req: SupportRequest, request: Request):
    """ARIA Support — the autonomous 24/7 assistant behind the support widget.

    A fast Claude sub-agent (Haiku) with a strict support system prompt when an
    API key is configured; an honest offline FAQ responder otherwise so support
    works with no token budget. Kept separate from /api/v1/chat so the main
    cognitive brain and its plan limits are untouched.
    """
    import time

    start = time.time()

    if not _rate_ok(request, "support", 20, 60):
        return {
            "reply": "Estás enviando mensajes muy rápido. Espera un momento e inténtalo de nuevo.",
            "source": "ratelimited",
            "processing_time_ms": 0,
        }
    if not _current_user(request):
        return {
            "reply": "Inicia sesión para hablar con ARIA Support.",
            "source": "auth",
            "processing_time_ms": 0,
        }

    from apps.core.support.support_agent import answer

    api_key = getattr(settings, "ANTHROPIC_API_KEY", None)
    try:
        reply, source = await answer(req.message, api_key=api_key)
    except Exception as e:  # noqa: BLE001 — the widget must never hard-error.
        logger.error(f"Support chat error: {e}")
        from apps.core.support.support_agent import offline_answer

        reply, source = offline_answer(req.message or ""), "offline_error"

    return {
        "reply": reply,
        "source": source,
        "processing_time_ms": int((time.time() - start) * 1000),
    }


@app.post("/api/v1/code")
async def generate_code(req: ChatRequest, request: Request):
    """Generate code with ARIA."""
    import time

    if not _current_user(request):
        return {"reply": "Please sign in to use this endpoint.", "unauthorized": True}
    if not _rate_ok(request, "code", 20, 60):
        return {"reply": "Rate limit reached — please slow down.", "ratelimited": True}
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
async def research(req: ChatRequest, request: Request):
    """Research a topic with ARIA."""
    import time

    if not _current_user(request):
        return {"reply": "Please sign in to use this endpoint.", "unauthorized": True}
    if not _rate_ok(request, "research", 20, 60):
        return {"reply": "Rate limit reached — please slow down.", "ratelimited": True}
    start = time.time()
    try:
        from apps.core.agent_brain import get_agent

        agent = get_agent()
        reply = await agent.research(req.message)
        elapsed = int((time.time() - start) * 1000)
        return {"reply": reply, "processing_time_ms": elapsed}
    except Exception as e:
        return {"reply": f"Error: {e}"}


class WorkflowRequest(BaseModel):
    goal: str
    context: str | None = None


@app.post("/api/v1/workflow")
async def dynamic_workflow(req: WorkflowRequest, request: Request):
    """ARIA Dynamic Workflows — el patrón insignia de las IA frontera 2026.

    Descompone un objetivo en subtareas, ejecuta subagentes en paralelo enrutando
    cada uno al modelo óptimo, verifica cada resultado de forma adversarial y
    sintetiza la entrega final. Requiere sesión; es costoso, así que va con un
    límite de tasa más estricto y respeta el freeze global y el tope de gasto.
    """
    import time

    start = time.time()

    if not _current_user(request):
        return JSONResponse(
            {"ok": False, "error": "auth", "synthesis": "Inicia sesión para usar ARIA."},
            status_code=401,
        )
    # Los flujos abren varios subagentes por llamada → límite deliberadamente bajo.
    if not _rate_ok(request, "workflow", 6, 300):
        return JSONResponse(
            {"ok": False, "error": "rate_limited", "synthesis": "Demasiados flujos seguidos."},
            status_code=429,
        )
    if _PANIC["on"]:
        return JSONResponse(
            {"ok": False, "error": "paused", "synthesis": "ARIA está pausada por un operador."},
            status_code=503,
        )

    email = ""
    plan = "free"
    context = req.context
    try:
        from apps.core import auth

        u = auth.verify_user(request.cookies.get(auth.USER_COOKIE))
        if u:
            email = (u.get("email") or "").strip().lower()
            plan = "business" if email in _owner_emails() else await _get_user_plan(email)
            if not context:
                context = _profile_context(await _get_profile(email)) or None
    except Exception:
        pass

    if email and plan in ("pro", "business"):
        from apps.core.ops.cost_ledger import get_ledger

        if get_ledger().is_frozen(email):
            return JSONResponse(
                {
                    "ok": False,
                    "error": "burn_cap",
                    "synthesis": "Alcanzaste el tope de uso de IA de tu plan este mes.",
                },
                status_code=402,
            )

    try:
        from apps.core.orchestration.dynamic_workflow import get_dynamic_workflow

        wf = await get_dynamic_workflow()
        result = await wf.run(req.goal, context=context)
        payload = result.to_dict()
        _log_workflow_run(
            email,
            req.goal,
            payload.get("subtasks", []),
            payload.get("total_tokens", 0),
            payload.get("duration_ms", 0),
            payload.get("ok", False),
        )
        await _record_ai_cost(email, plan, req.goal, payload.get("synthesis", ""))
        payload["processing_time_ms"] = int((time.time() - start) * 1000)
        return payload
    except Exception as e:
        logger.error(f"Workflow error: {e}")
        return JSONResponse({"ok": False, "error": str(e), "synthesis": ""}, status_code=500)


@app.post("/api/v1/workflow/stream")
async def dynamic_workflow_stream(req: WorkflowRequest, request: Request):
    """Streaming (SSE) de /api/v1/workflow — emite cada subagente en cuanto
    termina para que el dashboard renderice el flujo en vivo. Mismos guards que
    la ruta no-streaming (comparte el bucket de rate limit para que cambiar de
    endpoint no evada el tope). El cliente cae al POST normal si el stream falla.
    """
    if not _current_user(request):
        return JSONResponse({"ok": False, "error": "auth"}, status_code=401)
    if not _rate_ok(request, "workflow", 6, 300):
        return JSONResponse({"ok": False, "error": "rate_limited"}, status_code=429)
    if _PANIC["on"]:
        return JSONResponse({"ok": False, "error": "paused"}, status_code=503)

    email = ""
    plan = "free"
    context = req.context
    try:
        from apps.core import auth

        u = auth.verify_user(request.cookies.get(auth.USER_COOKIE))
        if u:
            email = (u.get("email") or "").strip().lower()
            plan = "business" if email in _owner_emails() else await _get_user_plan(email)
            if not context:
                context = _profile_context(await _get_profile(email)) or None
    except Exception:
        pass

    if email and plan in ("pro", "business"):
        from apps.core.ops.cost_ledger import get_ledger

        if get_ledger().is_frozen(email):
            return JSONResponse({"ok": False, "error": "burn_cap"}, status_code=402)

    async def _sse():
        synthesis = ""
        try:
            from apps.core.orchestration.dynamic_workflow import get_dynamic_workflow

            wf = await get_dynamic_workflow()
            async for ev in wf.run_events(req.goal, context=context):
                if ev.get("type") == "done":
                    synthesis = ev.get("synthesis", "")
                    _log_workflow_run(
                        email,
                        req.goal,
                        ev.get("subtasks", []),
                        ev.get("total_tokens", 0),
                        ev.get("duration_ms", 0),
                        ev.get("ok", False),
                    )
                yield f"data: {json.dumps(ev, ensure_ascii=False)}\n\n"
        except Exception as e:  # noqa: BLE001 — the stream must always close cleanly.
            logger.error(f"Workflow stream error: {e}")
            yield f"data: {json.dumps({'type': 'error', 'error': str(e)[:200]})}\n\n"
        finally:
            with suppress(Exception):
                await _record_ai_cost(email, plan, req.goal, synthesis)

    return StreamingResponse(
        _sse(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",  # disable proxy buffering so events flush live
            "Connection": "keep-alive",
        },
    )


@app.get("/api/v1/workflow/runs")
async def workflow_runs(request: Request):
    """Panel de uso del usuario: agregados de por vida + últimos flujos.

    Es la base del modelo 'cobra por resultado' — `deliverables` cuenta flujos
    completados, no tokens. Cada usuario ve solo lo suyo.
    """
    if not _current_user(request):
        return JSONResponse({"ok": False, "error": "auth"}, status_code=401)

    email = ""
    try:
        from apps.core import auth

        u = auth.verify_user(request.cookies.get(auth.USER_COOKIE))
        if u:
            email = (u.get("email") or "").strip().lower()
    except Exception:
        pass

    from apps.core.ops.workflow_ledger import get_workflow_ledger

    led = get_workflow_ledger()
    return {"ok": True, "stats": led.stats(email), "runs": led.recent(email, 8)}


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
async def run_mission(req: RunRequest, request: Request):
    """Execute a mission using ARIA's execution engine. Owner-only — this drives
    the autonomous engine and must not be exposed to anonymous callers."""
    import time

    if not _is_owner_user(request):
        return JSONResponse({"success": False, "error": "forbidden"}, status_code=403)
    if not _rate_ok(request, "run", 10, 60):
        return JSONResponse({"success": False, "error": "rate_limited"}, status_code=429)
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


@app.get("/api/v1/activepieces/selftest")
async def activepieces_selftest():
    """Check that the Activepieces MCP bridge is reachable and list available tools."""
    try:
        from apps.core.tools.activepieces_mcp import get_activepieces_mcp

        return await get_activepieces_mcp().self_test()
    except Exception as e:
        logger.error(f"Activepieces selftest error: {e}")
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
