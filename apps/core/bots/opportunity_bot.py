"""
opportunity_bot.py — Bot especializado en detección de oportunidades de negocio.

Aria NO busca oportunidades. Este bot las trae servidas.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Dict, List, Optional

logger = logging.getLogger("aria.bots.opportunity")


class OpportunityBot:
    """Bot autónomo de detección y puntuación de oportunidades de negocio."""

    def __init__(self):
        self._found: List[Dict] = []
        self._scan_count = 0

    async def scan(self, focus: str = "general", min_score: float = 0.5) -> Dict:
        """Escanea múltiples fuentes y devuelve oportunidades puntuadas."""
        try:
            from apps.core.tools.knowledge_suite import get_knowledge_suite
            ks = get_knowledge_suite()
            raw_signals: List[str] = []

            hn = ks.news.hackernews_top(limit=15)
            for item in hn.get("data", []):
                title = item.get("title", "")
                if any(kw in title.lower() for kw in ["show hn", "ask hn", "launch", "side project", "saas"]):
                    raw_signals.append(f"HN: {title}")

            reddit_ent = ks.reddit.subreddit_hot("Entrepreneur", limit=10)
            for post in reddit_ent.get("data", []):
                raw_signals.append(f"Reddit/Entrepreneur: {post.get('title', '')}")

            reddit_saas = ks.reddit.subreddit_hot("SaaS", limit=8)
            for post in reddit_saas.get("data", []):
                raw_signals.append(f"Reddit/SaaS: {post.get('title', '')}")

            focus_query = focus if focus != "general" else "oportunidades de negocio 2025 tendencias"
            web = ks.web.search(focus_query, max_results=5)
            for item in web.get("data", []):
                raw_signals.append(f"Web: {item.get('title', '')}")

            if not raw_signals:
                return {"success": True, "opportunities": [], "message": "Sin señales nuevas"}

            opportunities = await self._analyze_signals(raw_signals, focus, min_score)
            self._found.extend(opportunities)
            self._scan_count += 1

            logger.info("[OpportunityBot] Scan completado: %d oportunidades", len(opportunities))
            return {
                "success": True,
                "scan_count": self._scan_count,
                "signals_analyzed": len(raw_signals),
                "opportunities": opportunities,
                "scanned_at": datetime.now(timezone.utc).isoformat(),
            }

        except Exception as e:
            logger.error("[OpportunityBot] Error en scan: %s", e)
            return {"success": False, "error": str(e)}

    async def _analyze_signals(self, signals: List[str], focus: str, min_score: float) -> List[Dict]:
        try:
            from apps.core.tools.ai_client import AIModel, get_ai_client
            import json as _json
            ai = get_ai_client()
            signals_text = "\n".join(signals[:30])
            response = await ai.complete(
                system=(
                    "Eres un analista de oportunidades de negocio. "
                    "Analiza las señales del mercado y extrae oportunidades concretas y accionables. "
                    "Para cada oportunidad devuelve JSON con: "
                    "{title, category, description, score(0-1), time_to_market, effort, potential_revenue}. "
                    f"Devuelve un JSON array. Mínimo score aceptable: {min_score}."
                ),
                user=f"Foco: {focus}\n\nSeñales del mercado:\n{signals_text}",
                model=AIModel.FAST, max_tokens=800,
                json_mode=True, agent_name="opportunity_bot_analyze",
            )
            if not response.success:
                return []
            content = response.content
            if isinstance(content, str):
                try:
                    content = _json.loads(content)
                except Exception:
                    return []
            if isinstance(content, list):
                return [o for o in content if isinstance(o, dict) and o.get("score", 0) >= min_score]
            if isinstance(content, dict) and "opportunities" in content:
                return [o for o in content["opportunities"] if o.get("score", 0) >= min_score]
            return []
        except Exception as e:
            logger.error("[OpportunityBot] Error analizando señales: %s", e)
            return []

    async def top_opportunities(self, limit: int = 5) -> List[Dict]:
        all_opps = sorted(self._found, key=lambda x: x.get("score", 0), reverse=True)
        return all_opps[:limit]

    async def opportunity_report(self) -> str:
        top = await self.top_opportunities(5)
        if not top:
            return "No hay oportunidades puntuadas todavía."
        try:
            from apps.core.tools.ai_client import AIModel, get_ai_client
            import json as _json
            ai = get_ai_client()
            response = await ai.complete(
                system="Redacta un reporte breve (5-8 oraciones) de oportunidades de negocio. Directo y accionable. Sin bullets.",
                user=f"Oportunidades:\n{_json.dumps(top, ensure_ascii=False, indent=2)}",
                model=AIModel.FAST, max_tokens=300, agent_name="opportunity_bot_report",
            )
            return response.content.strip() if response.success else str(top)
        except Exception:
            return str(top)

    def status(self) -> Dict:
        return {
            "bot": "OpportunityBot",
            "scan_count": self._scan_count,
            "opportunities_found": len(self._found),
            "top_score": max((o.get("score", 0) for o in self._found), default=0),
        }


_instance: Optional[OpportunityBot] = None

def get_opportunity_bot() -> OpportunityBot:
    global _instance
    if _instance is None:
        _instance = OpportunityBot()
    return _instance
