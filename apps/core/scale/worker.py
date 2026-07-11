"""
worker.py — Stateless background mission worker.

Runs isolated from the web server. Drains the mission queue one task at a time,
tracks state transitions (queued → processing → completed | failed) in the
cache, paces outbound LLM calls through the rate-limiter, streams live logs over
Pub/Sub, and auto-retries transient failures (self-healing).

Run it as its own Fly process:  python -m apps.core.scale.worker
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from apps.core.ops.self_healing import RetryOutcome, run_with_self_healing
from apps.core.scale import log_bus
from apps.core.scale.rate_limiter import RateLimitDispatcher, get_dispatcher
from apps.core.scale.task_queue import MissionQueue, get_queue

logger = logging.getLogger("aria.worker")

# Short, responsive retry schedule for a mission (seconds): transient LLM/network
# hiccups recover fast; permanent errors don't retry (see self_healing).
WORKER_RETRY_DELAYS = (5, 15, 30)


async def _default_agent_run(payload: dict) -> dict:
    """Execute a mission through ARIA's cognitive brain."""
    from apps.core.cognition.aria_mind import get_aria_mind

    message = payload.get("message", "")
    session_id = payload.get("session_id") or "worker"
    resp = await get_aria_mind().handle(message, session_id)
    media_b64 = None
    if getattr(resp, "image_bytes", None):
        import base64

        media_b64 = base64.b64encode(resp.image_bytes).decode()
    return {"reply": resp.text or resp.caption or "", "media_base64": media_b64}


async def handle_task(
    task: dict,
    *,
    queue: MissionQueue,
    agent_run: Any = None,
    dispatcher: RateLimitDispatcher | None = None,
    delays: tuple[int, ...] = WORKER_RETRY_DELAYS,
    sleep: Any = asyncio.sleep,
) -> RetryOutcome:
    """Process a single mission end-to-end with state + logs + self-healing."""
    tid = task["id"]
    payload = task.get("payload", {}) or {}
    disp = dispatcher or get_dispatcher()
    run = agent_run or _default_agent_run

    await queue.set_status(tid, "processing")
    await log_bus.publish(tid, "▶ mission picked up by worker")

    async def _attempt() -> dict:
        provider = payload.get("provider", "default")
        waited = await disp.acquire(provider)  # pace to provider quota
        if waited > 0.05:
            await log_bus.publish(
                tid, f"· paced {waited:.1f}s to respect {provider} quota", level="dim"
            )
        await log_bus.publish(tid, "· calling model", level="dim")
        result = await run(payload)
        await log_bus.publish(tid, "· model responded", level="dim")
        return result

    async def _alert(outcome: RetryOutcome) -> None:
        await log_bus.publish(tid, f"✕ mission failed: {outcome.error}", level="error")

    outcome = await run_with_self_healing(
        _attempt, name=tid, on_alert=_alert, delays=delays, sleep=sleep
    )
    if outcome.ok:
        await queue.set_status(tid, "completed", result=outcome.result)
        await log_bus.publish(tid, "✓ mission complete", level="ok")
    else:
        await queue.set_status(tid, "failed", error=outcome.error)
    return outcome


async def run_forever(
    queue: MissionQueue | None = None, *, stop: asyncio.Event | None = None
) -> None:
    """Main worker loop — blocks on the queue and processes tasks one by one."""
    q = queue or get_queue()
    logger.info("[worker] started; draining mission queue")
    while stop is None or not stop.is_set():
        task = await q.dequeue(timeout=5.0)
        if not task:
            continue
        try:
            await handle_task(task, queue=q)
        except Exception as exc:  # noqa: BLE001 — one bad task must not kill the worker
            logger.error("[worker] task crashed: %s", exc)


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    asyncio.run(run_forever())


if __name__ == "__main__":
    main()
