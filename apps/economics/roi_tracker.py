"""
ARIA ROI Tracker — tracks return on investment per action, department, and campaign.
Provides AI-powered recommendations on where to double down.
"""
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Optional

from apps.core.memory.redis_client import get_cache
from apps.core.tools.ai_client import get_ai_client, AIModel

_ROI_KEY = "economics:roi:v1"
_ROI_TTL = 86400 * 90  # 90 days


@dataclass
class ROIRecord:
    record_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    name: str = ""
    category: str = ""       # "action", "campaign", "department", "experiment"
    investment_usd: float = 0.0
    returns_usd: float = 0.0
    roi_pct: float = 0.0     # (returns - investment) / investment * 100
    payback_days: float = 0.0
    status: str = "tracking"  # "tracking"|"concluded"|"failed"
    started_at: float = field(default_factory=time.time)
    concluded_at: float = 0.0

    def roi_multiple(self) -> float:
        return self.returns_usd / max(self.investment_usd, 0.01)

    def to_dict(self) -> dict:
        return {
            "record_id": self.record_id,
            "name": self.name,
            "category": self.category,
            "investment_usd": round(self.investment_usd, 4),
            "returns_usd": round(self.returns_usd, 4),
            "roi_pct": round(self.roi_pct, 4),
            "payback_days": round(self.payback_days, 4),
            "roi_multiple": round(self.roi_multiple(), 4),
            "status": self.status,
            "started_at": self.started_at,
            "concluded_at": self.concluded_at,
        }


