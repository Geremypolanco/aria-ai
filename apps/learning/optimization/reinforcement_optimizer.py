"""
ReinforcementOptimizer — UCB1 bandit algorithm for adaptive growth action selection.

Treats each growth action type as an arm. Uses Upper Confidence Bound (UCB1)
to balance exploration (trying underused actions) vs exploitation (doubling
down on proven winners).
"""

from __future__ import annotations

import math
import random
import time
import uuid
from dataclasses import dataclass

from apps.core.memory.redis_client import get_cache

_KEY = "learning:reinforcement:v1"
_TTL = 86400 * 90

_DEFAULT_ACTIONS = [
    "create_content",
    "run_ad",
    "flash_sale",
    "email_campaign",
    "product_optimize",
    "quiz_launch",
    "bundle_create",
    "influencer",
]


@dataclass
class ActionArm:
    arm_id: str
    action_type: str
    total_pulls: int = 0
    total_reward: float = 0.0
    avg_reward: float = 0.0
    ucb_score: float = float("inf")
    last_pulled_ts: float = 0.0

    def update(self, reward: float) -> None:
        self.total_pulls += 1
        self.total_reward += reward
        self.avg_reward = self.total_reward / self.total_pulls
        self.last_pulled_ts = time.time()

    def to_dict(self) -> dict:
        return {
            "arm_id": self.arm_id,
            "action_type": self.action_type,
            "total_pulls": self.total_pulls,
            "total_reward": round(self.total_reward, 2),
            "avg_reward": round(self.avg_reward, 2),
            "ucb_score": round(self.ucb_score, 4) if self.ucb_score != float("inf") else "inf",
            "last_pulled_ts": self.last_pulled_ts,
        }


class ReinforcementOptimizer:
    def __init__(self) -> None:
        self._arms: dict[str, ActionArm] = {}
        self._history: list[dict] = []
        self._loaded = False
        for action in _DEFAULT_ACTIONS:
            self._arms[action] = ActionArm(
                arm_id=str(uuid.uuid4())[:8],
                action_type=action,
            )

    async def _load(self) -> None:
        if not self._loaded:
            try:
                cache = get_cache()
                data = await cache.get(_KEY)
                if isinstance(data, dict):
                    arms_data = data.get("arms", {})
                    for atype, adict in arms_data.items():
                        if atype in self._arms:
                            arm = self._arms[atype]
                            arm.total_pulls = adict.get("total_pulls", 0)
                            arm.total_reward = adict.get("total_reward", 0.0)
                            arm.avg_reward = adict.get("avg_reward", 0.0)
                    self._history = data.get("history", [])
            except Exception:
                pass
            self._loaded = True

    async def _save(self) -> None:
        try:
            cache = get_cache()
            payload = {
                "arms": {k: v.to_dict() for k, v in self._arms.items()},
                "history": self._history[-500:],
            }
            await cache.set(_KEY, payload, ttl_seconds=_TTL)
        except Exception:
            pass

    def _compute_ucb(self, arm: ActionArm, total_pulls: int) -> float:
        if arm.total_pulls == 0:
            return float("inf")
        if total_pulls == 0:
            return arm.avg_reward
        exploration = math.sqrt(2 * math.log(total_pulls) / arm.total_pulls)
        return arm.avg_reward + exploration

    def _update_ucb_scores(self) -> None:
        total = sum(a.total_pulls for a in self._arms.values())
        for arm in self._arms.values():
            arm.ucb_score = self._compute_ucb(arm, total)

    async def select_action(self) -> str:
        await self._load()
        self._update_ucb_scores()
        # Arms with inf UCB (never explored) come first
        unexplored = [a for a in self._arms.values() if a.total_pulls == 0]
        if unexplored:
            return unexplored[0].action_type
        best = max(self._arms.values(), key=lambda a: a.ucb_score)
        return best.action_type

    async def record_outcome(self, action_type: str, reward: float) -> ActionArm:
        await self._load()
        if action_type not in self._arms:
            self._arms[action_type] = ActionArm(
                arm_id=str(uuid.uuid4())[:8],
                action_type=action_type,
            )
        arm = self._arms[action_type]
        arm.update(reward)
        self._history.append(
            {
                "action_type": action_type,
                "reward": reward,
                "ts": time.time(),
            }
        )
        self._update_ucb_scores()
        await self._save()
        return arm

    async def batch_update(self, outcomes: list[dict]) -> None:
        await self._load()
        for o in outcomes:
            atype = o.get("action_type", "")
            reward = float(o.get("reward", 0.0))
            if atype:
                if atype not in self._arms:
                    self._arms[atype] = ActionArm(arm_id=str(uuid.uuid4())[:8], action_type=atype)
                self._arms[atype].update(reward)
                self._history.append({"action_type": atype, "reward": reward, "ts": time.time()})
        self._update_ucb_scores()
        await self._save()

    def arm_rankings(self) -> list[dict]:
        return sorted(
            [a.to_dict() for a in self._arms.values()],
            key=lambda x: x["avg_reward"],
            reverse=True,
        )

    async def explore_recommend(self, exploration_pct: float = 0.2) -> str:
        await self._load()
        if random.random() < exploration_pct:
            return random.choice(list(self._arms.keys()))
        self._update_ucb_scores()
        best = max(self._arms.values(), key=lambda a: a.avg_reward)
        return best.action_type

    def optimization_report(self) -> dict:
        rankings = self.arm_rankings()
        return {
            "total_pulls": sum(a.total_pulls for a in self._arms.values()),
            "total_reward": round(sum(a.total_reward for a in self._arms.values()), 2),
            "best_action": rankings[0]["action_type"] if rankings else None,
            "worst_action": rankings[-1]["action_type"] if rankings else None,
            "exploration_rate": 0.2,
            "arm_rankings": rankings[:5],
            "total_history": len(self._history),
        }


_instance: ReinforcementOptimizer | None = None


def get_reinforcement_optimizer() -> ReinforcementOptimizer:
    global _instance
    if _instance is None:
        _instance = ReinforcementOptimizer()
    return _instance
