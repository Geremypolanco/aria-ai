"""
digest_bot.py — Bot que compila y entrega el resumen diario de todos los bots.
Aria NO recopila datos de otros bots. Este bot hace el trabajo de integración.
"""
from __future__ import annotations
import asyncio, logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
logger = logging.getLogger("aria.bots.digest")

class DigestBot:
    def __init__(self):
        self._digests: List[Dict] = []
        self._digest_count = 0

    async def collect_all(self) -> Dict:
        data: Dict[str, Any] = {}
        bots_to_check = [
            ("content", "apps.core.bots.content_bot", "get_content_bot"),
            ("research", "apps.core.bots.research_bot", "get_research_bot"),
            ("opportunity", "apps.core.bots.opportunity_bot", "get_opportunity_bot"),
            ("finance", "apps.core.bots.finance_bot", "get_finance_bot"),
            ("monitor", "apps.core.bots.monitor_bot", "get_monitor_bot"),
            ("shopify", "apps.core.bots.shopify_bot", "get_shopify_bot"),
            ("email", "apps.core.bots.email_bot", "get_email_bot"),
            ("social", "apps.core.bots.social_bot", "get_social_bot"),
            ("scheduler", "apps.core.bots.scheduler_bot", "get_scheduler_bot"),
        ]
        for name, module_path, getter_name in bots_to_check:
            try:
                import importlib
                mod = importlib.import_module(module_path)
                getter = getattr(mod, getter_name)
                bot = getter()
                data[name] = bot.status()
            except Exception as e:
                data[name] = {"error": str(e)}
        return data

    async def run_morning_scan(self) -> Dict:
        results: Dict[str, Any] = {}
        async def run_research():
            from apps.core.bots.research_bot import get_research_bot
            return await get_research_bot().watch_topics()
        async def run_opportunities():
            from apps.core.bots.opportunity_bot import get_opportunity_bot
            return await get_opportunity_bot().scan()
        async def run_finance():
            from apps.core.bots.finance_bot import get_finance_bot
            return await get_finance_bot().snapshot()
        async def run_social():
            from apps.core.bots.social_bot import get_social_bot
            return await get_social_bot().get_trending()
        async def run_monitor():
            from apps.core.bots.monitor_bot import get_monitor_bot
            return await get_monitor_bot().check_all()
        tasks = {"research": run_research, "opportunities": run_opportunities,
                 "finance": run_finance, "social": run_social, "monitor": run_monitor}
        gathered = await asyncio.gather(*[fn() for fn in tasks.values()], return_exceptions=True)
        for name, result in zip(tasks.keys(), gathered):
            results[name] = result if not isinstance(result, Exception) else {"error": str(result)}
        return {"success": True, "scan_results": results, "run_at": datetime.now(timezone.utc).isoformat()}

    async def generate_digest(self, scan_results: Optional[Dict] = None) -> str:
        if not scan_results:
            scan_results = await self.run_morning_scan()
        try:
            from apps.core.tools.ai_client import AIModel, get_ai_client
            import json as _json
            ai = get_ai_client()
            hour = datetime.now(timezone.utc).hour - 4
            period = "mañana" if hour < 12 else ("tarde" if hour < 19 else "noche")
            response = await ai.complete(
                system=(f"Sintetizas reportes de bots de IA en un resumen de {period} para la dueña del sistema. "
                        f"Tono: conversacional, cálido, directo. 5-8 oraciones. "
                        f"Destaca: oportunidades encontradas, alertas importantes, métricas clave. Sin listas."),
                user=_json.dumps(scan_results, ensure_ascii=False, default=str)[:2000],
                model=AIModel.FAST, max_tokens=350, agent_name="digest_bot_summary",
            )
            digest = response.content.strip() if response.success else "No se pudo generar el resumen."
            self._digests.append({"digest": digest, "generated_at": datetime.now(timezone.utc).isoformat(), "period": period})
            self._digest_count += 1
            return digest
        except Exception as e:
            logger.error("[DigestBot] Error generando digest: %s", e)
            return f"Error al generar resumen: {e}"

    async def send_to_aria(self) -> bool:
        try:
            scan = await self.run_morning_scan()
            digest = await self.generate_digest(scan)
            from apps.core.tools.telegram_bot import get_bot
            from apps.core.config import settings
            bot = get_bot()
            if settings.TELEGRAM_CHAT_ID:
                await bot._send(str(settings.TELEGRAM_CHAT_ID), digest)
                logger.info("[DigestBot] Digest enviado a Aria")
                return True
            return False
        except Exception as e:
            logger.error("[DigestBot] Error enviando digest: %s", e)
            return False

    def status(self) -> Dict:
        return {"bot": "DigestBot", "digests_generated": self._digest_count,
                "last_digest": self._digests[-1].get("generated_at") if self._digests else None}

_instance: Optional[DigestBot] = None
def get_digest_bot() -> DigestBot:
    global _instance
    if _instance is None:
        _instance = DigestBot()
    return _instance
