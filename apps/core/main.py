"""
Aria AI — Sistema Operativo Núcleo (Edición Compacta Móvil)
"""
import os, sys, logging, httpx, uvicorn
from datetime import datetime, timezone
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

from apps.core.config import settings
from apps.core.tools.ai_client import get_ai_client, AIModel
from apps.core.memory.supabase_client import get_db
from apps.core.memory.redis_client import get_cache

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s]: %(message)s", handlers=[logging.StreamHandler(sys.stdout)])
logger = logging.getLogger("aria.core")
scheduler = AsyncIOScheduler(timezone="UTC")

TELEGRAM_API = "https://api.telegram.org/bot"

async def send_telegram(message: str) -> bool:
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            res = await client.post(
                f"{TELEGRAM_API}{settings.TELEGRAM_TOKEN}/sendMessage",
                json={"chat_id": settings.TELEGRAM_CHAT_ID, "text": message, "parse_mode": "HTML"}
            )
            return res.status_code == 200
    except Exception as e:
        logger.error(f"Telegram fallo en silencio: {e}")
        return False

async def autonomous_cycle_job():
    logger.info("Aria: Iniciando ciclo de ejecucion autonomo...")
    cache = get_cache()
    db = get_db()

    locked = await cache.acquire_lock("autonomous_cycle", ttl_seconds=300)
    if not locked: return

    try:
        await cache.set_agent_heartbeat("orchestrator")
        ai = await get_ai_client()
        response = await ai.complete(
            system="Eres Aria, IA de negocios del Señor Polanco. Encuentra la accion de mayor ROI actual.",
            user="Analiza tendencias globales y sugiere el mejor nicho electronico para monetizar hoy.",
            model=AIModel.STRATEGY,
            agent_name="orchestrator"
        )
        if response.success:
            await db.log_info(f"Ciclo completado: {response.content[:200]}", "orchestrator")
            logger.info("Ciclo de IA completado exitosamente.")
    except Exception as e:
        logger.error(f"Error en ciclo de Aria: {e}")
    finally:
        await cache.release_lock("autonomous_cycle")

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Aria OS encendiendo...")
    await send_telegram("⚡ <b>SISTEMA OPERATIVO ARIA ONLINE</b>\nBienvenido, Señor Polanco. Núcleo optimizado y listo.")

    interval = int(os.getenv("CYCLE_INTERVAL_MINUTES", "60"))
    scheduler.add_job(autonomous_cycle_job, IntervalTrigger(minutes=interval), id="cycle")
    scheduler.start()
    yield
    scheduler.shutdown()

app = FastAPI(title="Aria Core", lifespan=lifespan)

@app.get("/")
async def root():
    return JSONResponse(content={"status": "online", "system": "Aria OS Compact"}, status_code=200)

if __name__ == "__main__":
    uvicorn.run("apps.core.main:app", host="0.0.0.0", port=int(os.getenv("PORT", "8000")), reload=False)
