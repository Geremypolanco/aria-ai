"""
Aria AI — Sistema Operativo Nucleo
FastAPI + APScheduler + Telegram Webhook bidireccional + 4 jobs autonomos
"""
from __future__ import annotations

import logging
import os
import sys
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any, Optional

import httpx
import uvicorn
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel

from apps.core.config import settings
from apps.core.memory.redis_client import get_cache
from apps.core.memory.supabase_client import get_db
from apps.core.tools.ai_client import AIModel, get_ai_client

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("aria.core")

TELEGRAM_API = "https://api.telegram.org/bot"
scheduler = AsyncIOScheduler(timezone="UTC")

_orchestrator: Optional[Any] = None


async def get_orchestrator() -> Any:
    global _orchestrator
    if _orchestrator is None:
        from apps.core.agents.orchestrator import Orchestrator
        _orchestrator = Orchestrator()
        await _orchestrator.start()
    return _orchestrator


# -- TELEGRAM -----------------------------------------------------------------

async def send_telegram(message: str) -> bool:
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            res = await client.post(
                f"{TELEGRAM_API}{settings.TELEGRAM_TOKEN}/sendMessage",
                json={
                    "chat_id": settings.TELEGRAM_CHAT_ID,
                    "text": message,
                    "parse_mode": "HTML",
                    "disable_web_page_preview": True,
                },
            )
            return res.status_code == 200
    except Exception as exc:
        logger.error("Telegram error: %s", exc)
        return False


async def set_telegram_webhook() -> None:
    webhook_url = "https://aria-ai.fly.dev/telegram/webhook"
    try:
        from apps.core.tools.telegram_bot import get_bot
        bot = get_bot()
        ok = await bot.set_webhook(webhook_url)
        if ok:
            logger.info("Telegram webhook registrado: %s", webhook_url)
            await send_telegram(
                "<b>ARIA AI Online</b>\n\nSistema iniciado.\n"
                f"Webhook: <code>{webhook_url}</code>\n\nUsa /ayuda para ver comandos."
            )
        else:
            logger.warning("No se pudo registrar el webhook de Telegram")
    except Exception as exc:
        logger.error("Error registrando webhook de Telegram: %s", exc)


# -- LIFESPAN -----------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("ARIA AI iniciando...")
    try:
        await set_telegram_webhook()
    except Exception as exc:
        logger.warning("Telegram webhook setup failed: %s", exc)

    scheduler.add_job(run_content_cycle, IntervalTrigger(minutes=settings.CYCLE_INTERVAL_MINUTES),
                      id="content_cycle", replace_existing=True)
    scheduler.add_job(run_governance_cycle, CronTrigger(hour=0, minute=0),
                      id="governance_cycle", replace_existing=True)
    scheduler.add_job(run_evolution_cycle, CronTrigger(hour=3, minute=0),
                      id="evolution_cycle", replace_existing=True)
    scheduler.add_job(run_hr_cycle, CronTrigger(hour=6, minute=0),
                      id="hr_cycle", replace_existing=True)
    scheduler.start()
    logger.info("ARIA AI operativa. Jobs: %d", len(scheduler.get_jobs()))

    yield

    scheduler.shutdown(wait=False)
    logger.info("ARIA AI apagada.")


app = FastAPI(
    title="ARIA AI — Gobernador Economico",
    description="Sistema autonomo de gestion economica circular",
    version="2.0.0",
    lifespan=lifespan,
)


# -- JOBS AUTONOMOS -----------------------------------------------------------

async def run_content_cycle() -> None:
    try:
        from apps.core.agents.content_agent import ContentAgent
        agent = ContentAgent()
        await agent.start()
        await agent.run({"task": "full_pipeline"})
        await agent.stop()
    except Exception as exc:
        logger.error("Content cycle error: %s", exc)


async def run_governance_cycle() -> None:
    try:
        from apps.core.agents.economic_governor_agent import EconomicGovernorAgent
        agent = EconomicGovernorAgent()
        await agent.start()
        await agent.run({"mode": "full_cycle"})
        await agent.stop()
    except Exception as exc:
        logger.error("Governance cycle error: %s", exc)


async def run_evolution_cycle() -> None:
    try:
        from apps.core.agents.evolution_agent import EvolutionAgent
        agent = EvolutionAgent()
        await agent.start()
        await agent.run({"task": "auto_evolve"})
        await agent.stop()
    except Exception as exc:
        logger.error("Evolution cycle error: %s", exc)


async def run_hr_cycle() -> None:
    try:
        from apps.core.agents.human_resources_agent import HumanResourcesAgent
        agent = HumanResourcesAgent()
        await agent.start()
        await agent.run({"mode": "cycle"})
        await agent.stop()
    except Exception as exc:
        logger.error("HR cycle error: %s", exc)


