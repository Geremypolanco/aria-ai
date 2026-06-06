"""
Aria AI -- Sistema Operativo Nucleo v2.1 -- Gobernador Economico + Motor de Ventas
FastAPI + APScheduler + Telegram Webhook + SalesAgent + 5 jobs autonomos
"""
from __future__ import annotations
import logging, os, sys
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any, Optional

import httpx, uvicorn
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel

from apps.core.config import settings
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
                "<b>ARIA AI v2.1 Online</b>\n\n"
                "Gobernador Economico + Motor de Ventas activos.\n"
                "Usa /ayuda para ver comandos."
            )
    except Exception as exc:
        logger.error("Error registrando webhook Telegram: %s", exc)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("ARIA AI v2.1 iniciando...")
    try:
        await set_telegram_webhook()
    except Exception as exc:
        logger.warning("Telegram webhook failed: %s", exc)

    scheduler.add_job(run_content_cycle, IntervalTrigger(minutes=settings.CYCLE_INTERVAL_MINUTES),
                      id="content_cycle", replace_existing=True)
    scheduler.add_job(run_sales_cycle, CronTrigger(hour=8, minute=0),
                      id="sales_cycle", replace_existing=True)
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
    title="ARIA AI -- Gobernador Economico v2.1",
    description="Sistema autonomo de generacion de ingresos y gestion economica circular",
    version="2.1.0",
    lifespan=lifespan,
)


async def run_content_cycle() -> None:
    try:
        from apps.core.agents.content_agent import ContentAgent
        agent = ContentAgent()
        await agent.start()
        await agent.run({"task": "full_pipeline"})
        await agent.stop()
    except Exception as exc:
        logger.error("Content cycle error: %s", exc)


async def run_sales_cycle() -> None:
    try:
        from apps.core.agents.sales_agent import SalesAgent
        agent = SalesAgent()
        await agent.start()
        await agent.run({"mode": "revenue_cycle"})
        await agent.stop()
    except Exception as exc:
        logger.error("Sales cycle error: %s", exc)


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


