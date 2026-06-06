"""
finance_bot.py — Bot especializado en monitoreo financiero.
Aria NO revisa mercados. Este bot los vigila y la alerta cuando importa.
"""
from __future__ import annotations
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
logger = logging.getLogger("aria.bots.finance")

class FinanceBot:
    def __init__(self):
        self._watchlist_stocks: List[str] = ["AAPL", "TSLA", "NVDA", "AMZN", "MSFT"]
        self._watchlist_crypto: List[str] = ["bitcoin", "ethereum", "solana"]
        self._alerts: List[Dict] = []
        self._alert_thresholds: Dict[str, float] = {}
        self._snapshot_count = 0

    async def snapshot(self) -> Dict:
        from apps.core.tools.knowledge_suite import get_knowledge_suite
        ks = get_knowledge_suite()
        result: Dict[str, Any] = {"timestamp": datetime.now(timezone.utc).isoformat()}
        stocks = {}
        for symbol in self._watchlist_stocks:
            r = ks.finance.get_ticker(symbol)
            if r.get("success"):
                d = r["data"]
                stocks[symbol] = {"price": d.get("price"), "change_pct": d.get("change_pct"), "name": d.get("name")}
        result["stocks"] = stocks
        crypto_r = ks.crypto.top_coins(limit=10)
        result["crypto"] = crypto_r.get("data", [])
        fx = ks.currency.compare("USD", ["EUR", "MXN", "COP", "BRL"])
        result["forex"] = fx.get("data", {})
        self._snapshot_count += 1
        alerts = await self._check_alerts(stocks, result.get("crypto", []))
        result["new_alerts"] = alerts
        logger.info("[FinanceBot] Snapshot #%d tomado", self._snapshot_count)
        return {"success": True, **result}

    async def _check_alerts(self, stocks: Dict, crypto: List) -> List[Dict]:
        triggered = []
        for symbol, data in stocks.items():
            chg = data.get("change_pct") or 0
            threshold = self._alert_thresholds.get(symbol, 3.0)
            if abs(chg) >= threshold:
                alert = {"type": "stock", "symbol": symbol, "change_pct": chg,
                         "direction": "↑" if chg > 0 else "↓", "price": data.get("price"),
                         "triggered_at": datetime.now(timezone.utc).isoformat()}
                triggered.append(alert)
                self._alerts.append(alert)
        for coin in crypto:
            chg = coin.get("change_24h") or 0
            threshold = self._alert_thresholds.get(coin.get("symbol", ""), 8.0)
            if abs(chg) >= threshold:
                alert = {"type": "crypto", "symbol": coin.get("symbol"), "name": coin.get("name"),
                         "change_pct": chg, "direction": "↑" if chg > 0 else "↓",
                         "price": coin.get("price"), "triggered_at": datetime.now(timezone.utc).isoformat()}
                triggered.append(alert)
                self._alerts.append(alert)
        return triggered

    def add_to_watchlist(self, symbol: str, asset_type: str = "stock", threshold_pct: float = 3.0) -> None:
        if asset_type == "stock" and symbol not in self._watchlist_stocks:
            self._watchlist_stocks.append(symbol.upper())
        elif asset_type == "crypto" and symbol not in self._watchlist_crypto:
            self._watchlist_crypto.append(symbol.lower())
        self._alert_thresholds[symbol] = threshold_pct
        logger.info("[FinanceBot] Watchlist: %s (%s) threshold=%.1f%%", symbol, asset_type, threshold_pct)

    def remove_from_watchlist(self, symbol: str) -> None:
        self._watchlist_stocks = [s for s in self._watchlist_stocks if s != symbol.upper()]
        self._watchlist_crypto = [s for s in self._watchlist_crypto if s != symbol.lower()]

    async def daily_summary(self) -> str:
        try:
            snap = await self.snapshot()
            from apps.core.tools.ai_client import AIModel, get_ai_client
            import json as _json
            ai = get_ai_client()
            response = await ai.complete(
                system="Eres un analista financiero. Resumen diario en 4-6 oraciones. Tono directo, datos concretos. Sin listas.",
                user=f"Datos:\n{_json.dumps(snap, ensure_ascii=False, default=str)[:1500]}",
                model=AIModel.FAST, max_tokens=250, agent_name="finance_bot_summary",
            )
            return response.content.strip() if response.success else "No se pudo generar resumen."
        except Exception as e:
            return f"Error: {e}"

    def get_alerts(self, limit: int = 10) -> List[Dict]:
        return self._alerts[-limit:]

    def status(self) -> Dict:
        return {"bot": "FinanceBot", "watchlist_stocks": self._watchlist_stocks,
                "watchlist_crypto": self._watchlist_crypto, "snapshots_taken": self._snapshot_count,
                "total_alerts": len(self._alerts), "recent_alerts": self._alerts[-3:]}

_instance: Optional[FinanceBot] = None
def get_finance_bot() -> FinanceBot:
    global _instance
    if _instance is None:
        _instance = FinanceBot()
    return _instance