class ROITracker:
    """Tracks ROI per action, department, and campaign."""

    def __init__(self) -> None:
        self._records: list[dict] = []
        self._loaded = False

    async def _load(self) -> None:
        if not self._loaded:
            try:
                cache = get_cache()
                data = await cache.get(_ROI_KEY)
                if data and isinstance(data, dict):
                    self._records = data.get("records", [])
            except Exception:
                pass
            self._loaded = True

    async def _save(self) -> None:
        try:
            cache = get_cache()
            await cache.set(_ROI_KEY, {"records": self._records}, ttl_seconds=_ROI_TTL)
        except Exception:
            pass

    async def track(self, name: str, category: str, investment_usd: float) -> ROIRecord:
        """Start tracking a new investment."""
        await self._load()
        record = ROIRecord(
            name=name,
            category=category,
            investment_usd=investment_usd,
        )
        self._records.append(record.to_dict())
        await self._save()
        return record

    async def update_returns(self, record_id: str, returns_usd: float) -> Optional[ROIRecord]:
        """Update returns and recalculate ROI metrics."""
        await self._load()
        for i, r in enumerate(self._records):
            if r.get("record_id") == record_id:
                investment = r.get("investment_usd", 0.0)
                roi_pct = (returns_usd - investment) / max(investment, 0.01) * 100
                # payback_days = investment / (returns/30) if returns > 0 else 999
                payback_days = (investment / (returns_usd / 30)) if returns_usd > 0 else 999.0

                r["returns_usd"] = round(returns_usd, 4)
                r["roi_pct"] = round(roi_pct, 4)
                r["payback_days"] = round(payback_days, 4)
                r["roi_multiple"] = round(returns_usd / max(investment, 0.01), 4)
                self._records[i] = r
                await self._save()

                record = ROIRecord(
                    record_id=r["record_id"],
                    name=r.get("name", ""),
                    category=r.get("category", ""),
                    investment_usd=investment,
                    returns_usd=returns_usd,
                    roi_pct=roi_pct,
                    payback_days=payback_days,
                    status=r.get("status", "tracking"),
                    started_at=r.get("started_at", time.time()),
                    concluded_at=r.get("concluded_at", 0.0),
                )
                return record
        return None

    async def conclude(self, record_id: str, final_returns_usd: float) -> Optional[ROIRecord]:
        """Conclude an investment with final returns."""
        await self._load()
        for i, r in enumerate(self._records):
            if r.get("record_id") == record_id:
                investment = r.get("investment_usd", 0.0)
                roi_pct = (final_returns_usd - investment) / max(investment, 0.01) * 100
                payback_days = (investment / (final_returns_usd / 30)) if final_returns_usd > 0 else 999.0
                concluded_at = time.time()
                status = "concluded" if final_returns_usd >= investment else "failed"

                r["returns_usd"] = round(final_returns_usd, 4)
                r["roi_pct"] = round(roi_pct, 4)
                r["payback_days"] = round(payback_days, 4)
                r["roi_multiple"] = round(final_returns_usd / max(investment, 0.01), 4)
                r["status"] = status
                r["concluded_at"] = concluded_at
                self._records[i] = r
                await self._save()

                record = ROIRecord(
                    record_id=r["record_id"],
                    name=r.get("name", ""),
                    category=r.get("category", ""),
                    investment_usd=investment,
                    returns_usd=final_returns_usd,
                    roi_pct=roi_pct,
                    payback_days=payback_days,
                    status=status,
                    started_at=r.get("started_at", time.time()),
                    concluded_at=concluded_at,
                )
                return record
        return None

    def top_roi_records(self, limit: int = 10) -> list[dict]:
        """Return top ROI records sorted by roi_pct descending."""
        return sorted(self._records, key=lambda r: r.get("roi_pct", 0.0), reverse=True)[:limit]

    def failed_investments(self, threshold_roi_pct: float = -20.0) -> list[dict]:
        """Return investments below the threshold ROI percentage."""
        return [r for r in self._records if r.get("roi_pct", 0.0) <= threshold_roi_pct]

    def roi_summary(self) -> dict:
        """Summary of all tracked ROI records."""
        if not self._records:
            return {
                "total_tracked": 0,
                "avg_roi_pct": 0.0,
                "best_roi": {},
                "worst_roi": {},
                "total_returns": 0.0,
                "total_invested": 0.0,
            }

        total_invested = sum(r.get("investment_usd", 0.0) for r in self._records)
        total_returns = sum(r.get("returns_usd", 0.0) for r in self._records)
        avg_roi_pct = sum(r.get("roi_pct", 0.0) for r in self._records) / len(self._records)

        sorted_by_roi = sorted(self._records, key=lambda r: r.get("roi_pct", 0.0), reverse=True)
        best_roi = sorted_by_roi[0] if sorted_by_roi else {}
        worst_roi = sorted_by_roi[-1] if len(sorted_by_roi) > 1 else {}

        return {
            "total_tracked": len(self._records),
            "avg_roi_pct": round(avg_roi_pct, 4),
            "best_roi": best_roi,
            "worst_roi": worst_roi,
            "total_returns": round(total_returns, 4),
            "total_invested": round(total_invested, 4),
        }

    async def ai_roi_recommendation(self, records: list[dict]) -> str:
        """AI analyzes ROI records and suggests where to double down."""
        if not records:
            return "No ROI records to analyze."

        records_text = "\n".join(
            f"- {r.get('name', 'Unnamed')} [{r.get('category', 'unknown')}]: "
            f"ROI={r.get('roi_pct', 0):.1f}%, invested=${r.get('investment_usd', 0):.2f}, "
            f"returns=${r.get('returns_usd', 0):.2f}"
            for r in records[:10]
        )

        try:
            ai = get_ai_client()
            resp = await ai.complete(
                system=(
                    "You are a business ROI analyst. Analyze investments and recommend "
                    "where to double down for maximum returns. Be specific and actionable."
                ),
                user=(
                    f"Analyze these ROI records and recommend the top 2-3 areas to double down on:\n"
                    f"{records_text}\n\n"
                    f"Provide specific recommendations with reasoning."
                ),
                model=AIModel.STRATEGY,
                max_tokens=400,
            )
            if resp.success:
                return resp.content
        except Exception:
            pass

        # Fallback
        top = sorted(records, key=lambda r: r.get("roi_pct", 0.0), reverse=True)
        if top:
            best = top[0]
            return (
                f"ROI analysis: Double down on {best.get('name', 'top performer')}. "
                f"Best ROI: {best.get('roi_pct', 0):.0f}%"
            )
        return "ROI analysis: Insufficient data for recommendations."


_instance: Optional[ROITracker] = None


def get_roi_tracker() -> ROITracker:
    global _instance
    if _instance is None:
        _instance = ROITracker()
    return _instance
