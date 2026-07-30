"""Live conversation practice — the "video call" style speaking mode.

A WebSocket carries either recorded audio (base64) or typed text from the
learner; the server transcribes (if audio), generates a level-appropriate
tutor reply via the HF chat model, synthesizes speech for it, and streams
both the text and audio back so the frontend can play it while animating a
talking avatar — the practical, buildable version of "talk normally like in
a video call" without needing full video synthesis.
"""

from __future__ import annotations

import base64
import json
import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from .. import auth, db
from ..curriculum import build_conversation_system_prompt
from ..hf_client import hf_client
from .users import get_user_by_id_or_404

logger = logging.getLogger("lingua.conversation")

router = APIRouter(tags=["conversation"])

_MAX_HISTORY_TURNS = 12


def _log_turn(user_id: str, role: str, content: str) -> None:
    with db.cursor() as cur:
        cur.execute(
            "INSERT INTO conversation_log (user_id, role, content, created_at) VALUES (?,?,?,?)",
            (user_id, role, content, db.now_iso()),
        )


def _recent_history(user_id: str) -> list[dict[str, str]]:
    with db.cursor() as cur:
        cur.execute(
            "SELECT role, content FROM conversation_log WHERE user_id=? "
            "ORDER BY id DESC LIMIT ?",
            (user_id, _MAX_HISTORY_TURNS),
        )
        rows = cur.fetchall()
    return [{"role": r["role"], "content": r["content"]} for r in reversed(rows)]


@router.websocket("/ws/conversation/{user_id}")
async def conversation_socket(websocket: WebSocket, user_id: str) -> None:
    await websocket.accept()

    session = auth.verify_session(websocket.cookies.get(auth.SESSION_COOKIE))
    if not session or session["user_id"] != user_id:
        await websocket.send_json({"type": "error", "message": "Sign in with Google first"})
        await websocket.close(code=4401)
        return

    try:
        user = get_user_by_id_or_404(user_id)
    except Exception:
        await websocket.send_json({"type": "error", "message": "Unknown user"})
        await websocket.close()
        return

    system_prompt = build_conversation_system_prompt(user.target_lang, user.native_lang, user.level, user.interests)
    history = _recent_history(user_id)

    await websocket.send_json(
        {
            "type": "ready",
            "message": f"Conversation ready — practicing {user.target_lang} at level {user.level.value}.",
        }
    )

    try:
        while True:
            raw = await websocket.receive_text()
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                await websocket.send_json({"type": "error", "message": "Invalid message"})
                continue

            msg_type = msg.get("type")
            if msg_type == "audio":
                audio_bytes = base64.b64decode(msg.get("data", ""))
                content_type = msg.get("content_type", "audio/webm")
                transcript = await hf_client.speech_to_text(audio_bytes, content_type)
                if not transcript:
                    await websocket.send_json(
                        {"type": "error", "message": "Could not transcribe audio — try again or type instead."}
                    )
                    continue
            elif msg_type == "text":
                transcript = str(msg.get("data", "")).strip()
                if not transcript:
                    continue
            else:
                await websocket.send_json({"type": "error", "message": f"Unknown message type: {msg_type}"})
                continue

            await websocket.send_json({"type": "transcript", "text": transcript})
            _log_turn(user_id, "user", transcript)
            history.append({"role": "user", "content": transcript})
            history = history[-_MAX_HISTORY_TURNS:]

            reply_text = await hf_client.conversation_reply(system_prompt, history)
            _log_turn(user_id, "assistant", reply_text)
            history.append({"role": "assistant", "content": reply_text})
            history = history[-_MAX_HISTORY_TURNS:]

            audio = await hf_client.text_to_speech(reply_text, user.target_lang)
            audio_b64 = base64.b64encode(audio).decode() if audio else None

            await websocket.send_json(
                {
                    "type": "reply",
                    "text": reply_text,
                    "audio_base64": audio_b64,
                }
            )
    except WebSocketDisconnect:
        logger.info("Conversation socket closed for user %s", user_id)
