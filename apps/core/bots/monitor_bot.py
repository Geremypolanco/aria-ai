"""
monitor_bot.py — Bot especializado en monitoreo del sistema.
Aria NO monitorea el sistema. Este bot lo hace y solo la llama cuando algo falla.
"""
from __future__ import annotations
import asyncio, logging, time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
import httpx
logger = logging.getLogger("aria.bots.monitor")

class MonitorBot:
    HEALTH_CHECKS = {
        "telegram_api": "https://api.telegram.org",
        "coingecko": "https://api.coingecko.com/api/v3/ping",
        "hackernews": "https://hacker-news.firebaseio.com/v0/topstories.json",
        "wikipedia": "https://en.wikipedia.org/api/rest_v1/",
        "exchangerate": "https://api.exchangerate-api.com/v4/latest/USD",
    }

    def __init__(self):
        self._checks: List[Dict] = []
        self._failures: Dict[str, int] = {}
        self._last_check: Optional[str] = None
        self._client = httpx.AsyncClient(timeout=8.0)

    async def check_all(self) -> Dict:
        results = {}
        tasks = {name: self._check_endpoint(url) for name, url in self.HEALTH_CHECKS.items()}
        responses = await asyncio.gather(*tasks.values(), return_exceptions=True)
        for name, response in zip(tasks.keys(), responses):
            if isinstance(response, Exception):
                results[name] = {"status": "error", "error": str(response)[:80], "latency_ms": None}
                self._failures[name] = self._failures.get(name, 0) + 1
            else:
                results[name] = response
                if response.get("status") == "ok":
                    self._failures[name] = 0
                else:
                    self._failures[name] = self._failures.get(name, 0) + 1
        config_results = await self._check_configured_apis()
        results.update(config_results)
        self._last_check = datetime.now(timezone.utc).isoformat()
        self._checks.append({"timestamp": self._last_check, "results": results})
        if len(self._checks) > 100:
            self._checks = self._checks[-50:]
        failures = [name for name, count in self._failures.items() if count > 0]
        logger.info("[MonitorBot] Check: %d servicios, %d fallos", len(results), len(failures))
        return {"success": True, "checked_at": self._last_check, "services": results,
                "failures": failures, "overall": "degraded" if failures else "healthy"}

    async def _check_endpoint(self, url: str) -> Dict:
        start = time.monotonic()
        try:
            r = await self._client.get(url)
            latency = int((time.monotonic() - start) * 1000)
            return {"status": "ok" if r.status_code < 400 else "error",
                    "http_status": r.status_code, "latency_ms": latency}
        except Exception as e:
            return {"status": "error", "error": str(e)[:100], "latency_ms": None}

    async def _check_configured_apis(self) -> Dict:
        try:
            from apps.core.config import settings
            apis = {
                "groq": bool(getattr(settings, "GROQ_API_KEY", None)),
                "openai": bool(getattr(settings, "OPENAI_API_KEY", None)),
                "supabase": bool(getattr(settings, "SUPABASE_URL", None)),
                "telegram": bool(getattr(settings, "TELEGRAM_TOKEN", None) or getattr(settings, "TELEGRAM_BOT_TOKEN", None)),
                "shopify": bool(getattr(settings, "SHOPIFY_URL", None) or getattr(settings, "SHOPIFY_SHOP_NAME", None)),
                "wolfram": bool(getattr(settings, "WOLFRAM_APP_ID", None)),
            }
            return {k: {"status": "configured" if v else "missing_key"} for k, v in apis.items()}
        except Exception as e:
            return {"config_check": {"status": "error", "error": str(e)}}

    def get_critical_failures(self) -> List[str]:
        return [name for name, count in self._failures.items() if count >= 2]

    async def alert_if_degraded(self) -> Optional[str]:
        failures = self.get_critical_failures()
        if not failures:
            return None
        return f"Sistema degradado: {', '.join(failures)} con fallos consecutivos."

    def status(self) -> Dict:
        return {"bot": "MonitorBot", "last_check": self._last_check,
                "critical_failures": self.get_critical_failures(), "failure_counts": self._failures,
                "total_checks_run": len(self._checks)}

_instance: Optional[MonitorBot] = None
def get_monitor_bot() -> MonitorBot:
    global _instance
    if _instance is None:
        _instance = MonitorBot()
    return _instance
