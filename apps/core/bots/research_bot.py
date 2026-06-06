"""
research_bot.py — Bot especializado en investigación continua.

Aria NO investiga. Este bot investiga y le entrega resultados masticados.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger("aria.bots.research")

DEFAULT_TOPICS = [
    "inteligencia artificial 2025",
    "oportunidades de negocio digital",
    "tendencias e-commerce",
    "startups latinoamerica",
    "crypto mercado",
]


class ResearchBot:
    """Bot autónomo de investigación y gestión del conocimiento."""

    def __init__(self):
        self._cache: Dict[str, Dict] = {}
        self._research_count = 0
        self._watched_topics: List[str] = list(DEFAULT_TOPICS)

    async def research(self, query: str, depth: str = "quick", save_to_memory: bool = True) -> Dict:
        """Investiga un tema y devuelve resumen estructurado."""
        try:
            from apps.core.tools.knowledge_suite import get_knowledge_suite
            ks = get_knowledge_suite()
            results: Dict[str, Any] = {"query": query, "depth": depth}

            web = ks.web.search(query, max_results=6)
            results["web"] = web.get("data", [])[:5]

            wiki = ks.wikipedia.summary(query, sentences=4)
            results["wikipedia"] = wiki.get("data") if wiki.get("success") else None

            news = ks.news.hackernews_top(limit=5)
            results["hackernews"] = news.get("data", [])

            if depth == "deep":
                arxiv = ks.arxiv.search(query, max_results=4)
                results["papers"] = arxiv.get("data", [])
                reddit = ks.reddit.search(query, limit=5)
                results["reddit"] = reddit.get("data", [])

            summary = await self._synthesize(query, results)
            results["summary"] = summary
            results["researched_at"] = datetime.now(timezone.utc).isoformat()
            self._cache[query] = results
            self._research_count += 1

            if save_to_memory and summary:
                try:
                    doc_id = f"research:{query[:40]}:{datetime.now(timezone.utc).strftime('%Y%m%d')}"
                    ks.vector_memory.add_document(
                        doc_id=doc_id,
                        text=f"INVESTIGACIÓN: {query}\n\n{summary}",
                        metadata={"type": "research", "query": query, "depth": depth},
                    )
                except Exception:
                    pass

            logger.info("[ResearchBot] Investigado: %s (depth=%s)", query[:50], depth)
            return {"success": True, **results}

        except Exception as e:
            logger.error("[ResearchBot] Error en research: %s", e)
            return {"success": False, "error": str(e), "query": query}

    async def _synthesize(self, query: str, data: Dict) -> str:
        try:
            from apps.core.tools.ai_client import AIModel, get_ai_client
            ai = get_ai_client()
            web_titles = [r.get("title", "") for r in data.get("web", [])[:4]]
            wiki_text = ""
            if data.get("wikipedia"):
                wiki_text = data["wikipedia"].get("summary", "")[:300]
            raw = (
                f"Tema: {query}\n\nWikipedia: {wiki_text}\n\n"
                f"Resultados web: {'; '.join(web_titles)}\n"
            )
            response = await ai.complete(
                system=(
                    "Sintetizas investigaciones de manera clara y directa. "
                    "Da un resumen de 3-5 oraciones con los puntos más relevantes. "
                    "Si hay oportunidades de negocio, menciónalas. Sin listas, texto fluido."
                ),
                user=raw,
                model=AIModel.FAST, max_tokens=250, agent_name="research_bot_synthesis",
            )
            return response.content.strip() if response.success else ""
        except Exception:
            return ""

    async def watch_topics(self) -> Dict:
        tasks = [self.research(topic, depth="quick") for topic in self._watched_topics]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        successful = [r for r in results if isinstance(r, dict) and r.get("success")]
        return {"success": True, "researched": len(successful), "failed": len(results) - len(successful)}

    def add_topic(self, topic: str) -> None:
        if topic not in self._watched_topics:
            self._watched_topics.append(topic)

    def get_cached(self, query: str) -> Optional[Dict]:
        return self._cache.get(query)

    def status(self) -> Dict:
        return {
            "bot": "ResearchBot",
            "research_count": self._research_count,
            "cached_topics": len(self._cache),
            "watched_topics": self._watched_topics,
        }


_instance: Optional[ResearchBot] = None

def get_research_bot() -> ResearchBot:
    global _instance
    if _instance is None:
        _instance = ResearchBot()
    return _instance
