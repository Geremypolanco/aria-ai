from __future__ import annotations

import time
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from apps.core.memory.redis_client import get_cache

_TTL = 365 * 24 * 3600
_CACHE_KEY_TEMPLATE = "business:cashflow:v1:{workspace_id}"
# Pre-multi-tenancy global key — every entry lived here when there was only
# ever one workspace. See CashflowEngine._load()'s fallback for why this is
# still read (never written) going forward.
_LEGACY_CACHE_KEY = "business:cashflow:v1"


@dataclass
class CashflowEntry:
    entry_id: str
    type: str
    amount_usd: float
    category: str
    description: str
    date_ts: float
    recurring: bool
    frequency_days: int = 0

    def to_dict(self) -> dict:
        return {
            "entry_id": self.entry_id,
            "type": self.type,
            "amount_usd": self.amount_usd,
            "category": self.category,
            "description": self.description,
            "date_ts": self.date_ts,
            "recurring": self.recurring,
            "frequency_days": self.frequency_days,
        }

    @classmethod
    def from_dict(cls, data: dict) -> CashflowEntry:
        return cls(
            entry_id=data["entry_id"],
            type=data["type"],
            amount_usd=data["amount_usd"],
            category=data.get("category", "general"),
            description=data.get("description", ""),
            date_ts=data.get("date_ts", time.time()),
            recurring=data.get("recurring", False),
            frequency_days=data.get("frequency_days", 0),
        )


def _month_key(ts: float) -> str:
    dt = datetime.fromtimestamp(ts, tz=UTC)
    return dt.strftime("%Y-%m")


