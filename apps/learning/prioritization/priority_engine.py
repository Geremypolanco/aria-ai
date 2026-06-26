"""
Priority Engine — Dynamically prioritizes actions based on economic signals,
learning history, and urgency.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field

from apps.core.memory.redis_client import get_cache
from apps.core.tools.ai_client import AIModel, get_ai_client

_PRIORITY_KEY = "learning:priority:v1"
_PRIORITY_TTL = 86400 * 30  # 30 days


@dataclass
class PriorityItem:
    item_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    title: str = ""
    action_type: str = ""
    base_score: float = 0.0  # raw score before adjustments
    urgency_boost: float = 0.0  # 0-1 urgency adjustment
    roi_multiplier_boost: float = 0.0  # from learning history
    final_score: float = 0.0  # computed: base + urgency + roi_boost
    rank: int = 0
    reasoning: str = ""
    estimated_revenue: float = 0.0
    estimated_hours: float = 0.0
    deadline_hours: float = 0.0  # 0 = no deadline

    def to_dict(self) -> dict:
        return {
            "item_id": self.item_id,
            "title": self.title,
            "action_type": self.action_type,
            "base_score": self.base_score,
            "urgency_boost": self.urgency_boost,
            "roi_multiplier_boost": self.roi_multiplier_boost,
            "final_score": self.final_score,
            "rank": self.rank,
            "reasoning": self.reasoning,
            "estimated_revenue": self.estimated_revenue,
            "estimated_hours": self.estimated_hours,
            "deadline_hours": self.deadline_hours,
        }


class PriorityEngine:
    """Dynamically prioritizes actions based on economic signals, learning history, and urgency."""

    def __init__(self) -> None:
        self._history: list[dict] = []  # past prioritization runs
        self._loaded = False

    async def _load(self) -> None:
        if not self._loaded:
            try:
                cache = get_cache()
                data = await cache.get(_PRIORITY_KEY)
                if isinstance(data, dict):
                    self._history = data.get("history", [])
            except Exception:
                pass
            self._loaded = True

    async def _save(self) -> None:
        try:
            cache = get_cache()
            await cache.set(
                _PRIORITY_KEY,
                {"history": self._history[-200:]},
                ttl_seconds=_PRIORITY_TTL,
            )
        except Exception:
            pass

    def _get_roi_boost(self, action_type: str) -> float:
        """Look up ROI multiplier boost from learning history if available."""
        try:
            from apps.learning.roi.roi_learner import get_roi_learner

            learner = get_roi_learner()
            best = learner.best_actions(top_n=10)
            for a in best:
                if a["action_type"] == action_type:
                    # Scale: avg_roi > 3.0 gives max 0.2 boost
                    return min(0.2, (a["avg_roi"] - 1.0) * 0.05)
        except Exception:
            pass
        return 0.0

    async def prioritize(self, items: list[dict]) -> list[PriorityItem]:
        """
        Prioritize a list of action items.
        Each input item: {title, action_type, estimated_revenue, estimated_hours, urgency, deadline_hours}
        """
        await self._load()

        priority_items: list[PriorityItem] = []

        for item in items:
            title = item.get("title", "")
            action_type = item.get("action_type", "")
            estimated_revenue = float(item.get("estimated_revenue", 0.0))
            estimated_hours = float(item.get("estimated_hours", 1.0))
            urgency = float(item.get("urgency", 0.0))
            deadline_hours = float(item.get("deadline_hours", 0.0))

            # Base score = revenue per hour
            base_score = estimated_revenue / max(estimated_hours, 0.1)

            # Urgency boost
            urgency_boost = urgency * 0.3 * base_score

            # ROI multiplier boost from learning history
            roi_boost = self._get_roi_boost(action_type) * base_score

            # Final score
            final_score = base_score + urgency_boost + roi_boost

            pi = PriorityItem(
                title=title,
                action_type=action_type,
                base_score=base_score,
                urgency_boost=urgency_boost,
                roi_multiplier_boost=roi_boost,
                final_score=final_score,
                estimated_revenue=estimated_revenue,
                estimated_hours=estimated_hours,
                deadline_hours=deadline_hours,
            )
            priority_items.append(pi)

        # Sort descending by final_score
        priority_items.sort(key=lambda x: x.final_score, reverse=True)

        # Assign ranks (1-based)
        for i, pi in enumerate(priority_items):
            pi.rank = i + 1

        # AI generates reasoning for top 3
        if priority_items:
            top3 = priority_items[:3]
            top3_summary = "\n".join(
                f"{i+1}. {pi.title} ({pi.action_type}): score={pi.final_score:.1f}, "
                f"revenue=${pi.estimated_revenue:.0f}, hours={pi.estimated_hours:.1f}"
                for i, pi in enumerate(top3)
            )
            ai = get_ai_client()
            resp = await ai.complete(
                system=(
                    "You are a business prioritization expert. Explain briefly why these top items "
                    "should be prioritized in this order. Be concise (1-2 sentences each)."
                ),
                user=f"Top priority items:\n{top3_summary}\n\nExplain prioritization reasoning.",
                model=AIModel.FAST,
                max_tokens=300,
            )
            if resp.success and resp.content:
                lines = resp.content.strip().split("\n")
                for i, pi in enumerate(top3):
                    if i < len(lines):
                        pi.reasoning = lines[i].strip()
                    else:
                        pi.reasoning = f"High revenue-per-hour ratio: ${pi.estimated_revenue:.0f} / {pi.estimated_hours:.1f}h"
            else:
                for pi in top3:
                    pi.reasoning = f"Score: {pi.final_score:.1f} (revenue/hour efficiency)"

        # Record this run in history
        run_record = {
            "ts": time.time(),
            "item_count": len(priority_items),
            "top_action": priority_items[0].action_type if priority_items else "none",
        }
        self._history.append(run_record)
        await self._save()

        return priority_items

    async def daily_priorities(self, available_hours: float = 8.0) -> list[PriorityItem]:
        """Pick items that fit within available_hours, sorted by final_score."""
        await self._load()

        # Use last prioritized items from history, or return empty list if no items
        # For daily priorities, we need items — use a default set if none available
        # This method returns items from the most recent prioritization that fit in hours
        if not self._history:
            return []

        # We don't store full items in history, so create a prioritized daily plan
        # based on available hours using common high-value actions
        default_items = [
            {
                "title": "Create content",
                "action_type": "content",
                "estimated_revenue": 500,
                "estimated_hours": 2.0,
                "urgency": 0.5,
                "deadline_hours": 24,
            },
            {
                "title": "Email campaign",
                "action_type": "email",
                "estimated_revenue": 300,
                "estimated_hours": 1.0,
                "urgency": 0.6,
                "deadline_hours": 8,
            },
            {
                "title": "Social media",
                "action_type": "ad",
                "estimated_revenue": 200,
                "estimated_hours": 1.5,
                "urgency": 0.3,
                "deadline_hours": 0,
            },
        ]

        all_items = await self.prioritize(default_items)

        selected: list[PriorityItem] = []
        hours_used = 0.0

        for item in all_items:
            if hours_used + item.estimated_hours <= available_hours:
                selected.append(item)
                hours_used += item.estimated_hours

        return selected

    async def emergency_reprioritize(
        self, trigger: str, current_queue: list[dict]
    ) -> list[PriorityItem]:
        """AI restructures queue for emergency situation."""
        await self._load()

        queue_summary = "\n".join(
            f"- {item.get('title', 'unknown')} ({item.get('action_type', 'unknown')})"
            for item in current_queue[:10]
        )

        ai = get_ai_client()
        resp = await ai.complete(
            system=(
                "You are a crisis prioritization expert. Given an emergency trigger, "
                "restructure the work queue to address the most urgent items first. "
                "Return a JSON array of action types in priority order: "
                '[{"action_type": str, "reason": str}]. Return only valid JSON.'
            ),
            user=f"Emergency trigger: {trigger}\n\nCurrent queue:\n{queue_summary}\n\nReprioritize.",
            model=AIModel.FAST,
            max_tokens=400,
        )

        # Apply AI-suggested ordering if valid
        reordered_items = list(current_queue)  # default: keep original

        if resp.success and resp.content:
            try:
                import json
                import re

                content = resp.content.strip()
                match = re.search(r"\[.*\]", content, re.DOTALL)
                if match:
                    ai_order = json.loads(match.group())
                    priority_map = {
                        item.get("action_type", ""): i for i, item in enumerate(ai_order)
                    }
                    reordered_items = sorted(
                        current_queue, key=lambda x: priority_map.get(x.get("action_type", ""), 999)
                    )
            except Exception:
                pass

        # Give all items max urgency for emergency
        emergency_items = [
            {**item, "urgency": 1.0, "deadline_hours": 4.0} for item in reordered_items
        ]

        result = await self.prioritize(emergency_items)

        # Add emergency reasoning to top item
        if result:
            result[0].reasoning = f"EMERGENCY: {trigger} — immediate action required"

        return result

    def prioritization_stats(self) -> dict:
        """Return stats about prioritization runs."""
        if not self._history:
            return {
                "total_prioritizations": 0,
                "avg_items_per_run": 0.0,
                "most_common_top_action": "none",
            }

        total = len(self._history)
        avg_items = sum(r.get("item_count", 0) for r in self._history) / total

        action_counts: dict[str, int] = {}
        for r in self._history:
            action = r.get("top_action", "none")
            action_counts[action] = action_counts.get(action, 0) + 1

        most_common = max(action_counts.items(), key=lambda x: x[1])[0] if action_counts else "none"

        return {
            "total_prioritizations": total,
            "avg_items_per_run": round(avg_items, 1),
            "most_common_top_action": most_common,
        }


# ── SINGLETON ─────────────────────────────────────────────
_instance: PriorityEngine | None = None


def get_priority_engine() -> PriorityEngine:
    global _instance
    if _instance is None:
        _instance = PriorityEngine()
    return _instance
