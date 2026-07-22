"""
missions.py — Async mission API (producer) + live-logs WebSocket.

POST /api/v1/missions      → validate + enqueue, respond 202 with a task id.
GET  /api/v1/missions/{id} → poll the mission state / result.
WS   /ws/logs/{id}         → stream the worker's Pub/Sub logs to the browser.

This is the scalable path: the web tier only validates + enqueues, and stateless
workers do the heavy lifting (see apps/core/scale/*). The legacy synchronous
/api/v1/chat remains for the interactive dashboard.
"""

from __future__ import annotations

import contextlib
import logging

from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from apps.core.scale import log_bus
from apps.core.scale.task_queue import get_queue
from apps.core.security.deps import rate_limit, require_user

logger = logging.getLogger("aria.missions")

router = APIRouter(tags=["missions"])


class MissionRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=8000)
    session_id: str = Field("default", max_length=128)
    provider: str = Field("default", max_length=32)


@router.post(
    "/api/v1/missions",
    status_code=202,
    dependencies=[Depends(rate_limit("missions", 60, 60))],
)
async def create_mission(req: MissionRequest, user: dict = Depends(require_user)):
    """Producer: validate + enqueue, return 202 Accepted immediately."""
    email = (user.get("email") or "").strip().lower()
    tid = await get_queue().enqueue(
        {"message": req.message, "session_id": req.session_id, "provider": req.provider},
        user_email=email,
    )
    return JSONResponse(
        status_code=202,
        content={
            "accepted": True,
            "task_id": tid,
            "status_url": f"/api/v1/missions/{tid}",
            "logs_ws": f"/ws/logs/{tid}",
        },
    )


@router.get("/api/v1/missions/{task_id}")
async def mission_status(task_id: str, user: dict = Depends(require_user)):
    status = await get_queue().get_status(task_id)
    if not status:
        return JSONResponse({"error": "not found"}, status_code=404)
    # Owners see any task; others only their own (BOLA guard).
    email = (user.get("email") or "").strip().lower()
    if status.get("user_email") and status["user_email"] != email:
        from apps.core.config import settings

        owner = (getattr(settings, "OWNER_EMAIL", "") or "").strip().lower()
        if email != owner:
            return JSONResponse({"error": "forbidden"}, status_code=403)
    return {
        "task_id": task_id,
        "state": status.get("state"),
        "result": status.get("result"),
        "error": status.get("error"),
    }


@router.websocket("/ws/logs/{task_id}")
async def logs_ws(websocket: WebSocket, task_id: str):
    """Stream a mission's live logs (from the worker's Pub/Sub channel)."""
    # Authenticate from the session cookie (same-origin WebSocket carries it).
    from apps.core import auth

    user = auth.verify_user(websocket.cookies.get(auth.USER_COOKIE))
    if not user or not user.get("email"):
        await websocket.close(code=4401)  # unauthenticated
        return

    # Same BOLA guard as GET /api/v1/missions/{id} — task_ids are unguessable
    # (secrets.token_urlsafe), but that's not authorization: this endpoint
    # exposes the same per-mission data and must enforce ownership the same
    # way, not rely solely on the id being hard to guess.
    email = (user.get("email") or "").strip().lower()
    status = await get_queue().get_status(task_id)
    if status and status.get("user_email") and status["user_email"] != email:
        from apps.core.config import settings

        owner = (getattr(settings, "OWNER_EMAIL", "") or "").strip().lower()
        if email != owner:
            await websocket.close(code=4403)  # forbidden
            return

    await websocket.accept()
    try:
        async for line in log_bus.subscribe(task_id):
            await websocket.send_text(line)
    except WebSocketDisconnect:
        pass
    except Exception as exc:  # noqa: BLE001
        logger.debug("[ws] logs stream ended: %s", exc)
        with_close = getattr(websocket, "close", None)
        if with_close:
            with contextlib.suppress(Exception):
                await websocket.close()
