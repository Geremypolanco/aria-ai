"""
hitl_queue.py — Human-in-the-loop escalation queue for guardrails Layer 2.

Before this module, evaluate_plan() blocking a plan (unsafe, or risk_score >=
the threshold) meant the action was declined outright and permanently — there
was no path back to a human decision, just a fixed apology to the user. This
gives the owner that path: a blocked plan is queued here instead of refused
outright, and the owner can approve it (it actually runs, for real, via the
same _execute_tool the planner would have used), deny it (stays blocked,
permanently, recorded), or approve it with modified arguments (e.g. a reduced
dollar amount) from the Mission Control admin panel.

Design notes, matching this codebase's existing conventions (see
ops/cost_ledger.py, KillSwitch):
- Process-local dict is the source of truth within one process — deterministic,
  unit-testable without Redis. Redis (get_cache()) persistence is best-effort
  on top, so a request survives a restart or a request landing on a different
  Fly instance than the one that enqueued it. If Redis is unavailable, the
  queue still works correctly for the lifetime of this process.
- resolve() is race-safe across processes via acquire_lock() (Redis SET NX) —
  two admins (or a double-click) resolving the same request only lets the
  first one through; the second gets None back, not a double execution.
- NOTHING here fabricates an outcome: result_text is only ever set to what the
  real tool call actually returned.
"""

from __future__ import annotations

import logging
import time
import uuid
from contextlib import suppress
from dataclasses import asdict, dataclass, field

logger = logging.getLogger("aria.safety.hitl")

_REQUEST_KEY = "aria:hitl:request:{rid}"
_ALL_IDS_KEY = "aria:hitl:all_ids"
_REQUEST_TTL = 86400 * 14  # 2 weeks — long enough for an owner who checks in occasionally
_MAX_TRACKED_IDS = (
    500  # bounds the all_ids list; oldest ids fall off, matching _REQUEST_TTL's spirit
)

VALID_DECISIONS = ("approve", "deny", "modify")


@dataclass
class HitlRequest:
    request_id: str
    chat_id: str
    email: str
    user_text: str
    tool: str
    tool_args: dict
    risk_score: float
    risk_reason: str
    created_at: float = field(default_factory=time.time)
    status: str = "pending"  # pending | approved | denied | modified
    resolved_at: float | None = None
    resolved_by: str | None = None
    result_text: str | None = None
    note: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)

    @staticmethod
    def from_dict(data: dict) -> HitlRequest:
        return HitlRequest(**data)


