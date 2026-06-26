from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from enum import StrEnum

from apps.core.memory.redis_client import get_cache

_CACHE_KEY = "psychology:behavior:v1"
_CACHE_TTL = 86400 * 90  # 90 days


class BehaviorSignal(StrEnum):
    HIGH_INTENT = "high_intent"
    BROWSING = "browsing"
    COMPARISON_SHOPPING = "comparison_shopping"
    PRICE_SENSITIVE = "price_sensitive"
    LOYALTY_RISK = "loyalty_risk"
    READY_TO_BUY = "ready_to_buy"
    CHURNING = "churning"
    ADVOCATE = "advocate"


# Map action types to signals
_ACTION_SIGNAL_MAP: dict[str, BehaviorSignal] = {
    "view": BehaviorSignal.BROWSING,
    "add_to_cart": BehaviorSignal.HIGH_INTENT,
    "purchase": BehaviorSignal.READY_TO_BUY,
    "refund": BehaviorSignal.LOYALTY_RISK,
    "compare": BehaviorSignal.COMPARISON_SHOPPING,
    "price_check": BehaviorSignal.PRICE_SENSITIVE,
    "coupon": BehaviorSignal.PRICE_SENSITIVE,
    "share": BehaviorSignal.ADVOCATE,
    "review": BehaviorSignal.ADVOCATE,
    "unsubscribe": BehaviorSignal.CHURNING,
    "cancel": BehaviorSignal.CHURNING,
    "inactivity": BehaviorSignal.CHURNING,
    "wishlist": BehaviorSignal.HIGH_INTENT,
    "checkout": BehaviorSignal.READY_TO_BUY,
}

# Intent score weights per signal
_SIGNAL_INTENT_WEIGHT: dict[BehaviorSignal, float] = {
    BehaviorSignal.READY_TO_BUY: 1.0,
    BehaviorSignal.HIGH_INTENT: 0.8,
    BehaviorSignal.COMPARISON_SHOPPING: 0.5,
    BehaviorSignal.BROWSING: 0.2,
    BehaviorSignal.PRICE_SENSITIVE: 0.4,
    BehaviorSignal.ADVOCATE: 0.7,
    BehaviorSignal.LOYALTY_RISK: -0.3,
    BehaviorSignal.CHURNING: -0.5,
}


@dataclass
class BehaviorProfile:
    profile_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    user_id: str = ""
    signals: list[BehaviorSignal] = field(default_factory=list)
    intent_score: float = 0.0
    predicted_ltv_usd: float = 0.0
    churn_probability: float = 0.0
    next_best_action: str = ""
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            "profile_id": self.profile_id,
            "user_id": self.user_id,
            "signals": [s.value for s in self.signals],
            "intent_score": self.intent_score,
            "predicted_ltv_usd": self.predicted_ltv_usd,
            "churn_probability": self.churn_probability,
            "next_best_action": self.next_best_action,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, d: dict) -> BehaviorProfile:
        return cls(
            profile_id=d.get("profile_id", str(uuid.uuid4())),
            user_id=d.get("user_id", ""),
            signals=[BehaviorSignal(s) for s in d.get("signals", [])],
            intent_score=d.get("intent_score", 0.0),
            predicted_ltv_usd=d.get("predicted_ltv_usd", 0.0),
            churn_probability=d.get("churn_probability", 0.0),
            next_best_action=d.get("next_best_action", ""),
            created_at=d.get("created_at", time.time()),
        )


def _infer_signals(actions: list[dict]) -> list[BehaviorSignal]:
    signals: list[BehaviorSignal] = []
    seen: set[BehaviorSignal] = set()
    for action in actions:
        action_type = action.get("type", "").lower()
        signal = _ACTION_SIGNAL_MAP.get(action_type)
        if signal and signal not in seen:
            signals.append(signal)
            seen.add(signal)
    return signals


def _compute_intent_score(signals: list[BehaviorSignal]) -> float:
    if not signals:
        return 0.0
    raw = sum(_SIGNAL_INTENT_WEIGHT.get(s, 0.0) for s in signals)
    # Normalize to 0-1
    max_possible = sum(w for w in _SIGNAL_INTENT_WEIGHT.values() if w > 0)
    normalized = raw / max_possible if max_possible > 0 else 0.0
    return max(0.0, min(1.0, normalized))


def _compute_churn_probability(signals: list[BehaviorSignal]) -> float:
    churn_signals = {BehaviorSignal.CHURNING, BehaviorSignal.LOYALTY_RISK}
    churn_count = sum(1 for s in signals if s in churn_signals)
    positive_signals = {
        BehaviorSignal.READY_TO_BUY,
        BehaviorSignal.ADVOCATE,
        BehaviorSignal.HIGH_INTENT,
    }
    positive_count = sum(1 for s in signals if s in positive_signals)
    base = 0.1 + (churn_count * 0.3) - (positive_count * 0.1)
    return max(0.0, min(1.0, base))


