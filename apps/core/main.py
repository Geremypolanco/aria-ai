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
    HTMLResponse,
    JSONResponse,
    PlainTextResponse,
    RedirectResponse,
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


class ProfileRequest(BaseModel):
    name: str = ""
    work: str = ""
    goals: list[str] = []
    plan: str = "free"


class ConnectorRequest(BaseModel):
    app: str = ""


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

    raw_email = (user.get("email") or "").strip().lower()
    profile = await _get_profile(raw_email)

    # Prefer the name the user chose during onboarding, else the OAuth name.
    chosen = profile.get("name") if profile else ""
    name = _safe_name(chosen or user.get("name") or raw_email.split("@")[0] or "there")
    email = _safe_name(user.get("email", ""))
    first = name.split(" ")[0] if name else "there"
    initial = (first[:1] or "Y").upper()
    is_owner = raw_email in _owner_emails()
    plan_map = {"pro": "Pro", "business": "Business"}
    plan = "Business" if is_owner else plan_map.get(await _get_user_plan(raw_email), "Free")
    onboarded = "true" if (profile and profile.get("onboarded")) else "false"
    profile_json = json.dumps(
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

    html = (
        html.replace("__NAME__", name)
        .replace("__FIRST__", first)
        .replace("__INITIAL__", initial)
        .replace("__EMAIL__", email)
        .replace("__PLAN__", plan)
        .replace("__ONBOARDED__", onboarded)
        .replace("__PROFILE_JSON__", profile_json)
        .replace("__IS_OWNER__", "true" if is_owner else "false")
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


@app.get("/billing/checkout")
async def billing_checkout(request: Request, tier: str = "pro"):
    """Start a Stripe Checkout session for the given ARIA subscription tier."""
    from apps.core import auth

    user = auth.verify_user(request.cookies.get(auth.USER_COOKIE))
    if not user:
        return RedirectResponse("/login", status_code=307)

    plan = BILLING_PLANS.get(tier if tier in BILLING_PLANS else "pro")

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
                    f"🔒 You've reached today's free limit of {FREE_DAILY_LIMIT} messages.\n\n"
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