class HitlQueueStore:
    """Owner-facing queue of guardrail-blocked actions awaiting a decision."""

    def __init__(self) -> None:
        self._local: dict[str, HitlRequest] = {}

    async def _cache(self):
        try:
            from apps.core.memory.redis_client import get_cache

            return get_cache()
        except Exception:  # noqa: BLE001
            return None

    async def enqueue(
        self,
        *,
        chat_id: str,
        email: str,
        user_text: str,
        tool: str,
        tool_args: dict,
        risk_score: float,
        risk_reason: str,
    ) -> HitlRequest:
        req = HitlRequest(
            request_id="req_" + uuid.uuid4().hex[:10],
            chat_id=chat_id,
            email=(email or "").strip().lower(),
            user_text=user_text[:2000],
            tool=tool,
            tool_args=tool_args,
            risk_score=risk_score,
            risk_reason=risk_reason,
        )
        self._local[req.request_id] = req
        cache = await self._cache()
        if cache:
            try:
                await cache.set(
                    _REQUEST_KEY.format(rid=req.request_id), req.to_dict(), ttl_seconds=_REQUEST_TTL
                )
                await cache.rpush(_ALL_IDS_KEY, req.request_id)
                await cache.ltrim(_ALL_IDS_KEY, -_MAX_TRACKED_IDS, -1)
            except Exception as exc:  # noqa: BLE001 — queue still works process-local
                logger.warning("[hitl] failed to persist request %s: %s", req.request_id, exc)
        logger.info(
            "[hitl] queued %s for %s (risk=%.2f): %s", req.request_id, req.email, risk_score, tool
        )
        return req

    async def get(self, request_id: str) -> HitlRequest | None:
        if request_id in self._local:
            return self._local[request_id]
        cache = await self._cache()
        if not cache:
            return None
        try:
            data = await cache.get(_REQUEST_KEY.format(rid=request_id))
        except Exception:  # noqa: BLE001
            return None
        if not data:
            return None
        req = HitlRequest.from_dict(data)
        self._local[request_id] = req  # warm the local cache
        return req

    async def list_all(self) -> list[HitlRequest]:
        """Every request this process knows about, merged with whatever Redis
        has that this process hasn't seen yet (e.g. queued by another
        instance). Best-effort — a request only Redis knows about and that
        this process has never touched is still found via _ALL_IDS_KEY."""
        cache = await self._cache()
        ids = set(self._local.keys())
        if cache:
            try:
                remote_ids = await cache.lrange(_ALL_IDS_KEY, 0, -1)
                ids.update(remote_ids or [])
            except Exception:  # noqa: BLE001
                pass
        requests = []
        for rid in ids:
            req = await self.get(rid)
            if req:
                requests.append(req)
        return requests

    async def list_pending(self) -> list[HitlRequest]:
        pending = [r for r in await self.list_all() if r.status == "pending"]
        # Highest risk first — that's what needs the owner's attention soonest.
        pending.sort(key=lambda r: r.risk_score, reverse=True)
        return pending

    async def resolve(
        self,
        request_id: str,
        *,
        decision: str,
        resolved_by: str,
        modified_args: dict | None = None,
        note: str = "",
    ) -> HitlRequest | None:
        """Claims and resolves a pending request. Returns None if the request
        doesn't exist or isn't pending anymore (already resolved — by this
        admin's own earlier click, another admin, or a retried network
        request).

        The Redis lock below is a best-effort cross-process guard, not the
        authoritative one: AriaCache._cmd() swallows every failure and
        returns None either way, so a genuine lock-held-elsewhere and a
        simple "Redis is unreachable right now" are indistinguishable here.
        Treating a failed acquire as "denied" would fail the entire HITL
        approval flow closed on any Upstash blip — worse than the rare
        true double-resolve race it would prevent. The req.status ==
        "pending" check just below is what's authoritative for the common
        single-process case, matching this codebase's established
        fail-open-on-cache-errors convention (see CostLedger.is_frozen)."""
        if decision not in VALID_DECISIONS:
            raise ValueError(f"invalid decision: {decision}")

        cache = await self._cache()
        lock_acquired = False
        if cache:
            with suppress(Exception):
                lock_acquired = await cache.acquire_lock(
                    f"hitl_resolve:{request_id}", ttl_seconds=15
                )
        try:
            req = await self.get(request_id)
            if not req or req.status != "pending":
                return None

            req.status = (
                "approved"
                if decision == "approve"
                else "denied" if decision == "deny" else "modified"
            )
            req.resolved_at = time.time()
            req.resolved_by = resolved_by
            req.note = note
            if decision == "modify" and modified_args is not None:
                req.tool_args = modified_args

            self._local[request_id] = req
            if cache:
                try:
                    await cache.set(
                        _REQUEST_KEY.format(rid=request_id), req.to_dict(), ttl_seconds=_REQUEST_TTL
                    )
                except Exception as exc:  # noqa: BLE001
                    logger.warning(
                        "[hitl] failed to persist resolution for %s: %s", request_id, exc
                    )
            return req
        finally:
            if cache and lock_acquired:
                with suppress(Exception):
                    await cache.release_lock(f"hitl_resolve:{request_id}")

    async def record_result(self, request_id: str, result_text: str) -> None:
        """Called after the approved/modified tool call actually runs, so the
        queue reflects what really happened — never set except from a real
        execution outcome."""
        req = await self.get(request_id)
        if not req:
            return
        req.result_text = result_text[:2000]
        self._local[request_id] = req
        cache = await self._cache()
        if cache:
            try:
                await cache.set(
                    _REQUEST_KEY.format(rid=request_id), req.to_dict(), ttl_seconds=_REQUEST_TTL
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning("[hitl] failed to persist result for %s: %s", request_id, exc)


_store: HitlQueueStore | None = None


def get_hitl_queue() -> HitlQueueStore:
    global _store
    if _store is None:
        _store = HitlQueueStore()
    return _store