# -- ENDPOINTS ----------------------------------------------------------------

@app.get("/")
async def root() -> JSONResponse:
    return JSONResponse({
        "system": "ARIA AI",
        "version": "2.0.0",
        "status": "operational",
        "environment": settings.ENVIRONMENT,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    })


@app.get("/health")
async def health() -> JSONResponse:
    return JSONResponse({"status": "ok", "timestamp": datetime.now(timezone.utc).isoformat()})


@app.get("/status")
async def status() -> JSONResponse:
    try:
        db = get_db()
        logs = await db.get_recent_logs(limit=5)
        return JSONResponse({
            "status": "operational",
            "jobs": [j.id for j in scheduler.get_jobs()],
            "recent_logs": logs,
        })
    except Exception as exc:
        return JSONResponse({"status": "degraded", "error": str(exc)}, status_code=500)


@app.get("/revenue")
async def get_revenue() -> JSONResponse:
    try:
        db = get_db()
        total = await db.get_total_revenue()
        by_platform = await db.get_revenue_by_platform()
        recent = db._client.table("revenue").select("*").order("created_at", desc=True).limit(20).execute()
        return JSONResponse({
            "total_usd": total,
            "by_platform": by_platform,
            "recent_transactions": recent.data or [],
        })
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.get("/ai/metrics")
async def get_ai_metrics() -> JSONResponse:
    try:
        ai = get_ai_client()
        return JSONResponse(ai.get_health_summary())
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.get("/market/opportunities")
async def get_opportunities(limit: int = 10) -> JSONResponse:
    try:
        db = get_db()
        opportunities = await db.get_best_opportunities(limit=limit)
        return JSONResponse({"opportunities": opportunities, "count": len(opportunities)})
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.get("/products")
async def get_products(limit: int = 20) -> JSONResponse:
    try:
        db = get_db()
        result = db._client.table("products").select("*").order("created_at", desc=True).limit(limit).execute()
        return JSONResponse({"products": result.data or [], "count": len(result.data or [])})
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.get("/websites")
async def get_websites(limit: int = 20) -> JSONResponse:
    try:
        db = get_db()
        result = db._client.table("websites").select("*").order("created_at", desc=True).limit(limit).execute()
        return JSONResponse({"websites": result.data or [], "count": len(result.data or [])})
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.post("/governance/cycle")
async def trigger_governance() -> JSONResponse:
    try:
        import asyncio
        asyncio.create_task(run_governance_cycle())
        return JSONResponse({"success": True, "message": "Ciclo de gobernanza economica iniciado"})
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.get("/governance/status")
async def governance_status() -> JSONResponse:
    try:
        db = get_db()
        policies = await db.get_economic_policies(limit=5)
        capital = await db.get_capital_allocations(limit=5)
        return JSONResponse({
            "recent_policies": policies,
            "recent_allocations": capital,
        })
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.post("/evolve")
async def trigger_evolution() -> JSONResponse:
    try:
        import asyncio
        asyncio.create_task(run_evolution_cycle())
        await send_telegram("<b>Auto-evolucion disparada</b> manualmente.")
        return JSONResponse({"success": True, "message": "Evolucion en progreso"})
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


# -- TELEGRAM WEBHOOK ---------------------------------------------------------

class TelegramUpdate(BaseModel):
    update_id: int
    message: Optional[dict] = None
    callback_query: Optional[dict] = None


@app.post("/telegram/webhook")
async def telegram_webhook(update: TelegramUpdate) -> JSONResponse:
    try:
        from apps.core.tools.telegram_bot import get_bot
        bot = get_bot()
        await bot.process_update(update.model_dump())
        return JSONResponse({"ok": True})
    except Exception as exc:
        logger.error("Telegram webhook error: %s", exc)
        return JSONResponse({"ok": False, "error": str(exc)}, status_code=500)


# -- OAUTH REDES SOCIALES -----------------------------------------------------

