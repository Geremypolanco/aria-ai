"""
economic_governor_agent.py -- ARIA AI Gobernador Economico v1.

Agente central de macro-gestion economica para la economia circular de ARIA.
- Precios dinamicos por sector
- Distribucion de capital (reinversion, reserva, fondo comunitario)
- Deteccion de desequilibrios de mercado
- Politicas economicas auditables en Supabase
- Coordinacion con CFOAgent y ComplianceAgent

Principio: NINGUNA funcion retorna datos simulados.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

import httpx

from apps.core.agents.base_agent import BaseAgent
from apps.core.config import settings
from apps.core.tools.ai_client import AIModel

logger = logging.getLogger("aria.economic_governor")


class EconomicGovernorAgent(BaseAgent):
    """
    Gobernador macro-economico de la economia circular de ARIA.
    Opera sobre todos los sectores habilitados, tomando decisiones de:
    - Fijacion de precios dinamicos
    - Asignacion de capital entre sectores
    - Deteccion de desequilibrios y correccion
    - Politica de reinversion y fondo comunitario
    """

    def __init__(self) -> None:
        super().__init__(
            name="economic_governor",
            description="Macro-gestion economica circular: precios dinamicos, capital, desequilibrios de mercado",
            capabilities=[
                "price_setting", "capital_allocation", "market_analysis",
                "policy_creation", "sector_balancing", "community_fund",
                "supply_chain_optimization", "revenue_distribution",
                "market_data", "supabase",
            ],
            sector_id="digital",
        )
        self.reinvest_rate = settings.CIRCULAR_ECONOMY_REINVEST_RATE
        self.reserve_rate = settings.CIRCULAR_ECONOMY_RESERVE_RATE
        self.community_rate = settings.CIRCULAR_ECONOMY_COMMUNITY_RATE
        self.price_variance_target = settings.PRICE_STABILITY_TARGET_VARIANCE

    async def _execute(self, context: dict[str, Any]) -> dict[str, Any]:
        mode = context.get("mode", "full_cycle")
        if mode == "price_review":
            return await self.review_prices(context.get("sectors", settings.enabled_sectors_list))
        if mode == "capital_allocation":
            return await self.allocate_capital(context.get("total_revenue_usd", 0.0))
        if mode == "market_scan":
            return await self.scan_market_imbalances()
        return await self.run_governance_cycle()

    # -- CICLO DE GOBERNANZA --------------------------------------------------

    async def run_governance_cycle(self) -> dict[str, Any]:
        """
        Ciclo completo:
        1. Escanear desequilibrios de mercado
        2. Revisar y ajustar precios por sector
        3. Distribuir capital acumulado
        4. Registrar politicas en Supabase
        5. Notificar al propietario via Telegram
        """
        logger.info("[EconomicGovernor] Iniciando ciclo de gobernanza economica")
        results: dict[str, Any] = {"agent": self.name, "cycle": "governance"}

        imbalances = await self.scan_market_imbalances()
        results["imbalances"] = imbalances

        sectors = settings.enabled_sectors_list
        price_report = await self.review_prices(sectors)
        results["price_adjustments"] = price_report

        total_revenue = await self._get_total_revenue()
        if total_revenue > 0:
            allocation = await self.allocate_capital(total_revenue)
            results["capital_allocation"] = allocation

        policy = await self._create_governance_policy(results)
        results["policy_id"] = policy
        await self._send_governance_report(results)
        results["success"] = True
        return results

    # -- PRECIOS DINAMICOS ----------------------------------------------------

    async def review_prices(self, sectors: list[str]) -> dict[str, Any]:
        """
        Analiza precios actuales en cada sector y propone ajustes
        para mantener la estabilidad de la economia circular.
        """
        if not sectors:
            return {"adjusted": [], "stable": [], "flagged": []}

        prompt = (
            "Eres el Gobernador Economico de una economia circular multi-sectorial.\n"
            f"Sectores activos: {sectors}\n"
            f"Objetivo de varianza de precios: +-{self.price_variance_target * 100:.0f}%\n"
            f"Tasa de reinversion: {self.reinvest_rate * 100:.0f}%\n\n"
            "Para cada sector proporciona: recommended_adjustment_pct, rationale, requires_approval.\n"
            "Responde SOLO con JSON:\n"
            '{"sector_id": {"recommended_adjustment_pct": 0, "rationale": "...", "requires_approval": false}}'
        )
        try:
            analysis = await self.ai_complete_json(prompt, model=AIModel.STRATEGY)
            adjusted, stable, flagged = [], [], []
            for sector, data in analysis.items():
                adj = data.get("recommended_adjustment_pct", 0)
                if abs(adj) > self.price_variance_target * 100:
                    if data.get("requires_approval"):
                        flagged.append({"sector": sector, **data})
                    else:
                        adjusted.append({"sector": sector, **data})
                        await self._log_price_policy(sector, data)
                else:
                    stable.append(sector)
            return {"adjusted": adjusted, "stable": stable, "flagged": flagged}
        except Exception as exc:
            logger.error("[EconomicGovernor] review_prices error: %s", exc)
            return {"error": str(exc)}

    # -- DISTRIBUCION DE CAPITAL ----------------------------------------------

    async def allocate_capital(self, total_revenue_usd: float) -> dict[str, Any]:
        """
        Distribuye capital segun las tasas de la economia circular:
        - Reinversion en operaciones/expansion
        - Reserva de emergencia
        - Fondo comunitario (servicios de bajo costo)
        - Balance operativo
        """
        if total_revenue_usd <= 0:
            return {"success": False, "error": "Sin revenue para distribuir"}

        reinvest = round(total_revenue_usd * self.reinvest_rate, 4)
        reserve = round(total_revenue_usd * self.reserve_rate, 4)
        community = round(total_revenue_usd * self.community_rate, 4)
        operational = round(total_revenue_usd - reinvest - reserve - community, 4)

        allocation = {
            "total_revenue_usd": total_revenue_usd,
            "reinvestment_usd": reinvest,
            "reserve_usd": reserve,
            "community_fund_usd": community,
            "operational_usd": operational,
            "rates": {
                "reinvest": self.reinvest_rate,
                "reserve": self.reserve_rate,
                "community": self.community_rate,
            },
        }

        active = settings.enabled_sectors_list
        if len(active) > 1:
            per_sector = reinvest / len(active)
            allocation["sector_breakdown"] = {s: round(per_sector, 4) for s in active}

        await self._persist_allocation(allocation)
        logger.info(
            "[EconomicGovernor] Capital distribuido: reinversion=$%.2f | reserva=$%.2f | comunidad=$%.2f",
            reinvest, reserve, community,
        )
        return allocation

    # -- DETECCION DE DESEQUILIBRIOS ------------------------------------------

    async def scan_market_imbalances(self) -> dict[str, Any]:
        """
        Escanea sectores activos buscando:
        - Sobre-oferta o sub-oferta de recursos
        - Cuellos de botella en cadenas de suministro
        - Riesgo de concentracion de capital
        - Oportunidades de arbitraje dentro de la economia circular
        """
        try:
            from apps.core.memory.supabase_client import get_db
            db = get_db()
            sectors_data = await db.get_active_sectors()
            supply_chains = await db.get_supply_chain_efficiency()
            imbalances, opportunities = [], []

            for sector in sectors_data:
                sid = sector.get("sector_id", "")
                resources = await db.get_sector_resources(sid)
                for resource in resources:
                    util = resource.get("utilization_pct", 100)
                    if util < 60:
                        imbalances.append({
                            "type": "under_utilization",
                            "sector": sid,
                            "resource": resource.get("name"),
                            "utilization_pct": util,
                        })
                    elif util > 95:
                        imbalances.append({
                            "type": "bottleneck",
                            "sector": sid,
                            "resource": resource.get("name"),
                            "utilization_pct": util,
                        })

            for chain in supply_chains:
                if chain.get("efficiency_pct", 100) < 75:
                    opportunities.append({
                        "type": "supply_chain_optimization",
                        "chain": chain.get("name"),
                        "current_efficiency": chain.get("efficiency_pct"),
                        "source": chain.get("source_sector"),
                        "target": chain.get("target_sector"),
                    })

            return {
                "imbalances": imbalances,
                "opportunities": opportunities,
                "sectors_scanned": len(sectors_data),
            }
        except Exception as exc:
            logger.warning("[EconomicGovernor] scan_market_imbalances parcial: %s", exc)
            return {"imbalances": [], "opportunities": [], "error": str(exc)}

    # -- SERVICIOS COMUNITARIOS ------------------------------------------------

    async def propose_community_services(self, community_fund_usd: float) -> dict[str, Any]:
        """
        Propone servicios esenciales a bajo costo para comunidades con recursos limitados,
        financiados por el fondo comunitario.
        """
        prompt = (
            f"Tienes un fondo comunitario de ${community_fund_usd:.2f} USD.\n"
            "Propone 3-5 servicios esenciales de bajo costo o gratuitos que ARIA puede ofrecer\n"
            "a comunidades con recursos limitados usando su economia circular.\n"
            "Tipos: financial, legal, educational, health, tech.\n"
            "Responde SOLO con JSON:\n"
            '{"services": [{"name": "...", "type": "...", "cost_to_user_usd": 0, '
            '"cost_to_aria_usd": 0, "beneficiaries_est": 0, "description": "..."}]}'
        )
        try:
            return await self.ai_complete_json(prompt, model=AIModel.STRATEGY)
        except Exception as exc:
            return {"error": str(exc), "services": []}

    # -- PERSISTENCIA ----------------------------------------------------------

    async def _get_total_revenue(self) -> float:
        try:
            from apps.core.memory.supabase_client import get_db
            db = get_db()
            return await db.get_unallocated_revenue()
        except Exception:
            return 0.0

    async def _persist_allocation(self, allocation: dict) -> None:
        try:
            from apps.core.memory.supabase_client import get_db
            db = get_db()
            await db.record_capital_allocation(allocation)
        except Exception as exc:
            logger.warning("[EconomicGovernor] No pudo persistir allocation: %s", exc)

    async def _log_price_policy(self, sector: str, data: dict) -> None:
        try:
            from apps.core.memory.supabase_client import get_db
            db = get_db()
            await db.create_economic_policy({
                "policy_type": "pricing",
                "sector_id": sector,
                "name": f"Ajuste de precios - {sector}",
                "parameters": data,
                "status": "active",
                "proposed_by": self.name,
            })
        except Exception as exc:
            logger.warning("[EconomicGovernor] No pudo registrar politica: %s", exc)

    async def _create_governance_policy(self, cycle_results: dict) -> Optional[str]:
        try:
            from apps.core.memory.supabase_client import get_db
            db = get_db()
            policy = await db.create_economic_policy({
                "policy_type": "governance_cycle",
                "name": "Ciclo de gobernanza economica",
                "parameters": cycle_results,
                "status": "active",
                "proposed_by": self.name,
            })
            return policy.get("id") if policy else None
        except Exception:
            return None

    async def _send_governance_report(self, results: dict) -> None:
        token = settings.telegram_token
        chat_id = settings.TELEGRAM_CHAT_ID
        if not token or not chat_id:
            return
        n_adj = len(results.get("price_adjustments", {}).get("adjusted", []))
        n_imb = len(results.get("imbalances", {}).get("imbalances", []))
        alloc = results.get("capital_allocation", {})
        rev = alloc.get("total_revenue_usd", 0)
        comm = alloc.get("community_fund_usd", 0)
        msg = (
            "<b>ARIA AI - Gobernanza Economica</b>\n\n"
            f"Revenue distribuido: <b>${rev:.2f}</b>\n"
            f"Ajustes de precio: <b>{n_adj}</b>\n"
            f"Desequilibrios detectados: <b>{n_imb}</b>\n"
            f"Fondo comunitario: <b>${comm:.2f}</b>\n"
            f"Sectores activos: {', '.join(settings.enabled_sectors_list)}"
        )
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                await client.post(
                    f"https://api.telegram.org/bot{token}/sendMessage",
                    json={"chat_id": chat_id, "text": msg, "parse_mode": "HTML"},
                )
        except Exception as exc:
            logger.error("Telegram error en governance report: %s", exc)
