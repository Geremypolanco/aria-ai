"""
Cliente Supabase tipado para Aria AI.
Maneja toda la persistencia de datos.
"""
from typing import Optional, Any
from supabase import create_client, Client
from apps.core.config import settings
import json


class AriaDatabase:

    def __init__(self):
        self._client: Client = create_client(
            settings.SUPABASE_URL,
            settings.SUPABASE_KEY
        )

    # ── LOGS ──────────────────────────────────────────────
    async def log(
        self,
        level: str,
        message: str,
        agent: str = "system",
        metadata: Optional[dict] = None
    ):
        try:
            self._client.table("system_logs").insert({
                "level": level,
                "agent": agent,
                "message": message,
                "metadata": metadata or {}
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

    # ── TAREAS ────────────────────────────────────────────
    async def create_task(
        self,
        agent_id: str,
        task_type: str,
        input_data: dict,
        priority: int = 5,
        requires_approval: bool = False
    ) -> Optional[dict]:
        try:
            result = self._client.table("tasks").insert({
                "agent_id": agent_id,
                "type": task_type,
                "status": "pending",
                "priority": priority,
                "input": input_data,
                "requires_approval": requires_approval
            }).execute()
            return result.data[0] if result.data else None
        except Exception as e:
            await self.log_error(f"Error creando tarea: {e}")
            return None

    async def update_task(self, task_id: str, updates: dict) -> bool:
        try:
            self._client.table("tasks").update(updates).eq("id", task_id).execute()
            return True
        except Exception as e:
            await self.log_error(f"Error actualizando tarea {task_id}: {e}")
            return False

    async def get_pending_tasks(self, limit: int = 20) -> list:
        try:
            result = self._client.table("tasks")\
                .select("*, agents(name, type)")\
                .eq("status", "pending")\
                .order("priority", desc=True)\
                .order("created_at")\
                .limit(limit)\
                .execute()
            return result.data or []
        except Exception:
            return []

    # ── APROBACIONES ──────────────────────────────────────
    async def create_approval(
        self,
        task_id: str,
        agent_name: str,
        action: str,
        details: dict
    ) -> Optional[dict]:
        try:
            result = self._client.table("approvals").insert({
                "task_id": task_id,
                "agent_name": agent_name,
                "action": action,
                "details": details,
                "status": "pending"
            }).execute()
            return result.data[0] if result.data else None
        except Exception as e:
            await self.log_error(f"Error creando aprobación: {e}")
            return None

    async def resolve_approval(
        self,
        approval_id: str,
        decision: str,
        reason: str = ""
    ) -> bool:
        try:
            from datetime import datetime, timezone
            self._client.table("approvals").update({
                "status": "resolved",
                "decision": decision,
                "decision_reason": reason,
                "decided_at": datetime.now(timezone.utc).isoformat()
            }).eq("id", approval_id).execute()
            return True
        except Exception:
            return False

    async def get_pending_approvals(self) -> list:
        try:
            result = self._client.table("approvals")\
                .select("*")\
                .eq("status", "pending")\
                .order("created_at")\
                .execute()
            return result.data or []
        except Exception:
            return []

    # ── INGRESOS ──────────────────────────────────────────
    async def register_revenue(
        self,
        source: str,
        revenue_type: str,
        amount: float,
        currency: str = "USD",
        product_name: str = "",
        platform: str = "",
        transaction_id: str = "",
        metadata: dict = {}
    ) -> Optional[dict]:
        try:
            result = self._client.table("revenue").insert({
                "source": source,
                "type": revenue_type,
                "amount": amount,
                "currency": currency,
                "product_name": product_name,
                "platform": platform,
                "transaction_id": transaction_id or None,
                "metadata": metadata
            }).execute()
            return result.data[0] if result.data else None
        except Exception as e:
            await self.log_error(f"Error registrando ingreso: {e}")
            return None

    async def get_total_revenue(self) -> float:
        try:
            result = self._client.table("revenue").select("amount").execute()
            return sum(float(r["amount"]) for r in (result.data or []))
        except Exception:
            return 0.0

    async def get_revenue_by_platform(self) -> dict:
        try:
            result = self._client.table("revenue")\
                .select("platform, amount")\
                .execute()
            totals: dict = {}
            for r in (result.data or []):
                platform = r.get("platform", "unknown")
                totals[platform] = totals.get(platform, 0.0) + float(r["amount"])
            return totals
        except Exception:
            return {}

    # ── PRODUCTOS ─────────────────────────────────────────
    async def save_product(
        self,
        name: str,
        product_type: str,
        niche: str,
        platform: str,
        url: str,
        price: float,
        currency: str = "USD",
        metadata: dict = {}
    ) -> Optional[dict]:
        try:
            result = self._client.table("products").insert({
                "name": name,
                "type": product_type,
                "niche": niche,
                "platform": platform,
                "url": url,
                "price": price,
                "currency": currency,
                "metadata": metadata
            }).execute()
            return result.data[0] if result.data else None
        except Exception as e:
            await self.log_error(f"Error guardando producto: {e}")
            return None

    # ── SITIOS WEB ────────────────────────────────────────
    async def save_website(
        self,
        name: str,
        niche: str,
        language: str,
        market: str,
        github_url: str,
        vercel_url: str,
        metadata: dict = {}
    ) -> Optional[dict]:
        try:
            result = self._client.table("websites").insert({
                "name": name,
                "niche": niche,
                "language": language,
                "market": market,
                "github_url": github_url,
                "vercel_url": vercel_url,
                "status": "live",
                "metadata": metadata
            }).execute()
            return result.data[0] if result.data else None
        except Exception as e:
            await self.log_error(f"Error guardando website: {e}")
            return None

    # ── AGENTES ───────────────────────────────────────────
    async def update_agent_status(
        self,
        agent_name: str,
        status: str
    ) -> bool:
        try:
            from datetime import datetime, timezone
            self._client.table("agents").update({
                "status": status,
                "last_active": datetime.now(timezone.utc).isoformat()
            }).eq("name", agent_name).execute()
            return True
        except Exception:
            return False

    async def get_agent_by_name(self, name: str) -> Optional[dict]:
        try:
            result = self._client.table("agents")\
                .select("*")\
                .eq("name", name)\
                .single()\
                .execute()
            return result.data
        except Exception:
            return None

    # ── CICLOS ────────────────────────────────────────────
    async def start_cycle(self, cycle_number: int) -> Optional[dict]:
        try:
            result = self._client.table("autonomous_cycles").insert({
                "cycle_number": cycle_number,
                "status": "running"
            }).execute()
            return result.data[0] if result.data else None
        except Exception:
            return None

    async def complete_cycle(
        self,
        cycle_id: str,
        tasks_planned: int,
        tasks_completed: int,
        tasks_failed: int,
        revenue_generated: float,
        decisions: list
    ) -> bool:
        try:
            from datetime import datetime, timezone
            self._client.table("autonomous_cycles").update({
                "status": "completed",
                "tasks_planned": tasks_planned,
                "tasks_completed": tasks_completed,
                "tasks_failed": tasks_failed,
                "revenue_generated": revenue_generated,
                "decisions": decisions,
                "completed_at": datetime.now(timezone.utc).isoformat()
            }).eq("id", cycle_id).execute()
            return True
        except Exception:
            return False

    # ── MERCADO ───────────────────────────────────────────
    async def save_market_intelligence(
        self,
        niche: str,
        market: str,
        language: str,
        trend_score: int,
        competition_score: int,
        opportunity_score: int,
        data: dict
    ) -> Optional[dict]:
        try:
            result = self._client.table("market_intelligence").insert({
                "niche": niche,
                "market": market,
                "language": language,
                "trend_score": trend_score,
                "competition_score": competition_score,
                "opportunity_score": opportunity_score,
                "data": data
            }).execute()
            return result.data[0] if result.data else None
        except Exception:
            return None

    async def get_best_opportunities(self, limit: int = 5) -> list:
        try:
            result = self._client.table("market_intelligence")\
                .select("*")\
                .order("opportunity_score", desc=True)\
                .limit(limit)\
                .execute()
            return result.data or []
        except Exception:
            return []


# ── SINGLETON ─────────────────────────────────────────────
_db: Optional[AriaDatabase] = None


def get_db() -> AriaDatabase:
    global _db
    if _db is None:
        _db = AriaDatabase()
    return _db

