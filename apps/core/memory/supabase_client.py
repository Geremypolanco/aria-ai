"""
supabase_client.py -- Cliente Supabase tipado para Aria AI v2.

v2: Soporte completo para la arquitectura multi-sectorial del Gobernador Economico:
- agent_registry: registro dinamico de agentes
- sectors: gestion de sectores economicos
- resources: inventario de recursos por sector
- supply_chains: cadenas de suministro
- legal_frameworks: marcos legales
- human_resources: capital humano
- processes: procesos operativos
- economic_policies: politicas macro-economicas
- audit_trail: auditoria y transparencia
- capital_allocation: distribucion de capital
"""
from __future__ import annotations
from typing import Optional, Any
from supabase import create_client, Client
from apps.core.config import settings
import json


class AriaDatabase:

    def __init__(self):
        self._client: Client = create_client(settings.SUPABASE_URL, settings.SUPABASE_KEY)

    # -- LOGS -----------------------------------------------------------------

    async def log(self, level: str, message: str, agent: str = "system", metadata: Optional[dict] = None):
        try:
            self._client.table("system_logs").insert({
                "level": level, "agent": agent, "message": message, "metadata": metadata or {}
            }).execute()
        except Exception:
            pass

    async def log_info(self, message: str, agent: str = "system", metadata: dict = {}):
        await self.log("INFO", message, agent, metadata)

    async def log_error(self, message: str, agent: str = "system", metadata: dict = {}):
        await self.log("ERROR", message, agent, metadata)

    async def log_success(self, message: str, agent: str = "system", metadata: dict = {}):
        await self.log("SUCCESS", message, agent, metadata)

    async def log_money(self, message: str, agent: str = "cfo", metadata: dict = {}):
        await self.log("REVENUE", message, agent, metadata)

    async def get_recent_logs(self, limit: int = 10, level: Optional[str] = None) -> list:
        try:
            q = self._client.table("system_logs").select("*").order("created_at", desc=True).limit(limit)
            if level:
                q = q.eq("level", level)
            result = q.execute()
            return result.data or []
        except Exception:
            return []

    # -- TAREAS ---------------------------------------------------------------

    async def create_task(self, agent_id: str, task_type: str, input_data: dict,
                          priority: int = 5, requires_approval: bool = False) -> Optional[dict]:
        try:
            result = self._client.table("tasks").insert({
                "agent_id": agent_id, "type": task_type, "input": input_data,
                "priority": priority, "requires_approval": requires_approval,
            }).execute()
            return result.data[0] if result.data else None
        except Exception:
            return None

    async def update_task(self, task_id: str, updates: dict) -> bool:
        try:
            self._client.table("tasks").update(updates).eq("id", task_id).execute()
            return True
        except Exception:
            return False

    async def get_pending_tasks(self, agent_id: Optional[str] = None) -> list:
        try:
            q = self._client.table("tasks").select("*").eq("status", "pending").order("priority")
            if agent_id:
                q = q.eq("agent_id", agent_id)
            result = q.execute()
            return result.data or []
        except Exception:
            return []

    # -- INGRESOS -------------------------------------------------------------

    async def record_revenue(self, agent_id: str, source: str, amount_usd: float,
                              description: str = "", metadata: dict = {}) -> Optional[dict]:
        try:
            result = self._client.table("revenue").insert({
                "agent_id": agent_id, "source": source, "amount_usd": amount_usd,
                "description": description, "metadata": metadata,
            }).execute()
            return result.data[0] if result.data else None
        except Exception:
            return None

    async def get_total_revenue(self, days: int = 30) -> float:
        try:
            from datetime import datetime, timezone, timedelta
            since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
            result = self._client.table("revenue").select("amount_usd").gte("created_at", since).execute()
            return sum(r["amount_usd"] for r in (result.data or []))
        except Exception:
            return 0.0

    async def get_unallocated_revenue(self) -> float:
        """Retorna el revenue pendiente de distribucion en el ciclo circular."""
        return await self.get_total_revenue(days=1)

    # -- APROBACIONES ---------------------------------------------------------

    async def create_approval_request(self, agent_id: str, agent_name: str, action_type: str,
                                       detail: str, amount_usd: float, metadata: dict = {}) -> Optional[dict]:
        try:
            result = self._client.table("approvals").insert({
                "agent_id": agent_id, "agent_name": agent_name, "action_type": action_type,
                "detail": detail, "amount_usd": amount_usd, "metadata": metadata,
            }).execute()
            return result.data[0] if result.data else None
        except Exception:
            return None

    async def get_pending_approvals(self) -> list:
        try:
            result = self._client.table("approvals").select("*").eq("status", "pending").execute()
            return result.data or []
        except Exception:
            return []

    # -- AGENT REGISTRY -------------------------------------------------------

    async def upsert_agent_registry(self, agent_data: dict) -> Optional[dict]:
        """Registra o actualiza un agente en el registry de Supabase."""
        try:
            result = self._client.table("agent_registry").upsert(
                agent_data, on_conflict="agent_id"
            ).execute()
            return result.data[0] if result.data else None
        except Exception:
            return None

    async def update_agent_status(self, agent_id: str, status: str) -> bool:
        try:
            self._client.table("agent_registry").update({"status": status}).eq("agent_id", agent_id).execute()
            return True
        except Exception:
            return False

    async def get_agent_registry(self, sector_id: Optional[str] = None) -> list:
        """Obtiene todos los agentes registrados, opcionalmente filtrados por sector."""
        try:
            q = self._client.table("agent_registry").select("*").eq("status", "active")
            if sector_id:
                q = q.eq("sector_id", sector_id)
            result = q.execute()
            return result.data or []
        except Exception:
            return []

    # -- SECTORES -------------------------------------------------------------

    async def get_active_sectors(self) -> list:
        """Retorna todos los sectores habilitados en la economia circular."""
        try:
            result = self._client.table("sectors").select("*").eq("enabled", True).execute()
            return result.data or []
        except Exception:
            return []

    async def enable_sector(self, sector_id: str, config: dict = {}) -> bool:
        """Habilita un sector economico en ARIA."""
        try:
            self._client.table("sectors").update({
                "enabled": True, "config": config
            }).eq("sector_id", sector_id).execute()
            return True
        except Exception:
            return False

    # -- RECURSOS -------------------------------------------------------------

    async def get_sector_resources(self, sector_id: str) -> list:
        """Retorna los recursos de un sector especifico."""
        try:
            result = self._client.table("resources").select("*").eq("sector_id", sector_id).execute()
            return result.data or []
        except Exception:
            return []

    async def create_resource(self, resource_data: dict) -> Optional[dict]:
        try:
            result = self._client.table("resources").insert(resource_data).execute()
            return result.data[0] if result.data else None
        except Exception:
            return None

    async def update_resource(self, resource_id: str, updates: dict) -> bool:
        try:
            self._client.table("resources").update(updates).eq("id", resource_id).execute()
            return True
        except Exception:
            return False

    # -- CADENAS DE SUMINISTRO ------------------------------------------------

    async def get_supply_chain_efficiency(self) -> list:
        """Retorna todas las cadenas de suministro con su eficiencia actual."""
        try:
            result = self._client.table("supply_chains").select("*").eq("status", "active").execute()
            return result.data or []
        except Exception:
            return []

    async def update_supply_chain(self, chain_id: str, updates: dict) -> bool:
        try:
            self._client.table("supply_chains").update(updates).eq("id", chain_id).execute()
            return True
        except Exception:
            return False

    async def create_supply_chain(self, chain_data: dict) -> Optional[dict]:
        try:
            result = self._client.table("supply_chains").insert(chain_data).execute()
            return result.data[0] if result.data else None
        except Exception:
            return None

    # -- MARCOS LEGALES -------------------------------------------------------

    async def get_legal_frameworks(self, sector_id: Optional[str] = None, jurisdiction: Optional[str] = None) -> list:
        try:
            q = self._client.table("legal_frameworks").select("*")
            if sector_id:
                q = q.eq("sector_id", sector_id)
            if jurisdiction:
                q = q.eq("jurisdiction", jurisdiction)
            result = q.execute()
            return result.data or []
        except Exception:
            return []

    async def create_legal_framework(self, framework_data: dict) -> Optional[dict]:
        try:
            result = self._client.table("legal_frameworks").insert(framework_data).execute()
            return result.data[0] if result.data else None
        except Exception:
            return None

    # -- RECURSOS HUMANOS -----------------------------------------------------

    async def get_hr_employees(self, sector_id: Optional[str] = None, status: str = "active") -> list:
        try:
            q = self._client.table("human_resources").select("*").eq("status", status)
            if sector_id:
                q = q.eq("sector_id", sector_id)
            result = q.execute()
            return result.data or []
        except Exception:
            return []

    async def create_hr_employee(self, employee_data: dict) -> Optional[dict]:
        try:
            result = self._client.table("human_resources").insert(employee_data).execute()
            return result.data[0] if result.data else None
        except Exception:
            return None

    async def update_hr_performance(self, employee_id: str, performance: dict) -> bool:
        try:
            self._client.table("human_resources").update({"performance": performance}).eq("id", employee_id).execute()
            return True
        except Exception:
            return False

    async def update_hr_training_plan(self, employee_id: str, plan: dict) -> bool:
        try:
            self._client.table("human_resources").update({"training_plan": plan}).eq("id", employee_id).execute()
            return True
        except Exception:
            return False

    async def assign_hr_task(self, employee_id: str, task: dict, priority: int = 5) -> Optional[dict]:
        try:
            emp = self._client.table("human_resources").select("assigned_tasks").eq("id", employee_id).execute()
            current_tasks = emp.data[0].get("assigned_tasks", []) if emp.data else []
            current_tasks.append({**task, "priority": priority})
            self._client.table("human_resources").update({"assigned_tasks": current_tasks}).eq("id", employee_id).execute()
            return {"success": True, "task_added": task}
        except Exception as exc:
            return {"success": False, "error": str(exc)}

    # -- PROCESOS -------------------------------------------------------------

    async def get_processes(self, sector_id: Optional[str] = None, status: str = "active") -> list:
        try:
            q = self._client.table("processes").select("*").eq("status", status)
            if sector_id:
                q = q.eq("sector_id", sector_id)
            result = q.execute()
            return result.data or []
        except Exception:
            return []

    async def create_process(self, process_data: dict) -> Optional[dict]:
        try:
            result = self._client.table("processes").insert(process_data).execute()
            return result.data[0] if result.data else None
        except Exception:
            return None

    async def add_process_optimization(self, process_id: str, optimization: dict) -> bool:
        """Agrega una entrada al historial de optimizaciones de un proceso."""
        try:
            proc = self._client.table("processes").select("optimization_log").eq("id", process_id).execute()
            log = proc.data[0].get("optimization_log", []) if proc.data else []
            log.append(optimization)
            new_eff = optimization.get("expected_efficiency_gain_pct", 0)
            self._client.table("processes").update({
                "optimization_log": log,
                "current_efficiency": min(100, (proc.data[0].get("current_efficiency", 100) if proc.data else 100) + new_eff),
            }).eq("id", process_id).execute()
            return True
        except Exception:
            return False

    # -- POLITICAS ECONOMICAS -------------------------------------------------

    async def create_economic_policy(self, policy_data: dict) -> Optional[dict]:
        try:
            result = self._client.table("economic_policies").insert(policy_data).execute()
            return result.data[0] if result.data else None
        except Exception:
            return None

    async def get_active_policies(self, sector_id: Optional[str] = None) -> list:
        try:
            q = self._client.table("economic_policies").select("*").eq("status", "active")
            if sector_id:
                q = q.eq("sector_id", sector_id)
            result = q.execute()
            return result.data or []
        except Exception:
            return []

    # -- AUDITORIA ------------------------------------------------------------

    async def create_audit_entry(self, audit_data: dict) -> Optional[dict]:
        """Registra una entrada en el audit trail para transparencia y rendicion de cuentas."""
        try:
            result = self._client.table("audit_trail").insert(audit_data).execute()
            return result.data[0] if result.data else None
        except Exception:
            return None

    async def get_audit_trail(self, agent_name: Optional[str] = None,
                               sector_id: Optional[str] = None, limit: int = 50) -> list:
        try:
            q = self._client.table("audit_trail").select("*").order("created_at", desc=True).limit(limit)
            if agent_name:
                q = q.eq("agent_name", agent_name)
            if sector_id:
                q = q.eq("sector_id", sector_id)
            result = q.execute()
            return result.data or []
        except Exception:
            return []

    # -- CAPITAL ALLOCATION ---------------------------------------------------

    async def record_capital_allocation(self, allocation: dict) -> Optional[dict]:
        try:
            from datetime import datetime, timezone, timedelta
            now = datetime.now(timezone.utc)
            result = self._client.table("capital_allocation").insert({
                "period_start": (now - timedelta(hours=24)).isoformat(),
                "period_end": now.isoformat(),
                "total_revenue": allocation.get("total_revenue_usd", 0),
                "reinvested": allocation.get("reinvestment_usd", 0),
                "reserved": allocation.get("reserve_usd", 0),
                "community_fund": allocation.get("community_fund_usd", 0),
                "sector_breakdown": allocation.get("sector_breakdown", {}),
                "notes": "Distribucion automatica del Gobernador Economico",
            }).execute()
            return result.data[0] if result.data else None
        except Exception:
            return None

    async def get_capital_history(self, limit: int = 30) -> list:
        try:
            result = self._client.table("capital_allocation").select("*").order("created_at", desc=True).limit(limit).execute()
            return result.data or []
        except Exception:
            return []

    # -- INVENTARIO DE APIs ---------------------------------------------------

    async def upsert_api_inventory(self, api_data: dict) -> Optional[dict]:
        try:
            result = self._client.table("api_inventory").upsert(api_data, on_conflict="url").execute()
            return result.data[0] if result.data else None
        except Exception:
            return None

    async def get_api_inventory(self, integrated: Optional[bool] = None) -> list:
        try:
            q = self._client.table("api_inventory").select("*").order("roi_score", desc=True)
            if integrated is not None:
                q = q.eq("integrated", integrated)
            result = q.execute()
            return result.data or []
        except Exception:
            return []


_db_instance: Optional[AriaDatabase] = None


def get_db() -> AriaDatabase:
    global _db_instance
    if _db_instance is None:
        _db_instance = AriaDatabase()
    return _db_instance
