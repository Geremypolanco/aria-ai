"""
process_optimization_agent.py -- ARIA AI Agente de Optimizacion de Procesos v1.

Analiza y optimiza procesos operativos en cualquier sector de la economia circular:
- Analisis de eficiencia de procesos con IA
- Deteccion de cuellos de botella usando datos reales
- Propuesta y seguimiento de mejoras
- Integracion con IoT/sensores y ERPs externos
- Simulaciones de escenarios para validar optimizaciones

Principio: NINGUNA funcion retorna datos simulados.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

from apps.core.agents.base_agent import BaseAgent
from apps.core.config import settings
from apps.core.tools.ai_client import AIModel

logger = logging.getLogger("aria.process_opt")


class ProcessOptimizationAgent(BaseAgent):
    """
    Optimizador de procesos operativos para la economia circular de ARIA.
    Opera en cualquier sector usando datos reales de IoT, ERP y logs de sistema.
    """

    def __init__(self, sector_id: str = "digital") -> None:
        super().__init__(
            name="process_optimization_agent",
            description="Optimizacion de procesos: eficiencia, cuellos de botella, automatizacion, IoT/ERP",
            capabilities=[
                "process_analysis", "bottleneck_detection", "workflow_optimization",
                "iot_integration", "erp_integration", "simulation",
                "automation_design", "cost_reduction", "supabase",
            ],
            sector_id=sector_id,
        )

    async def _execute(self, context: dict[str, Any]) -> dict[str, Any]:
        mode = context.get("mode", "full_analysis")
        if mode == "analyze_process":
            return await self.analyze_process(context.get("process_id"))
        if mode == "optimize_supply_chain":
            return await self.optimize_supply_chain(context.get("chain_id"))
        if mode == "iot_scan":
            return await self.collect_iot_data()
        if mode == "propose_automation":
            return await self.propose_automation(context.get("process_id"))
        return await self.run_optimization_cycle()

    # -- CICLO COMPLETO --------------------------------------------------------

    async def run_optimization_cycle(self) -> dict[str, Any]:
        """
        Ciclo completo:
        1. Recopilar datos de IoT y ERP (si disponibles)
        2. Analizar todos los procesos activos del sector
        3. Detectar cuellos de botella
        4. Proponer optimizaciones
        5. Registrar mejoras en Supabase
        """
        logger.info("[ProcessOpt] Ciclo de optimizacion -- Sector: %s", self.sector_id)
        results: dict[str, Any] = {"agent": self.name, "sector": self.sector_id}

        iot_data = await self.collect_iot_data()
        results["iot_data"] = iot_data

        processes = await self._get_active_processes()
        results["processes_analyzed"] = len(processes)

        optimizations = []
        for proc in processes:
            analysis = await self.analyze_process(proc.get("id"))
            if analysis.get("optimization_needed"):
                opt = await self.propose_optimization(proc)
                if opt:
                    optimizations.append(opt)
                    await self._persist_optimization(proc["id"], opt)

        results["optimizations_proposed"] = len(optimizations)
        results["optimizations"] = optimizations

        chains = await self._get_supply_chains()
        chain_opts = 0
        for chain in chains:
            if chain.get("efficiency_pct", 100) < 85:
                chain_opt = await self.optimize_supply_chain(chain.get("id"))
                if chain_opt.get("success"):
                    chain_opts += 1
        results["supply_chain_optimizations"] = chain_opts
        results["success"] = True
        return results

    # -- ANALISIS DE PROCESOS -------------------------------------------------

    async def analyze_process(self, process_id: Optional[str]) -> dict[str, Any]:
        """
        Analiza un proceso especifico para identificar ineficiencias.
        Usa datos de Supabase + IA para el diagnostico.
        """
        process = None
        if process_id:
            try:
                from apps.core.memory.supabase_client import get_db
                db = get_db()
                processes = await db.get_processes(sector_id=self.sector_id)
                process = next((p for p in processes if p["id"] == process_id), None)
            except Exception as exc:
                return {"success": False, "error": str(exc)}

        if not process:
            return {"success": False, "error": "Proceso no encontrado", "optimization_needed": False}

        prompt = (
            "Analiza este proceso operativo y detecta ineficiencias.\n"
            f"Proceso: {process}\n"
            f"Sector: {self.sector_id}\n\n"
            "Evalua: eficiencia actual vs potencial, cuellos de botella, pasos automatizables,\n"
            "costo estimado de ineficiencias (USD/mes), complejidad de optimizacion.\n"
            "Responde SOLO con JSON:\n"
            '{"efficiency_score": 0, "bottlenecks": ["..."], "automatable_steps": ["..."], '
            '"monthly_cost_waste_usd": 0, "optimization_complexity": "low", '
            '"optimization_needed": true, "priority": 1}'
        )
        try:
            analysis = await self.ai_complete_json(prompt, model=AIModel.STRATEGY)
            analysis["process_id"] = process_id
            analysis["process_name"] = process.get("name")
            return analysis
        except Exception as exc:
            return {"success": False, "error": str(exc), "optimization_needed": False}

    # -- PROPUESTA DE OPTIMIZACION --------------------------------------------

    async def propose_optimization(self, process: dict) -> Optional[dict[str, Any]]:
        """Genera una propuesta concreta de optimizacion para un proceso dado."""
        prompt = (
            "Genera un plan de optimizacion accionable para este proceso.\n"
            f"Proceso: {process}\n"
            f"Sector: {self.sector_id}\n"
            "Capacidades de ARIA: automatizacion de codigo, integracion de APIs, generacion de contenido,\n"
            "analisis de datos, orquestacion de agentes.\n"
            "Responde SOLO con JSON:\n"
            '{"optimization_name": "...", "description": "...", '
            '"steps": [{"action": "...", "responsible": "aria|human|hybrid", '
            '"estimated_days": 1, "impact": "..."}], '
            '"expected_efficiency_gain_pct": 15, "expected_cost_saving_usd_month": 0, '
            '"aria_automation_level_pct": 80, "requires_human_approval": false}'
        )
        try:
            opt = await self.ai_complete_json(prompt, model=AIModel.STRATEGY)
            opt["process_id"] = process.get("id")
            if opt.get("requires_human_approval"):
                await self.execute_with_approval(
                    action=f"Optimizacion: {opt.get('optimization_name')}",
                    details=opt.get("description", ""),
                    fn=lambda: self._apply_optimization(process["id"], opt),
                    amount_usd=0.0,
                )
            else:
                await self._apply_optimization(process["id"], opt)
            return opt
        except Exception as exc:
            logger.error("[ProcessOpt] Error en propose_optimization: %s", exc)
            return None

    # -- CADENAS DE SUMINISTRO ------------------------------------------------

    async def optimize_supply_chain(self, chain_id: Optional[str]) -> dict[str, Any]:
        """Optimiza una cadena de suministro especifica."""
        if not chain_id:
            return {"success": False, "error": "chain_id requerido"}
        try:
            from apps.core.memory.supabase_client import get_db
            db = get_db()
            chains = await db.get_supply_chain_efficiency()
            chain = next((c for c in chains if c["id"] == chain_id), None)
            if not chain:
                return {"success": False, "error": "Cadena no encontrada"}

            prompt = (
                "Optimiza esta cadena de suministro dentro de la economia circular de ARIA.\n"
                f"Cadena: {chain}\n"
                f"Sector origen: {chain.get('source_sector')} -> Destino: {chain.get('target_sector')}\n"
                f"Eficiencia actual: {chain.get('efficiency_pct', 100)}%\n\n"
                "Propone mejoras concretas. Responde SOLO con JSON:\n"
                '{"optimizations": ["..."], "new_efficiency_pct": 0, '
                '"cost_reduction_pct": 0, "implementation_days": 7, "key_actions": ["..."]}'
            )
            result = await self.ai_complete_json(prompt, model=AIModel.STRATEGY)
            await db.update_supply_chain(chain_id, {
                "optimization": result,
                "efficiency_pct": result.get("new_efficiency_pct", chain.get("efficiency_pct", 100)),
            })
            result["success"] = True
            result["chain_id"] = chain_id
            return result
        except Exception as exc:
            return {"success": False, "error": str(exc)}

    # -- INTEGRACION IoT ------------------------------------------------------

    async def collect_iot_data(self) -> dict[str, Any]:
        """
        Recopila datos de sensores IoT si la API esta configurada.
        Si no esta configurada, retorna error explicito (no simula datos).
        """
        if not settings.IOT_API_KEY or not settings.IOT_BROKER_URL:
            return {
                "available": False,
                "message": "IOT_API_KEY / IOT_BROKER_URL no configurados. Conecta tu plataforma IoT.",
            }
        try:
            import httpx
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.get(
                    f"{settings.IOT_BROKER_URL}/sensors/{self.sector_id}",
                    headers={"Authorization": f"Bearer {settings.IOT_API_KEY}"},
                )
                if resp.status_code == 200:
                    data = resp.json()
                    return {
                        "available": True,
                        "sensors": data.get("sensors", []),
                        "readings": data.get("readings", []),
                    }
                return {"available": False, "error": f"IoT API retorno {resp.status_code}"}
        except Exception as exc:
            return {"available": False, "error": str(exc)}

    # -- PROPUESTA DE AUTOMATIZACION ------------------------------------------

    async def propose_automation(self, process_id: Optional[str]) -> dict[str, Any]:
        """Identifica que partes de un proceso puede automatizar ARIA directamente."""
        process = None
        if process_id:
            try:
                from apps.core.memory.supabase_client import get_db
                db = get_db()
                processes = await db.get_processes(sector_id=self.sector_id)
                process = next((p for p in processes if p["id"] == process_id), None)
            except Exception:
                pass

        prompt = (
            "Identifica que partes de este proceso puede automatizar ARIA de forma inmediata.\n"
            f"Proceso: {process or 'Proceso generico del sector ' + self.sector_id}\n"
            "Capacidades de ARIA: Python/FastAPI, integracion de APIs, IA generativa, scraping web,\n"
            "generacion de reportes, orquestacion de agentes, notificaciones Telegram.\n"
            "Responde SOLO con JSON:\n"
            '{"automatable_now": [{"step": "...", "tool": "api|script|agent|ai_generation", '
            '"estimated_hours_to_implement": 4, "time_saved_hours_month": 20}], '
            '"automatable_future": ["..."], "human_required": ["..."], "total_automation_pct": 70}'
        )
        try:
            result = await self.ai_complete_json(prompt, model=AIModel.STRATEGY)
            result["process_id"] = process_id
            result["success"] = True
            return result
        except Exception as exc:
            return {"success": False, "error": str(exc)}

    # -- UTILIDADES -----------------------------------------------------------

    async def _get_active_processes(self) -> list[dict]:
        try:
            from apps.core.memory.supabase_client import get_db
            db = get_db()
            return await db.get_processes(sector_id=self.sector_id)
        except Exception as exc:
            logger.warning("[ProcessOpt] No pudo obtener procesos: %s", exc)
            return []

    async def _get_supply_chains(self) -> list[dict]:
        try:
            from apps.core.memory.supabase_client import get_db
            db = get_db()
            return await db.get_supply_chain_efficiency()
        except Exception:
            return []

    async def _persist_optimization(self, process_id: str, optimization: dict) -> None:
        try:
            from apps.core.memory.supabase_client import get_db
            db = get_db()
            await db.add_process_optimization(process_id, optimization)
        except Exception as exc:
            logger.warning("[ProcessOpt] No pudo persistir optimizacion: %s", exc)

    async def _apply_optimization(self, process_id: str, opt: dict) -> dict[str, Any]:
        try:
            from apps.core.memory.supabase_client import get_db
            db = get_db()
            await db.add_process_optimization(process_id, {**opt, "status": "applied"})
            return {"success": True}
        except Exception as exc:
            return {"success": False, "error": str(exc)}
