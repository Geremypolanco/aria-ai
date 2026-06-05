"""
Aria AI — Sistema Operativo Núcleo
FastAPI + APScheduler + Telegram Webhook bidireccional + 4 jobs autónomos
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
from fastapi.responses import JSONResponse
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

# Orchestrator instancia global (lazy)
_orchestrator: Optional[Any] = None


async def get_orchestrator() -> Any:
    global _orchestrator
    if _orchestrator is None:
        from apps.core.agents.orchestrator import Orchestrator
        _orchestrator = Orchestrator()
        await _orchestrator.start()
    return _orchestrator


# ── TELEGRAM ──────────────────────────────────────────────

async def send_telegram(message: str) -> bool:
    """Envía un mensaje de texto al propietario via Telegram."""
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
    """Registra el webhook de Telegram al iniciar la app."""
    webhook_url = f"https://aria-ai.fly.dev/telegram/webhook"
    try:
        from apps.core.tools.telegram_bot import get_bot
        bot = get_bot()
        ok = await bot.set_webhook(webhook_url)
        if ok:
            logger.info("Telegram webhook registrado: %s", webhook_url)
            await send_telegram(
                f"🤖 <b>ARIA AI — Online</b>\n\n"
                f"Sistema iniciado correctamente.\n"
                f"Webhook activo en: <code>{webhook_url}</code>\n\n"
                f"Usa /ayuda para ver todos los comandos disponibles."
            )
        else:
            logger.warning("No se pudo registrar el webhook de Telegram")
    except Exception as exc:
        logger.error("Error registrando webhook de Telegram: %s", exc)


# ── SCHEDULER JOBS ────────────────────────────────────────

async def autonomous_cycle_job() -> None:
    logger.info("Scheduler: iniciando ciclo autónomo...")
    cache = get_cache()
    locked = await cache.acquire_lock("autonomous_cycle", ttl_seconds=300)
    if not locked:
        logger.info("Scheduler: ciclo ya en ejecución — skip")
        return
    try:
        await cache.set_agent_heartbeat("orchestrator")
        orch = await get_orchestrator()
        await orch.run_cycle()
    except Exception as exc:
        logger.error("Error en ciclo autónomo: %s", exc)
    finally:
        await cache.release_lock("autonomous_cycle")


async def agent_heartbeat_job() -> None:
    try:
        cache = get_cache()
        await cache.set_agent_heartbeat("system")
    except Exception:
        pass


async def daily_report_job() -> None:
    try:
        orch = await get_orchestrator()
        await orch.send_daily_report()
    except Exception as exc:
        logger.error("Error en reporte diario: %s", exc)


async def auto_evolve_job() -> None:
    try:
        from apps.core.agents.evolution_agent import EvolutionAgent
        agent = EvolutionAgent()
        await agent.start()
        await agent.run({"task": "auto_evolve", "market_focus": "all", "primary_language": "es"})
        await agent.stop()
    except Exception as exc:
        logger.error("Error en auto-evolución: %s", exc)


# ── LIFESPAN ──────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Aria OS iniciando...")

    try:
        raw = os.getenv("CYCLE_INTERVAL_MINUTES", "60").strip()
        interval = int(raw) if raw.isdigit() and int(raw) > 0 else 60
        scheduler.add_job(autonomous_cycle_job, IntervalTrigger(minutes=interval), id="autonomous_cycle", replace_existing=True)
        scheduler.add_job(agent_heartbeat_job, IntervalTrigger(seconds=30), id="heartbeat", replace_existing=True)
        scheduler.add_job(daily_report_job, CronTrigger(hour=9, minute=0), id="daily_report", replace_existing=True)
        scheduler.add_job(auto_evolve_job, IntervalTrigger(hours=4), id="auto_evolve", replace_existing=True)
        scheduler.start()
        logger.info("Scheduler iniciado con %d jobs.", len(scheduler.get_jobs()))
    except Exception as exc:
        logger.error("CRITICO: Error iniciando scheduler: %s", exc, exc_info=True)

    try:
        await set_telegram_webhook()
    except Exception as exc:
        logger.error("Error en setup de Telegram: %s", exc)

    logger.info("Aria OS activo.")
    yield

    try:
        scheduler.shutdown(wait=False)
    except Exception:
        pass
    logger.info("Aria OS apagado.")


# ── APP ───────────────────────────────────────────────────

app = FastAPI(
    title="Aria AI — Core OS",
    description="Sistema autónomo de generación de ingresos",
    version="1.0.0",
    lifespan=lifespan,
)


# ── MODELOS PYDANTIC ──────────────────────────────────────

class ChatRequest(BaseModel):
    message: str
    model: Optional[str] = "fast"


class ApprovalDecision(BaseModel):
    approval_id: str
    decision: str  # "approved" | "rejected"


# ── ENDPOINTS PÚBLICOS ────────────────────────────────────

@app.get("/")
async def root() -> JSONResponse:
    return JSONResponse({"status": "online", "system": "Aria OS", "version": "1.0.0"})


@app.get("/health")
async def health() -> JSONResponse:
    """Health check completo para Fly.io."""
    try:
        jobs = scheduler.get_jobs()
        job_info = [
            {
                "id": job.id,
                "next_run": job.next_run_time.isoformat() if job.next_run_time else None,
            }
            for job in jobs
        ]

        ai = await get_ai_client()
        ai_report = ai.get_health_report()

        return JSONResponse({
            "status": "healthy",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "scheduler": {"running": scheduler.running, "jobs": job_info},
            "ai_providers": ai_report,
        })
    except Exception as exc:
        return JSONResponse({"status": "degraded", "error": str(exc)}, status_code=200)


# ── TELEGRAM WEBHOOK ──────────────────────────────────────

@app.post("/telegram/webhook")
async def telegram_webhook(request: Request) -> JSONResponse:
    """
    Webhook de Telegram. Recibe todos los updates del bot y los procesa.
    Telegram requiere respuesta HTTP 200 inmediata — el procesamiento es async.
    """
    try:
        update = await request.json()
        logger.debug("[Webhook] Update recibido: %s", str(update)[:200])

        from apps.core.tools.telegram_bot import get_bot
        import asyncio
        bot = get_bot()
        # Procesamos el update de forma asíncrona sin bloquear el webhook
        asyncio.create_task(bot.handle_update(update))

        return JSONResponse({"ok": True})
    except Exception as exc:
        logger.error("[Webhook] Error procesando update: %s", exc)
        return JSONResponse({"ok": False, "error": str(exc)}, status_code=200)


@app.get("/telegram/status")
async def telegram_status() -> JSONResponse:
    """Verifica el estado del webhook de Telegram."""
    try:
        from apps.core.tools.telegram_bot import get_bot
        bot = get_bot()
        info = await bot.get_webhook_info()
        return JSONResponse({"ok": True, "webhook": info})
    except Exception as exc:
        return JSONResponse({"ok": False, "error": str(exc)})


@app.post("/telegram/reset-webhook")
async def reset_webhook() -> JSONResponse:
    """Re-registra el webhook de Telegram manualmente."""
    try:
        await set_telegram_webhook()
        return JSONResponse({"ok": True, "message": "Webhook re-registrado"})
    except Exception as exc:
        return JSONResponse({"ok": False, "error": str(exc)})



  # ── SOCIAL SESSION (COOKIES SIN API) ─────────────────────

  @app.get("/social/connect", response_class=HTMLResponse)
  async def social_connect_form(platform: str = "", token: str = ""):
      """Pagina web para importar cookies de redes sociales sin API."""
      from apps.core.tools.social_session import PLATFORM_CONFIG, SUPPORTED_PLATFORMS
      valid_token = settings.SOCIAL_CONNECT_TOKEN or "aria"
      if token != valid_token:
          return HTMLResponse("<h1>Token invalido</h1>", status_code=403)
      cfg = PLATFORM_CONFIG.get(platform, {})
      display = cfg.get("display_name", platform or "Red Social")
      emoji = cfg.get("emoji", "🌐") if platform else "🌐"
      instructions = cfg.get("instructions", "Exporta las cookies con Cookie-Editor -> Export as JSON.") if platform else ""
      help_url = cfg.get("help_url", "") if platform else ""
      platform_options = "".join(
          f'<option value="{p}" {"selected" if p == platform else ""}>{PLATFORM_CONFIG[p]["emoji"]} {PLATFORM_CONFIG[p]["display_name"]}</option>'
          for p in SUPPORTED_PLATFORMS
      )
      instr_html = instructions.replace("<b>","<strong>").replace("</b>","</strong>") if instructions else "Selecciona una plataforma."
      html = f"""<!DOCTYPE html>
  <html lang="es">
  <head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0">
  <title>ARIA - Conectar {display}</title>
  <style>*{{box-sizing:border-box;margin:0;padding:0}}body{{font-family:-apple-system,system-ui,sans-serif;background:#0f0f0f;color:#e0e0e0;min-height:100vh;display:flex;align-items:center;justify-content:center;padding:20px}}.card{{background:#1a1a1a;border:1px solid #333;border-radius:16px;padding:40px;max-width:600px;width:100%}}h1{{font-size:1.6rem;margin-bottom:8px;color:#fff}}.sub{{color:#888;margin-bottom:28px;font-size:.95rem}}label{{display:block;font-size:.85rem;color:#aaa;margin-bottom:6px;margin-top:20px}}select,textarea{{width:100%;background:#111;border:1px solid #333;border-radius:8px;padding:12px;color:#e0e0e0;font-size:.95rem;font-family:inherit}}select{{height:48px}}textarea{{height:220px;resize:vertical;font-family:'Courier New',monospace;font-size:.8rem}}.instr{{background:#111;border:1px solid #2a2a2a;border-radius:8px;padding:16px;margin-top:16px;font-size:.88rem;line-height:1.7;color:#ccc}}.btn{{display:block;width:100%;background:#6c63ff;color:#fff;border:none;border-radius:8px;padding:14px;font-size:1rem;font-weight:600;cursor:pointer;margin-top:24px}}.btn:hover{{background:#5a52d5}}.ok{{background:#0d2b0d;border:1px solid #2a5e2a;color:#4caf50;border-radius:8px;padding:16px;margin-top:16px;display:none}}.err{{background:#2b0d0d;border:1px solid #5e2a2a;color:#f44336;border-radius:8px;padding:16px;margin-top:16px;display:none}}.hl{{display:inline-block;margin-top:12px;color:#6c63ff;text-decoration:none;font-size:.85rem}}</style>
  </head>
  <body><div class="card">
  <h1>🤖 ARIA — Conectar Red Social</h1>
  <p class="sub">Sin API keys. Solo exporta las cookies de tu navegador.</p>
  <form id="f">
  <label>Plataforma</label>
  <select name="platform" id="ps" onchange="upd()">{platform_options}</select>
  <div class="instr" id="instr">{instr_html}</div>
  {"<a class='hl' href='" + help_url + "' target='_blank'>⬇️ Descargar Cookie-Editor para Chrome</a>" if help_url else ""}
  <label>JSON de Cookies (pegalo aqui)</label>
  <textarea name="cj" id="cj" placeholder='[{{"name":"auth_token","value":"..."}},...]' required></textarea>
  <input type="hidden" name="token" value="{valid_token}">
  <button type="submit" class="btn">✅ Guardar Sesion</button>
  </form>
  <div class="ok" id="ok"></div>
  <div class="err" id="err"></div>
  </div>
  <script>
  async function upd(){{const p=document.getElementById('ps').value;const r=await fetch('/social/platform-info?platform='+p);const d=await r.json();document.getElementById('instr').innerHTML=d.instructions||'';}}
  document.getElementById('f').addEventListener('submit',async(e)=>{{e.preventDefault();const btn=e.target.querySelector('.btn');btn.textContent='⏳...';btn.disabled=true;const fd=new FormData(e.target);const r=await fetch('/social/connect',{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify({{platform:fd.get('platform'),cookies_json:fd.get('cj'),token:fd.get('token')}})}});const d=await r.json();if(d.success){{document.getElementById('ok').textContent='✅ '+d.message;document.getElementById('ok').style.display='block';document.getElementById('err').style.display='none';btn.textContent='✅ Guardado';}}else{{document.getElementById('err').textContent='❌ '+d.error;document.getElementById('err').style.display='block';btn.textContent='✅ Guardar Sesion';btn.disabled=false;}}}});
  </script></body></html>"""
      return HTMLResponse(html)


  @app.post("/social/connect")
  async def social_connect_save(request: Request) -> JSONResponse:
      """Guarda cookies de sesion enviadas desde el formulario web o Telegram."""
      try:
          body = await request.json()
      except Exception:
          return JSONResponse({"success": False, "error": "JSON invalido"}, status_code=400)
      token = body.get("token", "")
      valid_token = settings.SOCIAL_CONNECT_TOKEN or "aria"
      if token != valid_token:
          return JSONResponse({"success": False, "error": "Token invalido"}, status_code=403)
      platform = body.get("platform", "").lower().strip()
      cookies_json_raw = body.get("cookies_json", "")
      from apps.core.tools.social_session import get_social_session_manager, SUPPORTED_PLATFORMS
      if platform not in SUPPORTED_PLATFORMS:
          return JSONResponse({"success": False, "error": f"Plataforma no soportada: {platform}"})
      mgr = get_social_session_manager()
      cookies = mgr.parse_cookies_json(cookies_json_raw)
      if not cookies:
          return JSONResponse({"success": False, "error": "No se pudo parsear el JSON. Usa Cookie-Editor -> Export as JSON."})
      validation = mgr.validate_cookies_for_platform(cookies, platform)
      if not validation.get("valid"):
          return JSONResponse({"success": False, "error": validation.get("error", "Cookies invalidas")})
      save_result = await mgr.save_session(platform, cookies)
      if not save_result.get("success"):
          return JSONResponse({"success": False, "error": save_result.get("error")})
      test = await mgr.test_session(platform)
      user_info = test.get("user_info", {}) if test.get("success") else {}
      user_str = ""
      if user_info:
          un = user_info.get("username") or user_info.get("firstName", "")
          if un:
              user_str = f" como @{un}"
      return JSONResponse({"success": True, "platform": platform, "message": f"Sesion de {platform.title()} guardada{user_str}.", "session_valid": test.get("success", False), "cookies_count": len(cookies)})


  @app.get("/social/platform-info")
  async def social_platform_info(platform: str = "") -> JSONResponse:
      """Info de una plataforma para el formulario web."""
      from apps.core.tools.social_session import PLATFORM_CONFIG
      cfg = PLATFORM_CONFIG.get(platform, {})
      if not cfg:
          return JSONResponse({"error": "Plataforma no encontrada"}, status_code=404)
      return JSONResponse({"platform": platform, "display_name": cfg["display_name"], "emoji": cfg["emoji"], "instructions": cfg.get("instructions","").replace("<b>","<strong>").replace("</b>","</strong>"), "required_cookies": cfg["required_cookies"], "help_url": cfg.get("help_url","")})


  @app.get("/social/sessions")
  async def social_sessions_list() -> JSONResponse:
      """Lista todas las sesiones activas de redes sociales."""
      from apps.core.tools.social_session import get_social_session_manager
      mgr = get_social_session_manager()
      sessions = await mgr.list_active_sessions()
      return JSONResponse({"success": True, "sessions": sessions, "total": len(sessions)})

  
# ── CHAT DIRECTO (API) ────────────────────────────────────

@app.post("/chat")
async def chat(request: ChatRequest) -> JSONResponse:
    """Chat directo con ARIA via REST API."""
    model_map = {
        "fast": AIModel.FAST,
        "strategy": AIModel.STRATEGY,
        "code": AIModel.CODE,
        "creative": AIModel.CREATIVE,
    }
    ai_model = model_map.get(request.model or "fast", AIModel.FAST)
    try:
        ai = await get_ai_client()
        response = await ai.complete(
            system=(
                f"Eres ARIA, sistema autónomo de IA que genera ingresos para {settings.OWNER_NAME}. "
                "Eres directa, eficiente y orientada a resultados. Responde en español."
            ),
            user=request.message,
            model=ai_model,
        )
        return JSONResponse({
            "response": response.content,
            "provider": response.provider.value if response.provider else None,
            "model": response.model,
            "latency_ms": response.latency_ms,
            "success": response.success,
        })
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


# ── DASHBOARD ─────────────────────────────────────────────

@app.get("/status")
async def status() -> JSONResponse:
    """Dashboard completo del sistema."""
    try:
        db = get_db()
        total_revenue = await db.get_total_revenue()
        revenue_by_platform = await db.get_revenue_by_platform()
        opportunities = await db.get_best_opportunities(limit=3)

        orch = await get_orchestrator()
        agent_statuses = orch.get_all_agent_statuses()

        jobs = [
            {
                "id": job.id,
                "next_run": job.next_run_time.isoformat() if job.next_run_time else None,
            }
            for job in scheduler.get_jobs()
        ]

        return JSONResponse({
            "system": "Aria OS v1.0",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "revenue": {
                "total_usd": total_revenue,
                "by_platform": revenue_by_platform,
            },
            "agents": agent_statuses,
            "scheduler": {"running": scheduler.running, "jobs": jobs},
            "top_opportunities": opportunities,
        })
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.get("/approvals")
async def get_approvals() -> JSONResponse:
    """Lista de aprobaciones pendientes."""
    try:
        db = get_db()
        result = db._client.table("approvals").select("*").eq("status", "pending").order("created_at", desc=True).limit(20).execute()
        return JSONResponse({"approvals": result.data or []})
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.post("/approvals/decide")
async def decide_approval(decision: ApprovalDecision) -> JSONResponse:
    """Aprobar o rechazar una acción pendiente."""
    if decision.decision not in ("approved", "rejected"):
        raise HTTPException(status_code=400, detail="decision debe ser 'approved' o 'rejected'")
    try:
        db = get_db()
        db._client.table("approvals").update({
            "status": decision.decision,
            "decided_at": datetime.now(timezone.utc).isoformat(),
        }).eq("id", decision.approval_id).execute()
        emoji = "✅" if decision.decision == "approved" else "❌"
        await send_telegram(
            f"{emoji} <b>Aprobación {decision.decision.upper()}</b>\n"
            f"ID: <code>{decision.approval_id}</code>"
        )
        return JSONResponse({"success": True, "decision": decision.decision})
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


# ── CONTROL DEL SCHEDULER ─────────────────────────────────

@app.post("/cycle/trigger")
async def trigger_cycle() -> JSONResponse:
    """Dispara un ciclo autónomo manualmente."""
    try:
        scheduler.add_job(autonomous_cycle_job, id="manual_cycle", replace_existing=True)
        await send_telegram("🚀 <b>Ciclo manual disparado</b> por el supervisor.")
        return JSONResponse({"success": True, "message": "Ciclo en ejecución"})
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.post("/cycle/pause")
async def pause_cycle() -> JSONResponse:
    """Pausa el scheduler."""
    try:
        scheduler.pause()
        await send_telegram("⏸ <b>Scheduler PAUSADO</b> por el supervisor.")
        return JSONResponse({"success": True, "status": "paused"})
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.post("/cycle/resume")
async def resume_cycle() -> JSONResponse:
    """Reanuda el scheduler."""
    try:
        scheduler.resume()
        await send_telegram("▶️ <b>Scheduler REANUDADO</b> por el supervisor.")
        return JSONResponse({"success": True, "status": "running"})
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


# ── DATOS ─────────────────────────────────────────────────

@app.get("/logs")
async def get_logs(limit: int = 50) -> JSONResponse:
    """Últimos logs del sistema."""
    try:
        db = get_db()
        result = db._client.table("system_logs").select("*").order("created_at", desc=True).limit(limit).execute()
        return JSONResponse({"logs": result.data or []})
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.get("/revenue")
async def get_revenue() -> JSONResponse:
    """Dashboard de ingresos."""
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
    """Métricas del cliente de IA."""
    try:
        ai = await get_ai_client()
        return JSONResponse(ai.get_health_report())
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.get("/market/opportunities")
async def get_opportunities(limit: int = 10) -> JSONResponse:
    """Mejores oportunidades de mercado detectadas."""
    try:
        db = get_db()
        opportunities = await db.get_best_opportunities(limit=limit)
        return JSONResponse({"opportunities": opportunities, "count": len(opportunities)})
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.get("/products")
async def get_products(limit: int = 20) -> JSONResponse:
    """Lista de productos creados por ARIA."""
    try:
        db = get_db()
        result = db._client.table("products").select("*").order("created_at", desc=True).limit(limit).execute()
        return JSONResponse({"products": result.data or [], "count": len(result.data or [])})
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.get("/websites")
async def get_websites(limit: int = 20) -> JSONResponse:
    """Lista de sitios web creados por ARIA."""
    try:
        db = get_db()
        result = db._client.table("websites").select("*").order("created_at", desc=True).limit(limit).execute()
        return JSONResponse({"websites": result.data or [], "count": len(result.data or [])})
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.post("/evolve")
async def trigger_evolution() -> JSONResponse:
    """Dispara el ciclo de auto-evolución manualmente."""
    try:
        import asyncio
        async def _run():
            from apps.core.agents.evolution_agent import EvolutionAgent
            agent = EvolutionAgent()
            await agent.start()
            result = await agent.run({"task": "manual_evolve"})
            await agent.stop()
            return result
        asyncio.create_task(_run())
        await send_telegram("🧬 <b>Auto-evolución disparada</b> manualmente.")
        return JSONResponse({"success": True, "message": "Evolución en progreso"})
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))




  # ── OAUTH REDES SOCIALES ─────────────────────────────────

@app.get("/auth/callback/{platform}")
async def social_auth_callback(platform: str, request: Request) -> JSONResponse:
    """
    Callback OAuth de redes sociales.
    Telegram envia al usuario el enlace, usuario autoriza, plataforma redirige aqui.
    """
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
            await send_telegram(
                f"\u2705 <b>{platform.title()} conectado</b>\n\n"
                f"Cuenta: @{username}\n"
                f"Ya tengo acceso completo.\n\n"
                f"Usa /publicar {platform} &lt;mensaje&gt; para publicar."
            )
            html = (
                f"<html><body style='font-family:sans-serif;text-align:center;padding:40px;background:#f8f9fa'>"
                f"<h2 style='color:#28a745'>\u2705 {platform.title()} conectado</h2>"
                f"<p>Cuenta <strong>@{username}</strong> vinculada a ARIA.</p>"
                f"<p style='color:#6c757d'>Puedes cerrar esta ventana.</p>"
                f"</body></html>"
            )
            from fastapi.responses import HTMLResponse
            return HTMLResponse(content=html)
        else:
            await send_telegram(f"\u26a0\ufe0f Obtuve tokens de {platform.title()} pero no pude guardarlos.")
            return JSONResponse({"ok": False, "error": "Error saving account"})

    except Exception as exc:
        logger.error("OAuth callback error for %s: %s", platform, exc)
        await send_telegram(f"Error en callback OAuth de {platform.title()}: {str(exc)[:100]}")
        return JSONResponse({"ok": False, "error": str(exc)}, status_code=500)


@app.get("/social/accounts")
async def list_social_accounts() -> JSONResponse:
    """Lista las cuentas de redes sociales conectadas."""
    try:
        from apps.core.tools.social_media import SocialMediaManager
        sm = SocialMediaManager()
        accounts = await sm.list_connected_accounts()
        return JSONResponse({"accounts": accounts, "count": len(accounts)})
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.post("/social/post")
async def social_post(request: Request) -> JSONResponse:
    """Publica contenido en una red social."""
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


# ── ENTRY POINT ───────────────────────────────────────────

if __name__ == "__main__":
    uvicorn.run(
        "apps.core.main:app",
        host="0.0.0.0",
        port=int(os.getenv("PORT", "8000")),
        reload=False,
    )
