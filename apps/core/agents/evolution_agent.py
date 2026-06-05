"""
EvolutionAgent — Auto-mejora continua del sistema ARIA AI.

Analiza el rendimiento de todos los agentes cada 6 horas,
identifica qué estrategias generan más ingresos,
ajusta parámetros y escala lo que funciona.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Optional

from apps.core.agents.base_agent import BaseAgent
from apps.core.tools.ai_client import AIModel

logger = logging.getLogger("aria.evolution_agent")


class EvolutionAgent(BaseAgent):
    """
    Agente de auto-evolución. No genera revenue directamente —
    optimiza el sistema para que los demás agentes lo hagan mejor.
    """

    def __init__(self) -> None:
        super().__init__(
            name="evolution_agent",
            description="Auto-evolución — analiza métricas y optimiza estrategias",
            capabilities=[
                "performance_analysis",
                "strategy_optimization",
                "agent_tuning",
                "report_generation",
            ],
        )

    async def _execute(self, context: dict[str, Any]) -> dict[str, Any]:
        """Ciclo completo de auto-evolución."""
        logger.info("[EvolutionAgent] Iniciando ciclo de evolución...")

        # 1. Recolectar métricas
        metrics = await self._collect_all_metrics()

        # 2. Analizar con IA
        analysis = await self._analyze_performance(metrics)

        # 3. Identificar top performers y bottlenecks
        insights = await self._identify_insights(metrics, analysis)

        # 4. Generar recomendaciones accionables
        recommendations = await self._generate_recommendations(insights)

        # 5. Reportar a Telegram
        await self._send_evolution_report(metrics, insights, recommendations)

        return {
            "success": True,
            "agent": "evolution_agent",
            "metrics_analyzed": len(metrics),
            "insights": insights,
            "recommendations": recommendations[:3],
        }

    # ── RECOLECCIÓN DE MÉTRICAS ───────────────────────────

    async def _collect_all_metrics(self) -> dict[str, Any]:
        """Recolecta métricas de todos los agentes y el sistema."""
        metrics: dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "agents": {},
            "revenue": {},
            "cycles": {},
            "ai_health": {},
        }

        try:
            from apps.core.memory.supabase_client import get_db
            from apps.core.memory.redis_client import get_cache
            db = get_db()
            cache = get_cache()

            # Revenue por plataforma
            total_revenue = await db.get_total_revenue()
            by_platform = await db.get_revenue_by_platform()
            metrics["revenue"] = {
                "total_usd": total_revenue,
                "by_platform": by_platform,
                "best_platform": max(by_platform, key=by_platform.get, default="none") if by_platform else "none",
            }

            # Estado de ciclos
            try:
                cycles_result = db._client.table("autonomous_cycles").select("*").order("created_at", desc=True).limit(10).execute()
                cycles = cycles_result.data or []
                if cycles:
                    completed = [c for c in cycles if c.get("status") == "completed"]
                    metrics["cycles"] = {
                        "total_run": len(cycles),
                        "completed": len(completed),
                        "avg_tasks_completed": sum(c.get("tasks_completed", 0) for c in completed) / max(len(completed), 1),
                        "total_revenue_from_cycles": sum(c.get("revenue_generated", 0) for c in completed),
                    }
            except Exception:
                pass

            # Estado de agentes via Redis
            agent_names = ["orchestrator", "pm_agent", "cfo_agent", "dev_agent", "marketing_agent", "support_agent"]
            for name in agent_names:
                alive = await cache.is_agent_alive(name)
                status = await cache.get_agent_status(name)
                metrics["agents"][name] = {
                    "alive": alive,
                    "state": status.get("state", "unknown") if status else "offline",
                    "success_rate": status.get("metrics", {}).get("success_rate", 0) if status else 0,
                    "tasks_attempted": status.get("metrics", {}).get("tasks_attempted", 0) if status else 0,
                }

            # Salud del cliente IA
            try:
                from apps.core.tools.ai_client import get_ai_client
                ai = await get_ai_client()
                metrics["ai_health"] = ai.get_health_report()
            except Exception:
                pass

        except Exception as exc:
            logger.error("[EvolutionAgent] Error recolectando métricas: %s", exc)

        return metrics

    # ── ANÁLISIS ──────────────────────────────────────────

    async def _analyze_performance(self, metrics: dict[str, Any]) -> Optional[str]:
        """Analiza el rendimiento con IA."""
        summary = self._metrics_summary(metrics)
        return await self.think(
            system=(
                "Eres el sistema de auto-evolución de ARIA AI. Tu función es analizar el rendimiento "
                "del sistema y proponer mejoras concretas y accionables. Sé específico: menciona "
                "qué agentes están fallando, qué plataformas generan más revenue, y qué estrategias "
                "escalar. Responde en español. Máximo 400 palabras."
            ),
            user=f"Métricas actuales del sistema:\n{summary}\n\nAnálisis de rendimiento:",
            model=AIModel.STRATEGY,
        )

    async def _identify_insights(
        self, metrics: dict[str, Any], analysis: Optional[str]
    ) -> dict[str, Any]:
        """Identifica insights clave de las métricas."""
        agents = metrics.get("agents", {})
        revenue = metrics.get("revenue", {})
        ai_health = metrics.get("ai_health", {})

        # Top performers
        top_agents = [
            name for name, data in agents.items()
            if data.get("success_rate", 0) >= 80 and data.get("alive", False)
        ]

        # Agentes con problemas
        failing_agents = [
            name for name, data in agents.items()
            if data.get("success_rate", 100) < 50 or not data.get("alive", False)
        ]

        # AI provider más estable
        best_provider = "unknown"
        best_rate = 0
        for provider, data in ai_health.items():
            if isinstance(data, dict) and data.get("success_rate_pct", 0) > best_rate:
                best_rate = data["success_rate_pct"]
                best_provider = provider

        return {
            "top_performing_agents": top_agents,
            "failing_agents": failing_agents,
            "total_revenue_usd": revenue.get("total_usd", 0),
            "best_revenue_platform": revenue.get("best_platform", "none"),
            "best_ai_provider": best_provider,
            "system_health": "healthy" if not failing_agents else "degraded",
            "ai_analysis": (analysis or "")[:500],
        }

    async def _generate_recommendations(
        self, insights: dict[str, Any]
    ) -> list[str]:
        """Genera recomendaciones accionables basadas en los insights."""
        recs = []

        if insights.get("failing_agents"):
            failing = ", ".join(insights["failing_agents"])
            recs.append(f"🔧 Reiniciar agentes con fallos: {failing}")

        if insights.get("total_revenue_usd", 0) == 0:
            recs.append("🚀 Activar ciclo autónomo inmediatamente — sin revenue registrado todavía")

        best_platform = insights.get("best_revenue_platform", "none")
        if best_platform and best_platform != "none":
            recs.append(f"📈 Escalar estrategia en {best_platform} — es la plataforma más rentable")

        best_provider = insights.get("best_ai_provider", "unknown")
        if best_provider and best_provider != "unknown":
            recs.append(f"🤖 Priorizar {best_provider} como proveedor principal de IA")

        if insights.get("system_health") == "degraded":
            recs.append("⚠️ Sistema en estado degradado — revisar logs con /logs")

        if not recs:
            recs.append("✅ Sistema operando correctamente — continuar estrategia actual")

        return recs

    # ── REPORTE ───────────────────────────────────────────

    async def _send_evolution_report(
        self,
        metrics: dict[str, Any],
        insights: dict[str, Any],
        recommendations: list[str],
    ) -> None:
        """Envía el reporte de evolución a Telegram."""
        agents = metrics.get("agents", {})
        agent_lines = "\n".join(
            f"  {'🟢' if d.get('alive') else '🔴'} {n}: {d.get('success_rate', 0):.0f}% éxito"
            for n, d in agents.items()
        )

        rec_lines = "\n".join(f"  {r}" for r in recommendations)

        message = (
            f"🧬 <b>EVOLUCIÓN AUTOMÁTICA — ARIA AI</b>\n\n"
            f"💰 Revenue total: <b>${insights.get('total_revenue_usd', 0):.2f}</b>\n"
            f"🏆 Mejor plataforma: <b>{insights.get('best_revenue_platform', 'N/A')}</b>\n"
            f"🤖 Proveedor IA: <b>{insights.get('best_ai_provider', 'N/A')}</b>\n"
            f"❤️ Estado: <b>{insights.get('system_health', 'unknown').upper()}</b>\n\n"
            f"<b>Agentes:</b>\n{agent_lines}\n\n"
            f"<b>Análisis IA:</b>\n{insights.get('ai_analysis', 'N/A')[:300]}\n\n"
            f"<b>Recomendaciones:</b>\n{rec_lines}\n\n"
            f"🕐 {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}"
        )
        await self._send_telegram(message)

    # ── HELPERS ───────────────────────────────────────────

    def _metrics_summary(self, metrics: dict[str, Any]) -> str:
        """Convierte métricas a texto legible para la IA."""
        lines = [
            f"Revenue total: ${metrics.get('revenue', {}).get('total_usd', 0):.2f} USD",
            f"Mejor plataforma: {metrics.get('revenue', {}).get('best_platform', 'N/A')}",
            f"Ciclos ejecutados: {metrics.get('cycles', {}).get('total_run', 0)}",
        ]
        for name, data in metrics.get("agents", {}).items():
            lines.append(
                f"Agente {name}: alive={data.get('alive')}, "
                f"success_rate={data.get('success_rate', 0):.0f}%, "
                f"tareas={data.get('tasks_attempted', 0)}"
            )
        return "\n".join(lines)

    def can_handle(self, task: str) -> bool:
        keywords = ["evolve", "evolución", "optimizar", "rendimiento", "métricas", "performance"]
        return any(kw in task.lower() for kw in keywords)