@app.get("/")
async def root() -> JSONResponse:
    return JSONResponse({
        "system": "ARIA AI", "version": "2.1.0", "status": "operational",
        "environment": settings.ENVIRONMENT,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "capabilities": [
            "revenue_generation", "sales_intelligence", "copywriting",
            "economic_governance", "content_creation", "auto_evolution",
        ],
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


@app.get("/products/ready")
async def get_ready_products() -> JSONResponse:
    try:
        from apps.core.tools.revenue_engine import READY_TO_LAUNCH_PRODUCTS
        return JSONResponse({"products": READY_TO_LAUNCH_PRODUCTS, "count": len(READY_TO_LAUNCH_PRODUCTS)})
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.post("/sales/cycle")
async def trigger_sales_cycle() -> JSONResponse:
    try:
        import asyncio
        asyncio.create_task(run_sales_cycle())
        return JSONResponse({"success": True, "message": "Ciclo de ventas iniciado"})
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.post("/sales/copy")
async def generate_copy(request: Request) -> JSONResponse:
    try:
        data = await request.json()
        product = data.get("product", "")
        audience = data.get("audience", "")
        pain = data.get("pain", "")
        benefit = data.get("benefit", "")
        if not all([product, audience, pain, benefit]):
            raise HTTPException(status_code=400, detail="product, audience, pain y benefit son requeridos")
        from apps.core.agents.sales_agent import SalesAgent
        agent = SalesAgent()
        result = await agent.generate_sales_copy(product, audience, pain, benefit)
        return JSONResponse(result)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.post("/sales/product")
async def create_product(request: Request) -> JSONResponse:
    try:
        data = await request.json()
        niche = data.get("niche", "emprendedores digitales")
        topic = data.get("topic", "productividad")
        from apps.core.agents.sales_agent import SalesAgent
        agent = SalesAgent()
        result = await agent.create_and_launch_product(niche=niche, topic=topic)
        return JSONResponse(result)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.get("/sales/niches")
async def get_niches() -> JSONResponse:
    try:
        from apps.core.tools.sales_intelligence import NicheTargetingEngine
        engine = NicheTargetingEngine()
        return JSONResponse({"niches": engine.get_all_niches(), "count": len(engine.HIGH_VALUE_NICHES)})
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.get("/sales/frameworks")
async def get_sales_frameworks() -> JSONResponse:
    try:
        from apps.core.tools.sales_intelligence import SalesIntelligence
        si = SalesIntelligence()
        return JSONResponse(si.get_sales_framework_summary())
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.get("/sales/personas")
async def get_buyer_personas() -> JSONResponse:
    try:
        from apps.core.tools.audience_profiler import BUYER_PERSONAS
        return JSONResponse({"personas": BUYER_PERSONAS, "count": len(BUYER_PERSONAS)})
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.post("/sales/followup")
async def create_followup(request: Request) -> JSONResponse:
    try:
        data = await request.json()
        from apps.core.agents.sales_agent import SalesAgent
        agent = SalesAgent()
        result = await agent.setup_followup(
            lead_name=data.get("name", ""),
            lead_email=data.get("email", ""),
            product=data.get("product", ""),
            pain=data.get("pain", ""),
        )
        return JSONResponse(result)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.get("/sales/report")
async def sales_report() -> JSONResponse:
    try:
        from apps.core.agents.sales_agent import SalesAgent
        agent = SalesAgent()
        result = await agent.generate_sales_report()
        return JSONResponse(result)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.post("/governance/cycle")
async def trigger_governance() -> JSONResponse:
    try:
        import asyncio
        asyncio.create_task(run_governance_cycle())
        return JSONResponse({"success": True, "message": "Ciclo de gobernanza iniciado"})
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.get("/governance/status")
async def governance_status() -> JSONResponse:
    try:
        db = get_db()
        policies = await db.get_economic_policies(limit=5)
        capital = await db.get_capital_allocations(limit=5)
        return JSONResponse({"recent_policies": policies, "recent_allocations": capital})
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


@app.get("/ai/metrics")
async def get_ai_metrics() -> JSONResponse:
    try:
        ai = get_ai_client()
        return JSONResponse(ai.get_health_summary())
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


@app.get("/auth/callback/{platform}")
async def social_auth_callback(platform: str, request: Request) -> JSONResponse:
    SUPPORTED = {"facebook", "instagram", "tiktok", "linkedin"}
    if platform not in SUPPORTED:
        return JSONResponse({"ok": False, "error": "Plataforma no soportada"}, status_code=400)
    code = request.query_params.get("code")
    error = request.query_params.get("error")
    if error:
        await send_telegram(f"OAuth {platform}: {error}")
        return JSONResponse({"ok": False, "error": error})
    if not code:
        return JSONResponse({"ok": False, "error": "No se recibio codigo"}, status_code=400)
    try:
        from apps.core.tools.social_media import SocialMediaManager
        sm = SocialMediaManager()
        token_data = await sm.exchange_code_for_token(platform, code)
        if not token_data:
            return JSONResponse({"ok": False, "error": "Token exchange failed"})
        access_token = token_data.get("access_token")
        profile = await sm.get_user_profile(platform, access_token) or {}
        saved = await sm.save_account(platform, access_token,
                                       token_data.get("refresh_token"),
                                       token_data.get("expires_in"), profile)
        username = profile.get("username", "cuenta")
        if saved:
            await send_telegram(f"<b>{platform.title()} conectado</b>\nCuenta: @{username}")
            return HTMLResponse(f"<h2>{platform.title()} conectado: @{username}</h2>")
        return JSONResponse({"ok": False, "error": "Error saving account"})
    except Exception as exc:
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
        if not platform or not content:
            raise HTTPException(status_code=400, detail="platform y content son requeridos")
        from apps.core.tools.social_media import SocialMediaManager
        sm = SocialMediaManager()
        result = await sm.post_content(platform, content, data.get("image_url"))
        return JSONResponse(result)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.get("/auth/linkedin", response_class=HTMLResponse)
async def linkedin_auth_start() -> HTMLResponse:
    client_id = getattr(settings, "LINKEDIN_CLIENT_ID", None)
    if not client_id:
        return HTMLResponse("<h2>LINKEDIN_CLIENT_ID no configurado</h2>")
    import urllib.parse
    params = {
        "response_type": "code", "client_id": client_id,
        "redirect_uri": "https://aria-ai.fly.dev/auth/linkedin/callback",
        "scope": "openid profile email w_member_social",
        "state": "aria_linkedin_connect",
    }
    auth_url = "https://www.linkedin.com/oauth/v2/authorization?" + urllib.parse.urlencode(params)
    return HTMLResponse(f'''<html><body style="font-family:sans-serif;padding:40px;text-align:center">
<h2>Conectar LinkedIn a ARIA AI</h2>
<a href="{auth_url}" style="background:#0a66c2;color:#fff;padding:12px 28px;border-radius:8px;text-decoration:none;font-weight:bold">
Conectar LinkedIn</a></body></html>''')


@app.get("/auth/linkedin/callback")
async def linkedin_auth_callback(code: str = "", error: str = "") -> HTMLResponse:
    if error or not code:
        return HTMLResponse(f"<h2>Error: {error or 'Codigo faltante'}</h2>", status_code=400)
    client_id = getattr(settings, "LINKEDIN_CLIENT_ID", None)
    client_secret = getattr(settings, "LINKEDIN_CLIENT_SECRET", None)
    if not client_id or not client_secret:
        return HTMLResponse("<h2>Credenciales LinkedIn no configuradas</h2>", status_code=500)
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            token_res = await client.post(
                "https://www.linkedin.com/oauth/v2/accessToken",
                data={"grant_type": "authorization_code", "code": code,
                      "redirect_uri": "https://aria-ai.fly.dev/auth/linkedin/callback",
                      "client_id": client_id, "client_secret": client_secret},
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
            if token_res.status_code != 200:
                return HTMLResponse(f"<h2>Error token: {token_res.text[:200]}</h2>", status_code=500)
            token_data = token_res.json()
            access_token = token_data.get("access_token", "")
            profile_res = await client.get(
                "https://api.linkedin.com/v2/userinfo",
                headers={"Authorization": f"Bearer {access_token}"},
            )
            profile = profile_res.json() if profile_res.status_code == 200 else {}
            name = profile.get("name", "Usuario")
        await send_telegram(f"<b>LinkedIn conectado</b>\nCuenta: {name}")
        return HTMLResponse(f"<h2>LinkedIn conectado exitosamente: {name}</h2>")
    except Exception as exc:
        return HTMLResponse(f"<h2>Error: {exc}</h2>", status_code=500)


@app.get("/auth/linkedin/status")
async def linkedin_status() -> JSONResponse:
    token = getattr(settings, "LINKEDIN_ACCESS_TOKEN", None)
    if not token:
        return JSONResponse({"connected": False, "connect_url": "https://aria-ai.fly.dev/auth/linkedin"})
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            res = await client.get("https://api.linkedin.com/v2/userinfo",
                                   headers={"Authorization": f"Bearer {token}"})
            if res.status_code == 200:
                profile = res.json()
                return JSONResponse({"connected": True, "name": profile.get("name", "")})
            return JSONResponse({"connected": False, "error": f"HTTP {res.status_code}"})
    except Exception as exc:
        return JSONResponse({"connected": False, "error": str(exc)})


if __name__ == "__main__":
    uvicorn.run(
        "apps.core.main:app",
        host="0.0.0.0",
        port=int(os.getenv("PORT", "8000")),
        reload=False,
    )
