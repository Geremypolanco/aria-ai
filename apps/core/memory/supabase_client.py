"""
Cliente Supabase tipado para Aria AI.
Gestiona toda la persistencia de datos del sistema.
"""
from __future__ import annotations
from typing import Optional, Any
from supabase import create_client, Client
from apps.core.config import settings
import json


class AriaDatabase:

    def __init__(self):
        self._client: Client = create_client(settings.SUPABASE_URL, settings.SUPABASE_KEY)

    # ── LOGS ──────────────────────────────────────────────

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

    # ── TAREAS ────────────────────────────────────────────

    async def create_task(self, agent_id: str, task_type: str, input_data: dict,
                          priority: int = 5, requires_approval: bool = False) -> Optional[dict]:
        try:
            result = self._client.table("tasks").insert({
                "agent_id": agent_id, "type": task_type, "status": "pending",
                "priority": priority, "input": input_data, "requires_approval": requires_approval
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
            result = self._client.table("tasks").select("*")                 .eq("status", "pending").order("priority", desc=True)                 .order("created_at").limit(limit).execute()
            return result.data or []
        except Exception:
            return []

    async def get_tasks_by_agent(self, agent_name: str, limit: int = 10) -> list:
        try:
            result = self._client.table("tasks").select("*")                 .eq("agent_id", agent_name).order("created_at", desc=True).limit(limit).execute()
            return result.data or []
        except Exception:
            return []

    # ── APROBACIONES ──────────────────────────────────────

    async def create_approval(self, agent_name: str, action_type: str, detail: str,
                              amount_usd: float = 0.0, metadata: dict = {}) -> Optional[dict]:
        try:
            result = self._client.table("approvals").insert({
                "agent_name": agent_name, "action_type": action_type,
                "detail": detail, "amount_usd": amount_usd,
                "status": "pending", "metadata": metadata
            }).execute()
            return result.data[0] if result.data else None
        except Exception as e:
            await self.log_error(f"Error creando aprobación: {e}")
            return None

    async def get_pending_approvals(self, limit: int = 10) -> list:
        try:
            result = self._client.table("approvals").select("*")                 .eq("status", "pending").order("created_at").limit(limit).execute()
            return result.data or []
        except Exception:
            return []

    async def resolve_approval(self, approval_id: str, decision: str) -> bool:
        """Aprueba o rechaza una acción. decision: 'approved' | 'rejected'"""
        try:
            from datetime import datetime, timezone
            self._client.table("approvals").update({
                "status": decision,
                "decided_at": datetime.now(timezone.utc).isoformat()
            }).eq("id", approval_id).execute()
            return True
        except Exception as e:
            await self.log_error(f"Error resolviendo aprobación {approval_id}: {e}")
            return False

    # ── INGRESOS ──────────────────────────────────────────

    async def record_revenue(self, platform: str, product_name: str, amount: float,
                             product_id: str = "", customer_id: str = "", metadata: dict = {}) -> Optional[dict]:
        try:
            result = self._client.table("revenue").insert({
                "platform": platform, "product_name": product_name,
                "amount": amount, "currency": "USD",
                "product_id": product_id, "customer_id": customer_id, "metadata": metadata
            }).execute()
            return result.data[0] if result.data else None
        except Exception as e:
            await self.log_error(f"Error registrando revenue: {e}")
            return None

    async def get_total_revenue(self) -> float:
        try:
            result = self._client.table("revenue").select("amount").execute()
            return sum(float(r.get("amount", 0)) for r in (result.data or []))
        except Exception:
            return 0.0

    async def get_revenue_by_platform(self) -> dict[str, float]:
        try:
            result = self._client.table("revenue").select("platform, amount").execute()
            totals: dict[str, float] = {}
            for row in (result.data or []):
                p = row.get("platform", "unknown")
                totals[p] = totals.get(p, 0.0) + float(row.get("amount", 0))
            return totals
        except Exception:
            return {}

    async def get_revenue_this_month(self) -> float:
        try:
            from datetime import datetime, timezone
            now = datetime.now(timezone.utc)
            start = datetime(now.year, now.month, 1, tzinfo=timezone.utc).isoformat()
            result = self._client.table("revenue").select("amount").gte("created_at", start).execute()
            return sum(float(r.get("amount", 0)) for r in (result.data or []))
        except Exception:
            return 0.0

    # ── PRODUCTOS ─────────────────────────────────────────

    async def create_product(self, name: str, description: str, niche: str,
                             platform: str, price_usd: float, url: str = "",
                             external_id: str = "", metadata: dict = {}) -> Optional[dict]:
        try:
            result = self._client.table("products").insert({
                "name": name, "description": description, "niche": niche,
                "platform": platform, "price_usd": price_usd, "url": url,
                "external_id": external_id, "metadata": metadata
            }).execute()
            return result.data[0] if result.data else None
        except Exception as e:
            await self.log_error(f"Error creando producto: {e}")
            return None

    async def get_active_products(self, limit: int = 20) -> list:
        try:
            result = self._client.table("products").select("*")                 .eq("status", "active").order("created_at", desc=True).limit(limit).execute()
            return result.data or []
        except Exception:
            return []

    async def update_product_stats(self, product_id: str, sales_count: int, revenue_usd: float) -> bool:
        try:
            self._client.table("products").update({
                "sales_count": sales_count, "revenue_usd": revenue_usd
            }).eq("id", product_id).execute()
            return True
        except Exception:
            return False

    # ── MARKET INTELLIGENCE ───────────────────────────────

    async def save_market_intelligence(self, niche: str, language: str, data: dict, score: dict) -> Optional[dict]:
        try:
            result = self._client.table("market_intelligence").insert({
                "niche": niche, "language": language,
                "demand_score": score.get("demand_score", 0),
                "competition_score": score.get("competition_score", 0),
                "opportunity_score": score.get("opportunity_score", 0),
                "monetization_potential": data.get("monetization_potential", "medio"),
                "recommended_products": data.get("recommended_products", []),
                "keywords": data.get("keywords", []),
                "insights": data,
            }).execute()
            return result.data[0] if result.data else None
        except Exception as e:
            await self.log_error(f"Error guardando market intelligence: {e}")
            return None

    async def get_top_niches(self, limit: int = 5) -> list:
        try:
            result = self._client.table("market_intelligence").select("*")                 .order("opportunity_score", desc=True).limit(limit).execute()
            return result.data or []
        except Exception:
            return []

    # ── CICLOS AUTÓNOMOS ──────────────────────────────────

    async def save_cycle(self, cycle_number: int, missions: dict, revenue_gen: float = 0.0,
                         duration_ms: int = 0) -> Optional[dict]:
        try:
            from datetime import datetime, timezone
            result = self._client.table("autonomous_cycles").insert({
                "cycle_number": cycle_number, "status": "completed",
                "missions": missions, "revenue_gen": revenue_gen,
                "duration_ms": duration_ms,
                "completed_at": datetime.now(timezone.utc).isoformat()
            }).execute()
            return result.data[0] if result.data else None
        except Exception as e:
            await self.log_error(f"Error guardando ciclo: {e}")
            return None

    async def get_cycle_stats(self) -> dict:
        try:
            result = self._client.table("autonomous_cycles").select("*")                 .eq("status", "completed").execute()
            cycles = result.data or []
            return {
                "total_cycles": len(cycles),
                "avg_duration_ms": int(sum(c.get("duration_ms", 0) for c in cycles) / max(len(cycles), 1)),
                "total_revenue": sum(float(c.get("revenue_gen", 0)) for c in cycles),
            }
        except Exception:
            return {"total_cycles": 0, "avg_duration_ms": 0, "total_revenue": 0.0}

    # ── CAMPAÑAS DE MARKETING ─────────────────────────────

    async def save_marketing_campaign(self, name: str, platform: str, type_: str,
                                      content: str, target_niche: str = "", metadata: dict = {}) -> Optional[dict]:
        try:
            from datetime import datetime, timezone
            result = self._client.table("marketing_campaigns").insert({
                "name": name, "platform": platform, "type": type_,
                "status": "published", "content": content,
                "target_niche": target_niche, "metadata": metadata,
                "published_at": datetime.now(timezone.utc).isoformat()
            }).execute()
            return result.data[0] if result.data else None
        except Exception as e:
            await self.log_error(f"Error guardando campaña: {e}")
            return None


# ── SINGLETON ──────────────────────────────────────────────────

_db_instance: Optional[AriaDatabase] = None

def get_db() -> AriaDatabase:
    global _db_instance
    if _db_instance is None:
        _db_instance = AriaDatabase()
    return _db_instance