class CashflowEngine:
    def __init__(self, workspace_id: str = "_default") -> None:
        self._workspace_id = workspace_id or "_default"
        self._cache_key = _CACHE_KEY_TEMPLATE.format(workspace_id=self._workspace_id)
        self._entries: list[dict] = []
        self._loaded = False

    def _is_legacy_owner_workspace(self) -> bool:
        """True only for the actual configured owner's own workspace_id —
        the sole tenant that could possibly have data under the old global
        key, back from before workspaces existed. Deliberately NOT a
        fallback for every workspace with an empty ledger: that would leak
        the owner's real financial history into any other/new workspace's
        view the first time it loads, exactly the cross-tenant bug this
        conversion exists to close."""
        from apps.core import auth

        return self._workspace_id in auth.owner_emails()

    async def _load(self) -> None:
        if self._loaded:
            return
        try:
            cache = get_cache()
            data = await cache.get(self._cache_key)
            if not data and self._is_legacy_owner_workspace():
                data = await cache.get(_LEGACY_CACHE_KEY)
            if data and isinstance(data, list):
                self._entries = data
        except Exception:
            pass
        self._loaded = True

    async def _save(self) -> None:
        self._loaded = True
        try:
            cache = get_cache()
            await cache.set(self._cache_key, self._entries, ttl_seconds=_TTL)
        except Exception:
            pass

    async def record(
        self,
        type: str,
        amount: float,
        category: str,
        description: str = "",
        recurring: bool = False,
        frequency_days: int = 0,
    ) -> CashflowEntry:
        await self._load()
        entry = CashflowEntry(
            entry_id=str(uuid.uuid4()),
            type=type,
            amount_usd=abs(amount),
            category=category,
            description=description,
            date_ts=time.time(),
            recurring=recurring,
            frequency_days=frequency_days,
        )
        self._entries.append(entry.to_dict())
        await self._save()
        return entry

    async def current_balance(self) -> float:
        await self._load()
        balance = 0.0
        for e in self._entries:
            if e["type"] == "income":
                balance += e["amount_usd"]
            else:
                balance -= e["amount_usd"]
        return round(balance, 2)

    async def monthly_summary(self, months_back: int = 3) -> list[dict]:
        await self._load()
        now = time.time()
        cutoff = now - months_back * 30 * 86400
        monthly: dict[str, dict[str, float]] = {}
        for e in self._entries:
            if e["date_ts"] < cutoff:
                continue
            mk = _month_key(e["date_ts"])
            if mk not in monthly:
                monthly[mk] = {"income": 0.0, "expenses": 0.0}
            if e["type"] == "income":
                monthly[mk]["income"] += e["amount_usd"]
            else:
                monthly[mk]["expenses"] += e["amount_usd"]
        result: list[dict] = []
        for month, vals in sorted(monthly.items()):
            income = vals["income"]
            expenses = vals["expenses"]
            net = income - expenses
            margin = round(net / max(income, 0.01) * 100, 2)
            result.append(
                {
                    "month": month,
                    "income_usd": round(income, 2),
                    "expenses_usd": round(expenses, 2),
                    "net_usd": round(net, 2),
                    "net_margin_pct": margin,
                }
            )
        return result

    async def forecast_cashflow(self, months_ahead: int = 3) -> list[dict]:
        await self._load()
        recurring_income: list[dict] = []
        recurring_expenses: list[dict] = []
        for e in self._entries:
            if e.get("recurring") and e.get("frequency_days", 0) > 0:
                monthly_amount = e["amount_usd"] * (30 / e["frequency_days"])
                if e["type"] == "income":
                    recurring_income.append({"amount": monthly_amount, "category": e["category"]})
                else:
                    recurring_expenses.append({"amount": monthly_amount, "category": e["category"]})
        monthly_income_est = sum(r["amount"] for r in recurring_income)
        monthly_expense_est = sum(r["amount"] for r in recurring_expenses)
        if monthly_income_est == 0 and monthly_expense_est == 0:
            # Estimate from last 30 days
            cutoff = time.time() - 30 * 86400
            recent = [e for e in self._entries if e["date_ts"] >= cutoff]
            monthly_income_est = sum(e["amount_usd"] for e in recent if e["type"] == "income")
            monthly_expense_est = sum(e["amount_usd"] for e in recent if e["type"] == "expense")
        forecast: list[dict] = []
        cumulative = 0.0
        for i in range(1, months_ahead + 1):
            net = monthly_income_est - monthly_expense_est
            cumulative += net
            forecast.append(
                {
                    "month": i,
                    "projected_income": round(monthly_income_est, 2),
                    "projected_expenses": round(monthly_expense_est, 2),
                    "projected_net": round(net, 2),
                    "cumulative_net": round(cumulative, 2),
                }
            )
        return forecast

    async def runway_months(self, monthly_burn_usd: float | None = None) -> float:
        await self._load()
        balance = await self.current_balance()
        if monthly_burn_usd is None:
            cutoff = time.time() - 30 * 86400
            recent_expenses = [
                e["amount_usd"]
                for e in self._entries
                if e["type"] == "expense" and e["date_ts"] >= cutoff
            ]
            monthly_burn_usd = sum(recent_expenses)
        burn = max(monthly_burn_usd, 0.01)
        return round(balance / burn, 2)

    async def optimization_tips(self) -> list[str]:
        await self._load()
        tips: list[str] = []
        expense_categories: dict[str, float] = {}
        income_categories: dict[str, float] = {}
        for e in self._entries:
            cat = e.get("category", "other")
            if e["type"] == "expense":
                expense_categories[cat] = expense_categories.get(cat, 0) + e["amount_usd"]
            else:
                income_categories[cat] = income_categories.get(cat, 0) + e["amount_usd"]
        if expense_categories:
            top_expense_cat = max(expense_categories, key=lambda k: expense_categories[k])
            tips.append(
                f"Largest expense category is '{top_expense_cat}' — review for optimisation opportunities"
            )
        recurring_count = sum(1 for e in self._entries if e.get("recurring"))
        if recurring_count > 5:
            tips.append(
                f"You have {recurring_count} recurring entries — audit subscriptions for unused services"
            )
        balance = await self.current_balance()
        if balance < 0:
            tips.append(
                "Negative balance detected — prioritise revenue generation over new expenses"
            )
        elif balance > 0 and len(income_categories) < 2:
            tips.append("Single income stream detected — diversify revenue sources to reduce risk")
        tips.append("Set up automatic monthly savings to build a 3-month cash reserve")
        tips.append(
            "Review expense-to-revenue ratio monthly; target below 60% for sustainable margins"
        )
        return tips[:5]

    def summary(self) -> dict:
        income = sum(e["amount_usd"] for e in self._entries if e["type"] == "income")
        expenses = sum(e["amount_usd"] for e in self._entries if e["type"] == "expense")
        cutoff = time.time() - 30 * 86400
        monthly_burn = sum(
            e["amount_usd"]
            for e in self._entries
            if e["type"] == "expense" and e["date_ts"] >= cutoff
        )
        return {
            "current_balance_usd": round(income - expenses, 2),
            "monthly_burn_usd": round(monthly_burn, 2),
        }


_cashflow_engines: dict[str, CashflowEngine] = {}


def get_cashflow_engine(workspace_id: str = "_default") -> CashflowEngine:
    """One CashflowEngine per workspace (apps/core/tenancy.py), not one
    process-wide instance — the previous single-instance singleton is
    exactly what made every team share one ledger regardless of who was
    asking. `workspace_id` defaults to "_default" only for callers that
    haven't been converted to pass a real one yet; every caller reachable
    from a user request should resolve and pass tenancy.workspace_id_for(email)."""
    workspace_id = workspace_id or "_default"
    if workspace_id not in _cashflow_engines:
        _cashflow_engines[workspace_id] = CashflowEngine(workspace_id)
    return _cashflow_engines[workspace_id]
