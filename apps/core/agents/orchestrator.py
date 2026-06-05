"""
orchestrator.py -- Director central de ARIA AI v4: Gobernador Economico Multi-Sectorial.

Mejoras v4:
- Registro dinamico de agentes via Supabase agent_registry
- Mapeo dinamico de sectores: instancia agentes segun sector y capacidades
- EconomicGovernorAgent integrado en el ciclo principal
- HumanResourcesAgent y ProcessOptimizationAgent orquestados por sector
- Descomposicion de objetivos globales en misiones inter-sectoriales
- Optimizacion de recursos globales con feedback loop
- ComplianceAgent como guardian de todas las misiones
- Metricas y auditorias por sector en Supabase
"""
from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timezone
from typing import Any, Optional

import httpx

from apps.core.agents.base_agent import BaseAgent
from apps.core.config import settings
from apps.core.tools.ai_client import AIModel, get_ai_client

logger = logging.getLogger("aria.orchestrator")
TELEGRAM_API = "https://api.telegram.org/bot"


class Orchestrator(BaseAgent):
    """
    Director central del sistema ARIA AI v4.
    Mision: gobernanza economica circular autonoma y generacion de ingresos reales.
    Motor IA: HuggingFace (primario) -> Groq -> OpenAI
    """

    def __init__(self) -> None:
        super().__init__(
            name="orchestrator",
            description="Director central -- gobernanza economica circular, coordinacion multi-sectorial y monetizacion autonoma",
            capabilities=["market_analysis", "planning", "coordination", "reporting", "sector_management"],
            sector_id="digital",
        )
        # Registro dinamico: name -> instancia de agente
        self._agents: dict[str, BaseAgent] = {}
        # Registro por sector: sector_id -> [agent_names]
        self._sector_agents: dict[str, list[str]] = {}
        self._cycle_count = 0
        self._feedback_history: list[dict] = []  # historial para aprendizaje

    async def _execute(self, context: dict[str, Any]) -> dict[str, Any]:
        return await self.run_cycle()

    # -- REGISTRO DINAMICO DE AGENTES ----------------------------------------

    async def register_agent(self, agent: BaseAgent) -> None:
        """Registra un agente en el Orchestrator y en Supabase agent_registry."""
        self._agents[agent.name] = agent
        sector = agent.sector_id
        if sector not in self._sector_agents:
            self._sector_agents[sector] = []
        if agent.name not in self._sector_agents[sector]:
            self._sector_agents[sector].append(agent.name)
        await agent.start()
        logger.info("[Orchestrator] Agente registrado: %s | Sector: %s", agent.name, sector)

    async def _initialize_core_agents(self) -> None:
        """Inicializa y registra todos los agentes nucleo del sistema."""
        from apps.core.agents.cfo_agent import CFOAgent
        from apps.core.agents.content_agent import ContentAgent
        from apps.core.agents.evolution_agent import EvolutionAgent
        from apps.core.agents.compliance_agent import ComplianceAgent
        from apps.core.agents.marketing_agent import MarketingAgent
        from apps.core.agents.economic_governor_agent import EconomicGovernorAgent
        from apps.core.agents.human_resources_agent import HumanResourcesAgent
        from apps.core.agents.process_optimization_agent import ProcessOptimizationAgent

        core_agents = [
            CFOAgent(),
            ContentAgent(),
            EvolutionAgent(),
            ComplianceAgent(),
            MarketingAgent(),
            EconomicGovernorAgent(),
            HumanResourcesAgent(sector_id="digital"),
            ProcessOptimizationAgent(sector_id="digital"),
        ]
        for agent in core_agents:
            await self.register_agent(agent)
        logger.info("[Orchestrator] %d agentes nucleo inicializados", len(core_agents))

    async def start(self) -> None:
        """Inicia el Orchestrator y registra todos los agentes nucleo."""
        await super().start()
        await self._initialize_core_agents()
        await self._sync_registry_from_supabase()

    async def _sync_registry_from_supabase(self) -> None:
        """Sincroniza el registry local con el de Supabase (para agentes externos/dinamicos)."""
        try:
            from apps.core.memory.supabase_client import get_db
            db = get_db()
            registry = await db.get_agent_registry()
            for entry in registry:
                name = entry.get("name")
                if name and name not in self._agents:
                    # Agente registrado en Supabase pero no en memoria local:
                    # se registra como placeholder hasta que se instancie
                    logger.info("[Orchestrator] Agente externo en registry: %s", name)
        except Exception as exc:
            logger.warning("[Orchestrator] No pudo sincronizar registry: %s", exc)

    # -- CICLO PRINCIPAL ------------------------------------------------------

    async def run_cycle(self) -> dict[str, Any]:
        """
        Ciclo autonomo completo v4:
        1. Inteligencia de mercado real
        2. Ciclo de gobernanza economica
        3. Plan de accion con IA (HF primario)
        4. Validacion de cumplimiento
        5. Ejecucion en paralelo por prioridad y sector
        6. Logging en Supabase + auditoria
        7. Reporte por Telegram
        8. Aprendizaje del ciclo para el siguiente
        """
        self._cycle_count += 1
        cycle_start = time.time()
        logger.info("[Orchestrator] --- CICLO #%d INICIADO ---", self._cycle_count)

        cycle_id = await self._log_cycle_start()

        # 1. Inteligencia de mercado REAL
        intelligence = await self._gather_market_intelligence()

        # 2. Ciclo de gobernanza economica (si el agente esta disponible)
        governance_result = await self._run_governance_cycle()

        # 3. Plan de monetizacion con IA
        plan = await self._generate_monetization_plan(intelligence)
        if not plan.get("missions"):
            plan = self._fallback_monetization_plan()

        # 4. Validar misiones con ComplianceAgent
        plan = await self._validate_missions_compliance(plan)

        # 5. Monetizacion siempre primero
        plan = self._enforce_monetization_priority(plan)

        logger.info(
            "[Orchestrator] Plan: %d misiones | foco: %s | sectores: %s",
            len(plan["missions"]),
            plan.get("focus", "monetizacion"),
            list(self._sector_agents.keys()),
        )

        # 6. Ejecutar misiones en paralelo por prioridad
        results = await self._execute_by_priority(plan["missions"])

        cycle_time = time.time() - cycle_start
        revenue_summary = self._extract_revenue_summary(results)

        # 7. Log resultado en Supabase + auditoria
        await self._log_cycle_result(cycle_id, plan, results, revenue_summary, cycle_time)
        await self._log_audit_trail(plan, results)

        # 8. Aprender del ciclo para el siguiente
        await self._record_feedback(plan, results, revenue_summary)

        # 9. Reporte Telegram
        await self._send_cycle_report(revenue_summary, cycle_time, governance_result)

        return {
            "cycle": self._cycle_count,
            "missions_executed": len(results),
            "revenue": revenue_summary,
            "governance": governance_result,
            "duration_s": round(cycle_time, 2),
        }

    # -- GOBERNANZA ECONOMICA -------------------------------------------------

    async def _run_governance_cycle(self) -> dict[str, Any]:
        """Ejecuta el ciclo de gobernanza economica si el agente esta disponible."""
        governor = self._agents.get("economic_governor")
        if not governor:
            return {"skipped": True, "reason": "EconomicGovernorAgent no registrado"}
        try:
            return await governor.run({"mode": "full_cycle"})
        except Exception as exc:
            logger.error("[Orchestrator] Error en governance cycle: %s", exc)
            return {"error": str(exc)}

    # -- MISIONES INTER-SECTORIALES -------------------------------------------

    async def decompose_global_objective(self, objective: str, target_sectors: list[str]) -> dict[str, Any]:
        """
        Descompone un objetivo de alto nivel en misiones inter-sectoriales.

        Ejemplo: 'optimizar cadena de suministro de alimentos en region X'
        -> missions para agriculture, logistics, distribution, banking
        """
        available_agents = {
            sector: self._sector_agents.get(sector, [])
            for sector in target_sectors
        }

        ai = get_ai_client()
        prompt = (
            f"Eres el Orchestrator de ARIA, el Gobernador Economico de una economia circular.\n\n"
            f"Objetivo global: {objective}\n"
            f"Sectores objetivo: {target_sectors}\n"
            f"Agentes disponibles por sector: {available_agents}\n\n"
            "Descompone el objetivo en misiones concretas y coordinadas entre sectores.\n"
            "Cada mision debe asignarse a un agente especifico y tener un orden de ejecucion.\n"
            "Responde SOLO con JSON:\n"
            '{"missions": [{"sector": "...", "agent": "...", "task": "...", '
            '"priority": 1, "depends_on": [], "expected_output": "..."}], '
            '"coordination_notes": "...", "estimated_impact": "..."}'
        )
        try:
            plan = await ai.complete_json(prompt, model=AIModel.STRATEGY)
            # Registrar en auditoria
            await self._audit_action(
                "decompose_global_objective",
                {"objective": objective, "sectors": target_sectors, "plan": plan},
                rationale=f"Descomposicion de objetivo global para sectores: {target_sectors}",
            )
            return plan
        except Exception as exc:
            logger.error("[Orchestrator] decompose_global_objective error: %s", exc)
            return {"missions": [], "error": str(exc)}

    async def expand_to_sector(self, sector_id: str, domain_context: dict) -> dict[str, Any]:
        """
        Expande ARIA a un nuevo sector economico:
        1. Habilita el sector en Supabase
        2. Instancia agentes especializados para ese sector
        3. Registra el sector en el ciclo economico
        """
        if sector_id not in BaseAgent.SUPPORTED_SECTORS:
            return {"success": False, "error": f"Sector '{sector_id}' no soportado"}

        logger.info("[Orchestrator] Expandiendo a sector: %s", sector_id)
        results = {"sector": sector_id, "agents_registered": []}

        # Instanciar agentes para el nuevo sector
        try:
            from apps.core.agents.human_resources_agent import HumanResourcesAgent
            from apps.core.agents.process_optimization_agent import ProcessOptimizationAgent

            sector_agents = [
                HumanResourcesAgent(sector_id=sector_id),
                ProcessOptimizationAgent(sector_id=sector_id),
            ]
            for agent in sector_agents:
                agent.domain_context = domain_context
                await self.register_agent(agent)
                results["agents_registered"].append(agent.name)

            # Habilitar sector en Supabase
            try:
                from apps.core.memory.supabase_client import get_db
                db = get_db()
                await db.enable_sector(sector_id, domain_context)
            except Exception as exc:
                logger.warning("[Orchestrator] No pudo habilitar sector en DB: %s", exc)

            results["success"] = True
            await self._audit_action(
                "expand_to_sector",
                {"sector_id": sector_id, "domain_context": domain_context},
                rationale=f"Expansion de ARIA al sector {sector_id}",
            )
            return results
        except Exception as exc:
            logger.error("[Orchestrator] Error expandiendo a sector %s: %s", sector_id, exc)
            return {"success": False, "error": str(exc)}

    # -- INTELIGENCIA DE MERCADO ----------------------------------------------

    async def _gather_market_intelligence(self) -> dict[str, Any]:
        """Recopila inteligencia de mercado real para todos los sectores activos."""
        intelligence: dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "sectors": settings.enabled_sectors_list,
        }
        try:
            from apps.core.tools.market_tools import get_market_signals
            signals = await get_market_signals()
            intelligence["signals"] = signals
        except Exception as exc:
            logger.warning("[Orchestrator] Market signals no disponibles: %s", exc)
            intelligence["signals"] = {}
        return intelligence

    # -- PLAN DE MONETIZACION -------------------------------------------------

    async def _generate_monetization_plan(self, intelligence: dict[str, Any]) -> dict[str, Any]:
        """Genera un plan de monetizacion con IA basado en la inteligencia de mercado."""
        ai = get_ai_client()
        available_capabilities = list(self._agents.keys())
        # Incluir feedback historico para aprendizaje
        feedback = self._feedback_history[-3:] if self._feedback_history else []
        prompt = (
            "Eres el planificador de ARIA AI, sistema de economia circular autonoma.\n\n"
            f"Agentes disponibles: {available_capabilities}\n"
            f"Sectores activos: {settings.enabled_sectors_list}\n"
            f"Inteligencia de mercado: {intelligence}\n"
            f"Feedback de ciclos anteriores: {feedback}\n\n"
            "Genera un plan de accion para este ciclo. Prioriza siempre la monetizacion.\n"
            "Responde SOLO con JSON:\n"
            '{"focus": "monetizacion", "missions": ['
            '{"agent": "...", "sector": "digital", "task": "...", "priority": 1, '
            '"context": {}, "estimated_revenue_usd": 0}]}'
        )
        try:
            return await ai.complete_json(prompt, model=AIModel.STRATEGY)
        except Exception as exc:
            logger.error("[Orchestrator] Error generando plan: %s", exc)
            return {"missions": []}

    def _fallback_monetization_plan(self) -> dict[str, Any]:
        """Plan de respaldo cuando la IA no esta disponible."""
        return {
            "focus": "monetizacion_basica",
            "missions": [
                {"agent": "content_agent", "sector": "digital", "task": "create_content",
                 "priority": 1, "context": {}, "estimated_revenue_usd": 0},
                {"agent": "cfo_agent", "sector": "digital", "task": "create_ebook",
                 "priority": 2, "context": {}, "estimated_revenue_usd": 5},
                {"agent": "evolution_agent", "sector": "digital", "task": "analyze_and_improve",
                 "priority": 3, "context": {"mode": "fix_bugs"}, "estimated_revenue_usd": 0},
            ],
        }

    def _enforce_monetization_priority(self, plan: dict) -> dict:
        """Asegura que las misiones de monetizacion van primero."""
        money_agents = {"cfo_agent", "marketing_agent"}
        missions = plan.get("missions", [])
        money = [m for m in missions if m.get("agent") in money_agents]
        others = [m for m in missions if m.get("agent") not in money_agents]
        plan["missions"] = money + others
        return plan

    # -- VALIDACION DE CUMPLIMIENTO -------------------------------------------

    async def _validate_missions_compliance(self, plan: dict) -> dict:
        """Pasa todas las misiones por el ComplianceAgent antes de ejecutar."""
        compliance = self._agents.get("compliance_agent")
        if not compliance:
            return plan
        valid_missions = []
        for mission in plan.get("missions", []):
            try:
                result = await compliance.run({"action": mission.get("task"), "context": mission})
                if result.get("approved", True):
                    valid_missions.append(mission)
                else:
                    logger.warning("[Orchestrator] Mision rechazada por Compliance: %s", mission.get("task"))
            except Exception:
                valid_missions.append(mission)  # Aprobar en caso de error de compliance
        plan["missions"] = valid_missions
        return plan

    # -- EJECUCION POR PRIORIDAD ----------------------------------------------

    async def _execute_by_priority(self, missions: list[dict]) -> list[dict[str, Any]]:
        """Ejecuta misiones en paralelo, respetando prioridades."""
        if not missions:
            return []
        # Agrupar por prioridad
        priority_groups: dict[int, list] = {}
        for m in missions:
            p = m.get("priority", 5)
            priority_groups.setdefault(p, []).append(m)

        all_results = []
        for priority in sorted(priority_groups.keys()):
            group = priority_groups[priority]
            tasks = [self._execute_mission(m) for m in group]
            group_results = await asyncio.gather(*tasks, return_exceptions=True)
            for m, r in zip(group, group_results):
                if isinstance(r, Exception):
                    all_results.append({"mission": m, "success": False, "error": str(r)})
                else:
                    all_results.append(r)
        return all_results

    async def _execute_mission(self, mission: dict) -> dict[str, Any]:
        """Ejecuta una mision individual delegando al agente correspondiente."""
        agent_name = mission.get("agent", "")
        agent = self._agents.get(agent_name)
        if not agent:
            return {"mission": mission, "success": False, "error": f"Agente '{agent_name}' no registrado"}
        try:
            context = {**mission.get("context", {}), "task": mission.get("task"), "sector_id": mission.get("sector", "digital")}
            result = await agent.run(context)
            return {"mission": mission, "result": result, "success": result.get("success", True)}
        except Exception as exc:
            logger.error("[Orchestrator] Error ejecutando mision %s/%s: %s", agent_name, mission.get("task"), exc)
            return {"mission": mission, "success": False, "error": str(exc)}

    # -- APRENDIZAJE ----------------------------------------------------------

    async def _record_feedback(self, plan: dict, results: list, revenue: dict) -> None:
        """Registra feedback del ciclo para mejorar el siguiente."""
        feedback = {
            "cycle": self._cycle_count,
            "missions_planned": len(plan.get("missions", [])),
            "missions_succeeded": sum(1 for r in results if r.get("success")),
            "revenue_usd": revenue.get("total", 0),
            "focus": plan.get("focus", ""),
        }
        self._feedback_history.append(feedback)
        # Mantener solo los ultimos 10 ciclos
        if len(self._feedback_history) > 10:
            self._feedback_history = self._feedback_history[-10:]

    # -- UTILIDADES -----------------------------------------------------------

    def _extract_revenue_summary(self, results: list[dict]) -> dict[str, Any]:
        total = 0.0
        by_agent: dict[str, float] = {}
        for r in results:
            res = r.get("result", {})
            amount = res.get("revenue_usd", 0) or res.get("revenue", {}).get("total", 0)
            agent = r.get("mission", {}).get("agent", "unknown")
            if isinstance(amount, (int, float)) and amount > 0:
                total += amount
                by_agent[agent] = by_agent.get(agent, 0) + amount
        return {"total": round(total, 4), "by_agent": by_agent}

    # -- LOGGING & AUDITORIA --------------------------------------------------

    async def _log_cycle_start(self) -> Optional[str]:
        try:
            from apps.core.memory.supabase_client import get_db
            db = get_db()
            result = db._client.table("cycles").insert({
                "cycle_number": self._cycle_count,
                "status": "running",
                "started_at": datetime.now(timezone.utc).isoformat(),
            }).execute()
            return result.data[0]["id"] if result.data else None
        except Exception:
            return None

    async def _log_cycle_result(self, cycle_id, plan, results, revenue, duration) -> None:
        if not cycle_id:
            return
        try:
            from apps.core.memory.supabase_client import get_db
            db = get_db()
            db._client.table("cycles").update({
                "status": "completed",
                "missions": plan.get("missions", []),
                "results": {"results": results[:10]},
                "revenue_usd": revenue.get("total", 0),
                "duration_ms": int(duration * 1000),
                "completed_at": datetime.now(timezone.utc).isoformat(),
            }).eq("id", cycle_id).execute()
        except Exception as exc:
            logger.warning("[Orchestrator] No pudo log cycle result: %s", exc)

    async def _log_audit_trail(self, plan: dict, results: list) -> None:
        """Registra la auditoria del ciclo para transparencia."""
        await self._audit_action(
            "cycle_execution",
            {"plan": plan.get("focus"), "missions": len(plan.get("missions", [])), "results_summary": len(results)},
            rationale=f"Ciclo #{self._cycle_count} de autonomia de ARIA",
        )

    async def _audit_action(self, action_type: str, detail: dict, rationale: str = "") -> None:
        try:
            from apps.core.memory.supabase_client import get_db
            db = get_db()
            await db.create_audit_entry({
                "agent_name": self.name,
                "sector_id": self.sector_id,
                "action_type": action_type,
                "action_detail": detail,
                "rationale": rationale,
                "reversible": True,
            })
        except Exception as exc:
            logger.debug("[Orchestrator] Audit log fallo: %s", exc)

    async def _send_cycle_report(self, revenue: dict, cycle_time: float, governance: dict) -> None:
        token = settings.telegram_token
        chat_id = settings.TELEGRAM_CHAT_ID
        if not token or not chat_id:
            return
        total = revenue.get("total", 0)
        by_agent = revenue.get("by_agent", {})
        breakdown = " | ".join(f"{a}: ${v:.2f}" for a, v in by_agent.items()) if by_agent else "Sin ingresos"
        gov_adj = governance.get("price_adjustments", {}).get("adjusted", []) if isinstance(governance, dict) else []
        msg = (
            f"<b>ARIA AI - Ciclo #{self._cycle_count}</b>\n\n"
            f"Ingresos: <b>${total:.4f}</b>\n"
            f"Desglose: {breakdown}\n"
            f"Duracion: {cycle_time:.1f}s\n"
            f"Sectores activos: {', '.join(settings.enabled_sectors_list)}\n"
            f"Ajustes de precio: {len(gov_adj)}\n"
            f"Proxima revision: en {settings.CYCLE_INTERVAL_MINUTES}min"
        )
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                await client.post(
                    f"{TELEGRAM_API}{token}/sendMessage",
                    json={"chat_id": chat_id, "text": msg, "parse_mode": "HTML"},
                )
        except Exception as exc:
            logger.error("[Orchestrator] Telegram error: %s", exc)
