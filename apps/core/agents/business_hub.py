"""
BusinessHub — Central router for ARIA AI business agents.

Sintra AI-style architecture: each agent is an autonomous specialist.
The Hub receives a mission, analyzes it, activates the right agent,
and can chain multiple agents for complex missions.

Available agents:
  ceo        — Strategy, executive decisions, delegation
  marketing  — SEO, content, campaigns, social media
  sales      — Revenue, products, Shopify/Stripe/Gumroad
  developer  — Code, deploy, autonomous debugging (Claude Code-level)
  research   — Deep market and internet research
  content    — Articles, newsletters, multi-platform publishing
  finance    — Revenue tracking, P&L, forecasting
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

logger = logging.getLogger("aria.business_hub")

# Name → class mapping
_AGENT_REGISTRY: dict[str, str] = {
    "ceo": "apps.core.agents.business.ceo_agent.CEOAgent",
    "marketing": "apps.core.agents.business.marketing_agent.MarketingAgent",
    "sales": "apps.core.agents.business.sales_agent.SalesAgent",
    "developer": "apps.core.agents.business.developer_agent.DeveloperAgent",
    "dev": "apps.core.agents.business.developer_agent.DeveloperAgent",
    "research": "apps.core.agents.business.research_agent.ResearchAgent",
    "content": "apps.core.agents.business.content_agent.ContentAgent",
    "finance": "apps.core.agents.business.finance_agent.FinanceAgent",
    "cfo": "apps.core.agents.business.finance_agent.FinanceAgent",
    "cmo": "apps.core.agents.business.marketing_agent.MarketingAgent",
    "cto": "apps.core.agents.business.developer_agent.DeveloperAgent",
}

# Keywords for auto-routing (bilingual — matched against user input, left untranslated)
_ROUTING_KEYWORDS: dict[str, list[str]] = {
    "developer": [
        "código",
        "code",
        "bug",
        "api",
        "deploy",
        "programa",
        "script",
        "función",
        "app",
        "software",
        "test",
        "build",
        "error",
        "debug",
        "fix",
    ],
    "marketing": [
        "marketing",
        "seo",
        "contenido",
        "viral",
        "campaña",
        "redes",
        "social",
        "instagram",
        "linkedin",
        "twitter",
        "tiktok",
        "blog",
        "keyword",
    ],
    "sales": [
        "vender",
        "producto",
        "precio",
        "stripe",
        "shopify",
        "gumroad",
        "revenue",
        "checkout",
        "tienda",
        "pago",
        "cobrar",
        "lanzar",
    ],
    "research": [
        "investiga",
        "analiza",
        "mercado",
        "competidor",
        "tendencia",
        "datos",
        "reporte",
        "estudio",
        "noticias",
        "benchmark",
    ],
    "content": [
        "artículo",
        "newsletter",
        "publicar",
        "medium",
        "devto",
        "hashnode",
        "email",
        "escribir",
        "post",
    ],
    "finance": [
        "finanzas",
        "revenue",
        "costos",
        "ganancia",
        "p&l",
        "forecast",
        "métricas",
        "kpi",
        "dinero",
    ],
    "ceo": [
        "estrategia",
        "plan",
        "negocio",
        "empresa",
        "misión",
        "objetivo",
        "prioridades",
        "decisión",
    ],
}


class BusinessHub:
    """
    Intelligent router for business agents.
    Can activate a specific agent or auto-detect the best agent.
    """

    async def dispatch(
        self,
        agent_name: str,
        mission: str,
        context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """
        Activates a specific agent with the given mission.
        If agent_name is "auto", automatically detects the best agent.
        """
        if not context:
            context = {}
        context["mission"] = mission

        # Auto-routing
        if agent_name in ("auto", ""):
            agent_name = self._route(mission)

        agent_key = agent_name.lower().strip()
        agent_class_path = _AGENT_REGISTRY.get(agent_key)

        if not agent_class_path:
            return {
                "success": False,
                "error": f"Agent '{agent_name}' not found. Available: {list(_AGENT_REGISTRY.keys())}",
            }

        try:
            agent = self._load_agent(agent_class_path)
            logger.info("[BusinessHub] Dispatching to %s: %s", agent_key, mission[:80])
            # BaseAgent's public entry point is run() (circuit breaker +
            # metrics wrapper around _execute()) — there is no execute()
            # method on any agent class. Calling it unconditionally raised
            # AttributeError for every single dispatch, meaning
            # run_business_agent / launch_niche's agent hooks / anything
            # routed through this method has never actually worked.
            result = await agent.run(context)
            return result
        except Exception as exc:
            logger.error("[BusinessHub] dispatch error agent=%s: %s", agent_key, exc, exc_info=True)
            return {"success": False, "agent": agent_key, "error": str(exc)}

    async def run_full_business_cycle(
        self, mission: str, agents: list[str] | None = None
    ) -> dict[str, Any]:
        """
        Runs multiple agents in parallel for a complete business mission.
        By default activates CEO + Research + Marketing + Sales.
        """
        if not agents:
            agents = ["ceo", "research", "marketing"]

        context = {"mission": mission, "auto_publish": False}

        tasks = [(name, self.dispatch(name, mission, dict(context))) for name in agents]
        results_list = await asyncio.gather(*[task for _, task in tasks], return_exceptions=True)

        results: dict[str, Any] = {
            "mission": mission,
            "agents_activated": agents,
        }
        for name, result in zip(agents, results_list, strict=False):
            if isinstance(result, Exception):
                results[name] = {"success": False, "error": str(result)}
            else:
                results[name] = result

        return results

    def _route(self, mission: str) -> str:
        """Auto-detects the most appropriate agent for a mission."""
        mission_lower = mission.lower()
        scores: dict[str, int] = dict.fromkeys(_ROUTING_KEYWORDS, 0)

        for agent, keywords in _ROUTING_KEYWORDS.items():
            for kw in keywords:
                if kw in mission_lower:
                    scores[agent] += 1

        best = max(scores, key=lambda k: scores[k])
        if scores[best] == 0:
            return "ceo"  # default to CEO if no match
        logger.info(
            "[BusinessHub] Auto-routed '%s' → %s (score=%d)", mission[:50], best, scores[best]
        )
        return best

    def _load_agent(self, class_path: str) -> Any:
        """Imports and instantiates the agent dynamically."""
        module_path, class_name = class_path.rsplit(".", 1)
        import importlib

        module = importlib.import_module(module_path)
        cls = getattr(module, class_name)
        return cls()

    def list_agents(self) -> dict[str, str]:
        """Returns the list of available agents with a description."""
        descriptions = {
            "ceo": "Executive strategy, decisions, and delegation",
            "marketing": "SEO, social media, campaigns, and growth",
            "sales": "Revenue: products, payments, conversion",
            "developer": "Code, deploy, autonomous debugging",
            "research": "Deep market and internet research",
            "content": "Articles, newsletters, multi-platform publishing",
            "finance": "Revenue tracking, P&L, and forecasting",
        }
        return descriptions


# Singleton
_hub: BusinessHub | None = None


def get_business_hub() -> BusinessHub:
    global _hub
    if _hub is None:
        _hub = BusinessHub()
    return _hub
