from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

from apps.core.memory.redis_client import get_cache

_LEADS_KEY = "crm:leads:v1"
_CUSTOMERS_KEY = "crm:customers:v1"
_LEADS_TTL = 86400 * 180
_CUSTOMERS_TTL = 86400 * 365


class LeadStage(str, Enum):
    SUBSCRIBER = "subscriber"
    PROSPECT = "prospect"
    QUALIFIED = "qualified"
    PROPOSAL = "proposal"
    NEGOTIATION = "negotiation"
    CUSTOMER = "customer"


_STAGE_ORDER = [
    LeadStage.SUBSCRIBER,
    LeadStage.PROSPECT,
    LeadStage.QUALIFIED,
    LeadStage.PROPOSAL,
    LeadStage.NEGOTIATION,
    LeadStage.CUSTOMER,
]


class ChurnRisk(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


@dataclass
class Lead:
    lead_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    email: str = ""
    name: str = ""
    source: str = ""
    stage: LeadStage = LeadStage.SUBSCRIBER
    score: float = 0.0
    tags: list[str] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)
    last_contact_ts: float = 0.0
    notes: str = ""

    @property
    def days_since_contact(self) -> float:
        if not self.last_contact_ts:
            return 999.0
        return (time.time() - self.last_contact_ts) / 86400

    def to_dict(self) -> dict:
        return {
            "lead_id": self.lead_id,
            "email": self.email,
            "name": self.name,
            "source": self.source,
            "stage": self.stage.value,
            "score": self.score,
            "tags": self.tags,
            "created_at": self.created_at,
            "last_contact_ts": self.last_contact_ts,
            "notes": self.notes,
        }

    @classmethod
    def from_dict(cls, d: dict) -> Lead:
        return cls(
            lead_id=d["lead_id"],
            email=d["email"],
            name=d.get("name", ""),
            source=d.get("source", ""),
            stage=LeadStage(d.get("stage", LeadStage.SUBSCRIBER.value)),
            score=d.get("score", 0.0),
            tags=d.get("tags", []),
            created_at=d.get("created_at", time.time()),
            last_contact_ts=d.get("last_contact_ts", 0.0),
            notes=d.get("notes", ""),
        )


@dataclass
class Customer:
    customer_id: str
    email: str
    name: str = ""
    total_spent_usd: float = 0.0
    order_count: int = 0
    last_purchase_ts: float = 0.0
    segments: list[str] = field(default_factory=list)
    churn_risk: ChurnRisk = ChurnRisk.LOW
    predicted_ltv: float = 0.0

    @property
    def avg_order_value(self) -> float:
        return self.total_spent_usd / max(self.order_count, 1)

    @property
    def days_since_purchase(self) -> float:
        if not self.last_purchase_ts:
            return 999.0
        return (time.time() - self.last_purchase_ts) / 86400

    def to_dict(self) -> dict:
        return {
            "customer_id": self.customer_id,
            "email": self.email,
            "name": self.name,
            "total_spent_usd": self.total_spent_usd,
            "order_count": self.order_count,
            "last_purchase_ts": self.last_purchase_ts,
            "segments": self.segments,
            "churn_risk": self.churn_risk.value,
            "predicted_ltv": self.predicted_ltv,
        }

    @classmethod
    def from_dict(cls, d: dict) -> Customer:
        return cls(
            customer_id=d["customer_id"],
            email=d["email"],
            name=d.get("name", ""),
            total_spent_usd=d.get("total_spent_usd", 0.0),
            order_count=d.get("order_count", 0),
            last_purchase_ts=d.get("last_purchase_ts", 0.0),
            segments=d.get("segments", []),
            churn_risk=ChurnRisk(d.get("churn_risk", ChurnRisk.LOW.value)),
            predicted_ltv=d.get("predicted_ltv", 0.0),
        )