@app.get("/auth/callback/{platform}")
async def social_auth_callback(platform: str, request: Request) -> JSONResponse:
    SUPPORTED = {"facebook", "instagram", "tiktok", "linkedin"}
    if platform not in SUPPORTED:
        return JSONResponse({"ok": False, "error": "Plataforma no soportada"}, status_code=400)

    code = request.query_params.get("code")
    error = request.query_params.get("error")

    if error:
        msg = request.query_params.get("error_description", error)
        await send_telegram(f"No pude conectar {platform.title()}. Error: {msg}")
        return JSONResponse({"ok": False, "error": msg})

    if not code:
        return JSONResponse({"ok": False, "error": "No se recibio codigo de autorizacion"}, status_code=400)

    try:
        from apps.core.tools.social_media import SocialMediaManager
        sm = SocialMediaManager()
        token_data = await sm.exchange_code_for_token(platform, code)
        if not token_data:
            await send_telegram(f"No pude obtener tokens de {platform.title()}")
            return JSONResponse({"ok": False, "error": "Token exchange failed"})

        access_token = token_data.get("access_token")
        refresh_token = token_data.get("refresh_token")
        expires_in = token_data.get("expires_in")
        profile = await sm.get_user_profile(platform, access_token) or {}
        saved = await sm.save_account(platform, access_token, refresh_token, expires_in, profile)
        username = profile.get("username", "cuenta")

        if saved:
            await send_telegram(f"<b>{platform.title()} conectado</b>\nCuenta: @{username}")
            html = (
                f"<html><body style='font-family:sans-serif;text-align:center;padding:40px'>"
                f"<h2>{platform.title()} conectado</h2>"
                f"<p>Cuenta <strong>@{username}</strong> vinculada a ARIA.</p>"
                f"</body></html>"
            )
            return HTMLResponse(content=html)
        else:
            await send_telegram(f"Obtuve tokens de {platform.title()} pero no pude guardarlos.")
            return JSONResponse({"ok": False, "error": "Error saving account"})

    except Exception as exc:
        logger.error("OAuth callback error for %s: %s", platform, exc)
        await send_telegram(f"Error en callback OAuth de {platform.title()}: {str(exc)[:100]}")
        return JSONResponse({"ok": False, "error": str(exc)}, status_code=500)


@app.get("/social/accounts")
async def list_social_accounts() -> JSONResponse:
    try:
        from apps.core.tools.social_media import SocialMediaManager
        sm = SocialMediaManager()
        accounts = await sm.list_connected_accounts()
        return JSONResponse({"accounts": accounts, "count": len(accounts)})
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.post("/social/post")
async def social_post(request: Request) -> JSONResponse:
    try:
        data = await request.json()
        platform = data.get("platform")
        content = data.get("content")
        image_url = data.get("image_url")
        if not platform or not content:
            raise HTTPException(status_code=400, detail="platform y content son requeridos")
        from apps.core.tools.social_media import SocialMediaManager
        sm = SocialMediaManager()
        result = await sm.post_content(platform, content, image_url)
        return JSONResponse(result)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


# -- LINKEDIN OAUTH -----------------------------------------------------------

LINKEDIN_AUTH_URL = "https://www.linkedin.com/oauth/v2/authorization"
LINKEDIN_TOKEN_URL = "https://www.linkedin.com/oauth/v2/accessToken"
LINKEDIN_REDIRECT = "https://aria-ai.fly.dev/auth/linkedin/callback"
LINKEDIN_SCOPES = "openid profile email w_member_social"


@app.get("/auth/linkedin", response_class=HTMLResponse)
async def linkedin_auth_start() -> HTMLResponse:
    client_id = getattr(settings, "LINKEDIN_CLIENT_ID", None)
    if not client_id:
        return HTMLResponse(content="""<!DOCTYPE html><html><head><meta charset="UTF-8">
<title>ARIA LinkedIn</title></head>
<body style='font-family:system-ui;background:#0f0f0f;color:#e0e0e0;
display:flex;align-items:center;justify-content:center;min-height:100vh'>
<div style='background:#1a1a1a;border:1px solid #333;border-radius:16px;padding:40px;max-width:520px;text-align:center'>
<h2 style='color:#f44336'>LinkedIn no configurado</h2>
<p>Ejecuta: fly secrets set LINKEDIN_CLIENT_ID=xxx LINKEDIN_CLIENT_SECRET=yyy -a aria-ai</p>
</div></body></html>""", status_code=200)

    import urllib.parse
    params = {
        "response_type": "code", "client_id": client_id,
        "redirect_uri": LINKEDIN_REDIRECT, "scope": LINKEDIN_SCOPES,
        "state": "aria_linkedin_connect",
    }
    auth_url = f"{LINKEDIN_AUTH_URL}?{urllib.parse.urlencode(params)}"
    return HTMLResponse(content=f"""<!DOCTYPE html><html lang="es">
<head><meta charset="UTF-8"><title>ARIA Conectar LinkedIn</title></head>
<body style='font-family:system-ui;background:#0f0f0f;color:#e0e0e0;
display:flex;align-items:center;justify-content:center;min-height:100vh'>
<div style='background:#1a1a1a;border:1px solid #333;border-radius:16px;padding:48px;max-width:520px;text-align:center'>
<div style='font-size:3rem'>&#128188;</div>
<h1>Conectar LinkedIn</h1>
<p style='color:#888;margin-bottom:24px'>ARIA publicara articulos y posts automaticamente.</p>
<a href="{auth_url}" style='display:inline-block;background:#0a66c2;color:#fff;border-radius:8px;
padding:16px 36px;font-size:1rem;font-weight:700;text-decoration:none'>
Conectar con LinkedIn</a>
</div></body></html>""")