def _next_best_action(signals: list[BehaviorSignal], intent_score: float, churn_prob: float) -> str:
    if BehaviorSignal.READY_TO_BUY in signals:
        return "Send personalized checkout reminder with limited-time incentive"
    if BehaviorSignal.HIGH_INTENT in signals:
        return "Trigger retargeting ad with social proof and urgency messaging"
    if BehaviorSignal.CHURNING in signals or churn_prob > 0.6:
        return "Send win-back email with exclusive discount and personal outreach"
    if BehaviorSignal.LOYALTY_RISK in signals:
        return "Proactive customer success check-in — ask about their experience"
    if BehaviorSignal.PRICE_SENSITIVE in signals:
        return "Offer payment plan or entry-level product tier"
    if BehaviorSignal.COMPARISON_SHOPPING in signals:
        return "Send comparison guide highlighting unique advantages over competitors"
    if BehaviorSignal.ADVOCATE in signals:
        return "Invite to referral program and offer exclusive advocate perks"
    if intent_score < 0.2:
        return "Nurture with educational content — build awareness and trust"
    return "Continue engaging with value-driven content in preferred channels"


class BehaviorAnalyzer:
    def __init__(self) -> None:
        self._profiles: dict[str, dict] = {}
        self._loaded = False

    async def _load(self) -> None:
        if self._loaded:
            return
        try:
            cache = get_cache()
            data = await cache.get(_CACHE_KEY)
            if data and isinstance(data, dict):
                self._profiles = data
        except Exception:
            pass
        self._loaded = True

    async def _save(self) -> None:
        try:
            cache = get_cache()
            await cache.set(_CACHE_KEY, self._profiles, ttl_seconds=_CACHE_TTL)
        except Exception:
            pass

    async def analyze_user(self, user_id: str, actions: list[dict]) -> BehaviorProfile:
        await self._load()

        signals = _infer_signals(actions)
        intent_score = _compute_intent_score(signals)
        churn_prob = _compute_churn_probability(signals)

        # Predict LTV: rough heuristic based on intent
        predicted_ltv = intent_score * 500.0  # up to $500 baseline

        nba = _next_best_action(signals, intent_score, churn_prob)

        profile = BehaviorProfile(
            user_id=user_id,
            signals=signals,
            intent_score=round(intent_score, 4),
            predicted_ltv_usd=round(predicted_ltv, 2),
            churn_probability=round(churn_prob, 4),
            next_best_action=nba,
        )

        self._profiles[user_id] = profile.to_dict()
        await self._save()
        return profile

    async def segment_users(self, user_ids: list[str]) -> dict[str, list[str]]:
        await self._load()

        segments: dict[str, list[str]] = {
            "high_intent": [],
            "at_risk": [],
            "loyal": [],
            "new": [],
        }

        for uid in user_ids:
            if uid not in self._profiles:
                segments["new"].append(uid)
                continue
            profile = BehaviorProfile.from_dict(self._profiles[uid])
            if profile.intent_score >= 0.7:
                segments["high_intent"].append(uid)
            elif profile.churn_probability >= 0.5:
                segments["at_risk"].append(uid)
            elif BehaviorSignal.ADVOCATE in profile.signals:
                segments["loyal"].append(uid)
            else:
                segments["new"].append(uid)

        return segments

    async def predict_churn(self, user_id: str) -> dict:
        await self._load()

        if user_id not in self._profiles:
            return {
                "user_id": user_id,
                "churn_probability": 0.5,
                "reasons": ["No behavioral data available"],
                "prevention_actions": [
                    "Start tracking user interactions",
                    "Send onboarding sequence",
                ],
            }

        profile = BehaviorProfile.from_dict(self._profiles[user_id])

        reasons: list[str] = []
        prevention: list[str] = []

        if BehaviorSignal.CHURNING in profile.signals:
            reasons.append("User showed active churn signals (unsubscribe, cancel, inactivity)")
            prevention.append("Send win-back campaign with personalized offer within 24 hours")
        if BehaviorSignal.LOYALTY_RISK in profile.signals:
            reasons.append("Recent refund or complaint detected")
            prevention.append("Personal outreach from customer success team")
        if profile.intent_score < 0.2:
            reasons.append("Low engagement — user not finding value")
            prevention.append("Send re-engagement sequence with best use cases and quick wins")
        if not reasons:
            reasons.append("Low churn risk based on current signals")
            prevention.append("Continue current engagement strategy")

        return {
            "user_id": user_id,
            "churn_probability": profile.churn_probability,
            "reasons": reasons,
            "prevention_actions": prevention,
        }

    async def buying_intent_score(self, user_id: str) -> float:
        await self._load()
        if user_id not in self._profiles:
            return 0.0
        profile = BehaviorProfile.from_dict(self._profiles[user_id])
        return profile.intent_score

    def summary(self) -> dict:
        if not self._profiles:
            return {"total_profiles": 0, "avg_intent_score": 0.0, "high_intent_count": 0}

        profiles = [BehaviorProfile.from_dict(d) for d in self._profiles.values()]
        avg_intent = sum(p.intent_score for p in profiles) / len(profiles)
        high_intent = sum(1 for p in profiles if p.intent_score >= 0.7)

        return {
            "total_profiles": len(profiles),
            "avg_intent_score": round(avg_intent, 4),
            "high_intent_count": high_intent,
        }


_analyzer_instance: BehaviorAnalyzer | None = None


def get_behavior_analyzer() -> BehaviorAnalyzer:
    global _analyzer_instance
    if _analyzer_instance is None:
        _analyzer_instance = BehaviorAnalyzer()
    return _analyzer_instance
