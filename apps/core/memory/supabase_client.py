"""
supabase_client.py -- Cliente Supabase tipado para Aria AI v2.

v2: Soporte completo para la arquitectura multi-sectorial del Gobernador Economico.
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
        return await self.get_total_revenue(days=1)

    async def get_revenue_by_platform(self) -> dict:
        try:
            result = self._client.table("revenue").select("source,amount_usd").execute()
            totals: dict = {}
            for r in (result.data or []):
                src = r.get("source", "unknown")
                totals[src] = totals.get(src, 0.0) + r.get("amount_usd", 0.0)
            return totals
        except Exception:
            return {}

    async def get_best_opportunities(self, limit: int = 10) -> list:
        try:
            result = (self._client.table("market_opportunities")
                      .select("*").order("roi_estimate", desc=True).limit(limit).execute())
            return result.data or []
        except Exception:
            return []

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
        try:
            q = self._client.table("agent_registry").select("*").eq("status", "active")
            if sector_id:
                q = q.eq("sector_id", sector_id)
            result = q.execute()
            return result.data or []
        except Exception:
            return []

    # -- GOBERNANZA ECONOMICA -------------------------------------------------

    async def record_economic_policy(self, policy_data: dict) -> Optional[dict]:
        try:
            result = self._client.table("economic_policies").insert(policy_data).execute()
            return result.data[0] if result.data else None
        except Exception:
            return None

    async def get_economic_policies(self, limit: int = 10, sector: Optional[str] = None) -> list:
        try:
            q = (self._client.table("economic_policies")
                 .select("*").order("created_at", desc=True).limit(limit))
            if sector:
                q = q.eq("sector_id", sector)
            result = q.execute()
            return result.data or []
        except Exception:
            return []

    async def record_capital_allocation(self, allocation_data: dict) -> Optional[dict]:
        try:
            result = self._client.table("capital_allocation").insert(allocation_data).execute()
            return result.data[0] if result.data else None
        except Exception:
            return None

    async def get_capital_allocations(self, limit: int = 10) -> list:
        try:
            result = (self._client.table("capital_allocation")
                      .select("*").order("created_at", desc=True).limit(limit).execute())
            return result.data or []
        except Exception:
            return []

    async def record_price_adjustment(self, sector: str, product_id: str,
                                       old_price: float, new_price: float,
                                       reason: str, metadata: dict = {}) -> Optional[dict]:
        try:
            result = self._client.table("price_adjustments").insert({
                "sector_id": sector, "product_id": product_id,
                "old_price_usd": old_price, "new_price_usd": new_price,
                "reason": reason, "metadata": metadata,
            }).execute()
            return result.data[0] if result.data else None
        except Exception:
            return None

    # -- MEDIA ASSETS (Cloudinary) --------------------------------------------

    async def record_media_asset(self, asset_data: dict) -> Optional[dict]:
        """
        Registra un media asset subido a Cloudinary en la tabla media_assets.

        asset_data debe contener: public_id, url, secure_url, resource_type,
        format, bytes, agent_id, tags, metadata.
        """
        try:
            result = self._client.table("media_assets").insert({
                "public_id": asset_data.get("public_id", ""),
                "url": asset_data.get("url", ""),
                "secure_url": asset_data.get("secure_url", ""),
                "resource_type": asset_data.get("resource_type", "image"),
                "format": asset_data.get("format", ""),
                "bytes": asset_data.get("bytes", 0),
                "agent_id": asset_data.get("agent_id", "system"),
                "tags": asset_data.get("tags", []),
                "metadata": asset_data.get("metadata", {}),
            }).execute()
            return result.data[0] if result.data else None
        except Exception:
            return None

    async def get_media_assets(self, agent_id: Optional[str] = None,
                                resource_type: Optional[str] = None,
                                limit: int = 20) -> list:
        try:
            q = self._client.table("media_assets").select("*").order("created_at", desc=True).limit(limit)
            if agent_id:
                q = q.eq("agent_id", agent_id)
            if resource_type:
                q = q.eq("resource_type", resource_type)
            result = q.execute()
            return result.data or []
        except Exception:
            return []

    # -- RECURSOS HUMANOS -----------------------------------------------------

    async def get_active_employees(self, sector_id: Optional[str] = None) -> list:
        try:
            q = self._client.table("human_resources").select("*").eq("status", "active")
            if sector_id:
                q = q.eq("sector_id", sector_id)
            result = q.execute()
            return result.data or []
        except Exception:
            return []

    async def update_employee_performance(self, employee_id: str, kpi_data: dict) -> bool:
        try:
            self._client.table("human_resources").update(
                {"performance": kpi_data}
            ).eq("id", employee_id).execute()
            return True
        except Exception:
            return False

    async def record_training_plan(self, employee_id: str, plan: dict) -> Optional[dict]:
        try:
            result = self._client.table("training_plans").insert({
                "employee_id": employee_id, "plan": plan,
            }).execute()
            return result.data[0] if result.data else None
        except Exception:
            return None

    # -- PROCESOS -------------------------------------------------------------

    async def get_active_processes(self, sector_id: Optional[str] = None) -> list:
        try:
            q = self._client.table("processes").select("*").eq("status", "active")
            if sector_id:
                q = q.eq("sector_id", sector_id)
            result = q.execute()
            return result.data or []
        except Exception:
            return []

    async def record_optimization(self, process_id: str, optimization: dict) -> Optional[dict]:
        try:
            result = self._client.table("process_optimizations").insert({
                "process_id": process_id, "optimization": optimization,
            }).execute()
            return result.data[0] if result.data else None
        except Exception:
            return None

    async def get_supply_chains(self, sector_id: Optional[str] = None) -> list:
        try:
            q = self._client.table("supply_chains").select("*").eq("status", "active")
            if sector_id:
                q = q.eq("sector_id", sector_id)
            result = q.execute()
            return result.data or []
        except Exception:
            return []


# -- SINGLETON ---------------------------------------------------------------

_db_instance: Optional[AriaDatabase] = None


def get_db() -> AriaDatabase:
    global _db_instance
    if _db_instance is None:
        _db_instance = AriaDatabase()
    return _db_instance