@app.get("/auth/linkedin/callback")
async def linkedin_auth_callback(code: str = "", error: str = "", state: str = "") -> HTMLResponse:
    if error:
        return HTMLResponse(f"<h2>Error de autorizacion</h2><p>{error}</p>", status_code=400)
    if not code:
        return HTMLResponse("<h2>Codigo faltante</h2>", status_code=400)

    client_id = getattr(settings, "LINKEDIN_CLIENT_ID", None)
    client_secret = getattr(settings, "LINKEDIN_CLIENT_SECRET", None)
    if not client_id or not client_secret:
        return HTMLResponse("<h2>LINKEDIN_CLIENT_ID/SECRET no configurados</h2>", status_code=500)

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            token_res = await client.post(
                LINKEDIN_TOKEN_URL,
                data={
                    "grant_type": "authorization_code", "code": code,
                    "redirect_uri": LINKEDIN_REDIRECT,
                    "client_id": client_id, "client_secret": client_secret,
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
            if token_res.status_code != 200:
                return HTMLResponse(
                    f"<h2>Error obteniendo token</h2><pre>{token_res.text[:300]}</pre>",
                    status_code=500,
                )
            token_data = token_res.json()
            access_token = token_data.get("access_token", "")
            expires_in = token_data.get("expires_in", 0)

            profile_res = await client.get(
                "https://api.linkedin.com/v2/userinfo",
                headers={"Authorization": f"Bearer {access_token}"},
            )
            profile = profile_res.json() if profile_res.status_code == 200 else {}
            name = profile.get("name", "Usuario")

            fly_token = getattr(settings, "FLY_API_TOKEN", None)
            if fly_token:
                try:
                    await client.post(
                        "https://api.fly.io/graphql",
                        json={"query": (
                            'mutation { setSecrets(input: {appId: "aria-ai", '
                            'secrets: [{key: "LINKEDIN_ACCESS_TOKEN", value: "' + access_token + '"}], '
                            'replaceAll: false}) { release { id } } }'
                        )},
                        headers={"Authorization": fly_token},
                    )
                except Exception:
                    pass

            days = expires_in // 86400
            logger.info("LinkedIn OAuth completado para: %s", name)
            await send_telegram(f"<b>LinkedIn conectado</b>\nCuenta: {name}\nToken valido {days} dias")
            return HTMLResponse(f"""<!DOCTYPE html><html><head><meta charset="UTF-8">
<title>LinkedIn Conectado</title></head>
<body style='font-family:system-ui;background:#0f0f0f;color:#e0e0e0;
display:flex;align-items:center;justify-content:center;min-height:100vh'>
<div style='background:#1a1a1a;border:1px solid #2a5e2a;border-radius:16px;padding:48px;max-width:520px;text-align:center'>
<div style='font-size:3rem'>&#9989;</div>
<h1 style='color:#4caf50'>LinkedIn Conectado</h1>
<p>Bienvenido, <strong>{name}</strong>. Token valido {days} dias. Puedes cerrar esta ventana.</p>
</div></body></html>""")

    except Exception as exc:
        logger.error("LinkedIn OAuth callback error: %s", exc)
        return HTMLResponse(f"<h2>Error interno</h2><p>{exc}</p>", status_code=500)


@app.get("/auth/linkedin/status")
async def linkedin_status() -> JSONResponse:
    token = getattr(settings, "LINKEDIN_ACCESS_TOKEN", None)
    if not token:
        return JSONResponse({"connected": False, "connect_url": "https://aria-ai.fly.dev/auth/linkedin"})
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            res = await client.get(
                "https://api.linkedin.com/v2/userinfo",
                headers={"Authorization": f"Bearer {token}"},
            )
            if res.status_code == 200:
                profile = res.json()
                return JSONResponse({
                    "connected": True,
                    "name": profile.get("name", ""),
                    "email": profile.get("email", ""),
                })
            return JSONResponse({
                "connected": False,
                "error": f"Token invalido (HTTP {res.status_code})",
                "connect_url": "https://aria-ai.fly.dev/auth/linkedin",
            })
    except Exception as exc:
        return JSONResponse({"connected": False, "error": str(exc)})


# -- ENTRY POINT --------------------------------------------------------------

if __name__ == "__main__":
    uvicorn.run(
        "apps.core.main:app",
        host="0.0.0.0",
        port=int(os.getenv("PORT", "8000")),
        reload=False,
    )