class CRMEngine:
    def __init__(self) -> None:
        self._leads: dict[str, Lead] = {}
        self._customers: dict[str, Customer] = {}
        self._leads_loaded = False
        self._customers_loaded = False

    # ------------------------------------------------------------------
    # Persistence helpers
    # ------------------------------------------------------------------

    async def _load_leads(self) -> dict[str, Lead]:
        if not self._leads_loaded:
            try:
                cache = get_cache()
                data = await cache.get(_LEADS_KEY)
                if data and isinstance(data, dict):
                    self._leads = {k: Lead.from_dict(v) for k, v in data.items()}
            except Exception:
                pass
            self._leads_loaded = True
        return self._leads

    async def _save_leads(self, leads: dict[str, Lead]) -> None:
        self._leads = leads
        try:
            cache = get_cache()
            await cache.set(_LEADS_KEY, {k: v.to_dict() for k, v in leads.items()}, ttl_seconds=_LEADS_TTL)
        except Exception:
            pass

    async def _load_customers(self) -> dict[str, Customer]:
        if not self._customers_loaded:
            try:
                cache = get_cache()
                data = await cache.get(_CUSTOMERS_KEY)
                if data and isinstance(data, dict):
                    self._customers = {k: Customer.from_dict(v) for k, v in data.items()}
            except Exception:
                pass
            self._customers_loaded = True
        return self._customers

    async def _save_customers(self, customers: dict[str, Customer]) -> None:
        self._customers = customers
        try:
            cache = get_cache()
            await cache.set(_CUSTOMERS_KEY, {k: v.to_dict() for k, v in customers.items()}, ttl_seconds=_CUSTOMERS_TTL)
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Lead management
    # ------------------------------------------------------------------

    async def add_lead(self, email: str, name: str = "", source: str = "", initial_score: float = 40.0) -> Lead:
        leads = await self._load_leads()
        # deduplicate by email
        for existing in leads.values():
            if existing.email.lower() == email.lower():
                return existing
        lead = Lead(email=email, name=name, source=source, score=initial_score)
        leads[lead.lead_id] = lead
        await self._save_leads(leads)
        return lead

    async def update_lead_stage(self, lead_id: str, new_stage: LeadStage, notes: str = "") -> Optional[Lead]:
        leads = await self._load_leads()
        lead = leads.get(lead_id)
        if not lead:
            return None
        old_idx = _STAGE_ORDER.index(lead.stage) if lead.stage in _STAGE_ORDER else 0
        new_idx = _STAGE_ORDER.index(new_stage) if new_stage in _STAGE_ORDER else 0
        advancement = max(0, new_idx - old_idx)
        lead.stage = new_stage
        lead.last_contact_ts = time.time()
        lead.score += 10.0 * advancement
        if notes:
            lead.notes = notes
        await self._save_leads(leads)
        return lead

    async def qualify_leads(self) -> list[Lead]:
        leads = await self._load_leads()
        newly_qualified: list[Lead] = []
        for lead in leads.values():
            if lead.days_since_contact < 7:
                lead.score += 20.0
            if lead.stage != LeadStage.SUBSCRIBER:
                lead.score += 15.0
            if lead.score >= 60.0 and lead.stage == LeadStage.SUBSCRIBER:
                lead.stage = LeadStage.QUALIFIED
                newly_qualified.append(lead)
        await self._save_leads(leads)
        return newly_qualified

    # ------------------------------------------------------------------
    # Customer management
    # ------------------------------------------------------------------

    async def add_customer(self, email: str, name: str, order_value: float, source: str = "shopify") -> Customer:
        customers = await self._load_customers()
        # find by email
        existing: Optional[Customer] = None
        for c in customers.values():
            if c.email.lower() == email.lower():
                existing = c
                break

        if existing:
            existing.total_spent_usd += order_value
            existing.order_count += 1
            existing.last_purchase_ts = time.time()
            if source not in existing.segments:
                existing.segments.append(source)
            await self._save_customers(customers)
            return existing

        customer = Customer(
            customer_id=str(uuid.uuid4()),
            email=email,
            name=name,
            total_spent_usd=order_value,
            order_count=1,
            last_purchase_ts=time.time(),
            segments=[source],
        )
        customers[customer.customer_id] = customer
        await self._save_customers(customers)
        return customer

    async def predict_churn(self, customer_id: str) -> ChurnRisk:
        customers = await self._load_customers()
        customer = customers.get(customer_id)
        if not customer:
            return ChurnRisk.LOW
        days = customer.days_since_purchase
        if days > 180:
            risk = ChurnRisk.CRITICAL
        elif days > 90:
            risk = ChurnRisk.HIGH
        elif days > 60:
            risk = ChurnRisk.MEDIUM
        else:
            risk = ChurnRisk.LOW
        customer.churn_risk = risk
        await self._save_customers(customers)
        return risk

    async def high_risk_customers(self) -> list[Customer]:
        customers = await self._load_customers()
        return [c for c in customers.values() if c.churn_risk in (ChurnRisk.HIGH, ChurnRisk.CRITICAL)]

    async def retention_candidates(self) -> list[Customer]:
        customers = await self._load_customers()
        at_risk = [
            c for c in customers.values()
            if c.churn_risk in (ChurnRisk.MEDIUM, ChurnRisk.HIGH, ChurnRisk.CRITICAL)
        ]
        return sorted(at_risk, key=lambda c: c.total_spent_usd, reverse=True)[:20]

    async def segment_customers(self) -> dict[str, list[Customer]]:
        customers = await self._load_customers()
        now = time.time()
        vip: list[Customer] = []
        loyal: list[Customer] = []
        new: list[Customer] = []
        at_risk: list[Customer] = []
        seen: set[str] = set()

        for c in customers.values():
            days_new = (now - c.last_purchase_ts) / 86400 if c.last_purchase_ts else 999
            if c.total_spent_usd > 500:
                vip.append(c)
                seen.add(c.customer_id)
            if c.order_count >= 3 and c.customer_id not in seen:
                loyal.append(c)
                seen.add(c.customer_id)
            if days_new < 30 and c.customer_id not in seen:
                new.append(c)
                seen.add(c.customer_id)
            if c.churn_risk in (ChurnRisk.MEDIUM, ChurnRisk.HIGH, ChurnRisk.CRITICAL):
                at_risk.append(c)

        return {"VIP": vip, "Loyal": loyal, "New": new, "At_Risk": at_risk}

    async def funnel_summary(self) -> dict:
        leads = await self._load_leads()
        counts: dict[str, int] = {s.value: 0 for s in LeadStage}
        total_score: dict[str, float] = {s.value: 0.0 for s in LeadStage}
        for lead in leads.values():
            counts[lead.stage.value] += 1
            total_score[lead.stage.value] += lead.score

        stage_keys = [s.value for s in _STAGE_ORDER]
        conversion_rates: dict[str, float] = {}
        for i in range(len(stage_keys) - 1):
            current = stage_keys[i]
            next_s = stage_keys[i + 1]
            conversion_rates[f"{current}->{next_s}"] = (
                counts[next_s] / max(counts[current], 1)
            )

        avg_score: dict[str, float] = {
            s: round(total_score[s] / max(counts[s], 1), 2)
            for s in stage_keys
        }

        return {
            "counts_by_stage": counts,
            "conversion_rates": conversion_rates,
            "avg_score_by_stage": avg_score,
        }

    def summary(self) -> dict:
        return {
            "total_leads": 0,
            "total_customers": 0,
            "high_risk_count": 0,
            "vip_count": 0,
            "total_revenue_tracked": 0.0,
        }

    async def async_summary(self) -> dict:
        leads = await self._load_leads()
        customers = await self._load_customers()
        high_risk = sum(1 for c in customers.values() if c.churn_risk in (ChurnRisk.HIGH, ChurnRisk.CRITICAL))
        vip = sum(1 for c in customers.values() if c.total_spent_usd > 500)
        total_revenue = sum(c.total_spent_usd for c in customers.values())
        return {
            "total_leads": len(leads),
            "total_customers": len(customers),
            "high_risk_count": high_risk,
            "vip_count": vip,
            "total_revenue_tracked": round(total_revenue, 2),
        }


_crm_instance: CRMEngine | None = None


def get_crm_engine() -> CRMEngine:
    global _crm_instance
    if _crm_instance is None:
        _crm_instance = CRMEngine()
    return _crm_instance
