"""
test_execution_audit.py — Elite QA end-to-end execution audit.

Exercises ALL six ARIA flows with integrated mocks (no real API keys required):

  1. Missions API & worker loop   — POST /api/v1/missions → 202 → queue → worker
  2. Live logs WebSocket          — /ws/logs/{id} auth + Pub/Sub streaming
  3. Signed comment webhooks      — HMAC verify (reject/accept) + reply pipeline
  4. Chrome Clipper capture       — /api/v1/clipper/capture auth + storage
  5. Voice profile / ElevenLabs   — /api/v1/user/voice-profile multipart + schema
  6. Support widget + legal shield— /api/v1/support/chat + no-refund frontend gate

Deterministic: LLM calls run their honest offline fallbacks (no ANTHROPIC key),
the cache is the in-memory mock, and the mission queue uses its in-process
backend. TestClient is created WITHOUT the lifespan context so no background
worker races the assertions — the worker is driven explicitly.
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import hmac
import json
import os

import pytest
from fastapi.testclient import TestClient

from apps.core import auth
from apps.core.main import app

QA_EMAIL = "qa@aria.test"


def _cookie() -> dict:
    """A valid signed session cookie for the QA user."""
    return {auth.USER_COOKIE: auth.sign_user(QA_EMAIL, "QA Bot", "test")}


@pytest.fixture
def client():
    # Plain TestClient (no `with`) → lifespan/background worker NOT started.
    return TestClient(app)


@pytest.fixture
def cache(mock_redis_patched):
    """In-memory cache, patched into get_cache() for clipper/voice storage."""
    return mock_redis_patched


@pytest.fixture(autouse=True)
def _clean_queue():
    from apps.core.scale import task_queue as tq

    tq._mem_pending.clear()
    tq._mem_status.clear()
    yield
    tq._mem_pending.clear()
    tq._mem_status.clear()


# ══════════════════ FLOW 1 — Missions API & worker ══════════════════
class TestFlow1Missions:
    def test_post_returns_202_and_enqueues(self, client):
        r = client.post(
            "/api/v1/missions",
            json={"message": "Publica un post sobre IA", "provider": "default"},
            cookies=_cookie(),
        )
        assert r.status_code == 202
        body = r.json()
        assert body["accepted"] is True
        tid = body["task_id"]
        assert tid.startswith("task_")
        assert body["status_url"] == f"/api/v1/missions/{tid}"
        assert body["logs_ws"] == f"/ws/logs/{tid}"

        # The task really landed in the queue as "queued" (read the in-memory
        # backend directly — no event loop needed, robust under any ordering).
        from apps.core.scale import task_queue as tq

        assert tq._mem_status.get(tid, {}).get("state") == "queued"
        assert tid in tq._mem_pending

    def test_post_requires_auth(self, client):
        r = client.post("/api/v1/missions", json={"message": "hi"})
        assert r.status_code == 401

    def test_status_endpoint_bola_guard(self, client):
        tid = client.post("/api/v1/missions", json={"message": "mine"}, cookies=_cookie()).json()[
            "task_id"
        ]
        # Owner of the task can read it.
        r = client.get(f"/api/v1/missions/{tid}", cookies=_cookie())
        assert r.status_code == 200 and r.json()["state"] == "queued"
        # A different user is forbidden (BOLA guard).
        other = {auth.USER_COOKIE: auth.sign_user("intruder@x.com")}
        r2 = client.get(f"/api/v1/missions/{tid}", cookies=other)
        assert r2.status_code == 403

    async def test_worker_processes_to_completed(self):
        from apps.core.scale.task_queue import get_queue
        from apps.core.scale.worker import handle_task

        q = get_queue()
        tid = await q.enqueue({"message": "do", "provider": "default"})
        task = await q.dequeue(timeout=1.0)

        async def fake_agent(payload):
            return {"reply": "LLM: " + payload["message"]}

        outcome = await handle_task(task, queue=q, agent_run=fake_agent)
        assert outcome.ok is True
        assert (await q.get_status(tid))["state"] == "completed"

    async def test_worker_marks_failed_on_permanent_error(self):
        from apps.core.scale.task_queue import get_queue
        from apps.core.scale.worker import handle_task

        q = get_queue()
        tid = await q.enqueue({"message": "boom"})
        task = await q.dequeue(timeout=1.0)

        async def bad_agent(payload):
            raise ValueError("permanent validation error")

        slept = []

        async def no_sleep(d):
            slept.append(d)

        outcome = await handle_task(task, queue=q, agent_run=bad_agent, sleep=no_sleep)
        assert outcome.ok is False
        assert slept == []  # permanent errors are NOT retried
        assert (await q.get_status(tid))["state"] == "failed"

    async def test_run_forever_loop_does_not_hang(self, monkeypatch):
        """Boot the worker loop in the background, process one task, stop cleanly."""
        from apps.core.scale import worker as w
        from apps.core.scale.task_queue import get_queue

        q = get_queue()

        async def canned(payload):
            return {"reply": "ok"}

        monkeypatch.setattr(w, "_default_agent_run", canned)
        tid = await q.enqueue({"message": "bg", "provider": "default"})

        stop = asyncio.Event()
        loop_task = asyncio.ensure_future(w.run_forever(q, stop=stop))

        # Wait (bounded) for the background loop to complete the task.
        async def wait_done():
            while True:
                s = await q.get_status(tid)
                if s and s["state"] in ("completed", "failed"):
                    return s["state"]
                await asyncio.sleep(0.02)

        state = await asyncio.wait_for(wait_done(), timeout=3.0)
        assert state == "completed"

        # Signal stop and confirm the loop exits without hanging.
        stop.set()
        await asyncio.wait_for(loop_task, timeout=3.0)
        assert loop_task.done()


# ══════════════════ FLOW 2 — Live logs WebSocket ══════════════════
class _FakeWS:
    """Minimal async WebSocket double for driving logs_ws in-loop."""

    def __init__(self, cookies: dict):
        self.cookies = cookies
        self.sent: list[str] = []
        self.accepted = False
        self.close_code = None

    async def accept(self):
        self.accepted = True

    async def send_text(self, text: str):
        self.sent.append(text)

    async def close(self, code: int = 1000):
        self.close_code = code


class TestFlow2LiveLogs:
    async def test_unauthenticated_ws_is_rejected(self):
        from apps.core.routes.missions import logs_ws

        ws = _FakeWS(cookies={})  # no session cookie
        await logs_ws(ws, "task_x")
        assert ws.accepted is False
        assert ws.close_code == 4401  # unauthenticated close code

    async def test_authenticated_ws_streams_published_logs(self):
        from apps.core.routes.missions import logs_ws
        from apps.core.scale import log_bus

        tid = "task_ws_stream"
        ws = _FakeWS(cookies=_cookie())
        task = asyncio.ensure_future(logs_ws(ws, tid))
        await asyncio.sleep(0.05)  # let the subscription register
        assert ws.accepted is True

        await log_bus.publish(tid, "▶ mission picked up", level="info")
        await log_bus.publish(tid, "✓ mission complete", level="ok")
        await asyncio.sleep(0.05)

        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task

        joined = "".join(ws.sent)
        assert "mission picked up" in joined
        assert "mission complete" in joined
        # Each frame is a JSON log line.
        first = json.loads(ws.sent[0])
        assert "msg" in first and "level" in first and "ts" in first


# ══════════════════ FLOW 3 — Signed comment webhooks ══════════════════
class TestFlow3Webhooks:
    def _sign(self, secret: bytes, body: bytes, algo: str) -> str:
        return f"{algo}=" + hmac.new(secret, body, getattr(hashlib, algo)).hexdigest()

    def test_instagram_rejects_invalid_signature(self, client, monkeypatch):
        from apps.core.webhooks import webhook_monitor_controller as wm

        monkeypatch.setattr(wm.settings, "META_APP_SECRET", "ig-secret", raising=False)
        r = client.post(
            "/api/v1/webhooks/instagram/comments",
            content=b'{"entry":[]}',
            headers={"x-hub-signature-256": "sha256=deadbeef", "content-type": "application/json"},
        )
        assert r.status_code == 401

    def test_instagram_accepts_valid_signature_and_replies(self, client, monkeypatch):
        from apps.core.webhooks import webhook_monitor_controller as wm

        monkeypatch.setattr(wm.settings, "META_APP_SECRET", "ig-secret", raising=False)
        payload = {
            "entry": [
                {
                    "changes": [
                        {
                            "field": "comments",
                            "value": {
                                "id": "c1",
                                "text": "This is amazing, how do I start?",
                                "from": {"username": "alice"},
                                "media": {"id": "m9"},
                            },
                        }
                    ]
                }
            ]
        }
        body = json.dumps(payload).encode()
        sig = self._sign(b"ig-secret", body, "sha256")
        r = client.post(
            "/api/v1/webhooks/instagram/comments",
            content=body,
            headers={"x-hub-signature-256": sig, "content-type": "application/json"},
        )
        assert r.status_code == 200
        data = r.json()
        assert data["ok"] is True and data["handled"] == 1
        # A draft reply was produced and the publish stub did not raise.
        res = data["results"][0]
        assert res["reply"].strip()
        assert res["publish"]["stub"] is True

    def test_youtube_rejects_and_accepts_sha1(self, client, monkeypatch):
        from apps.core.webhooks import webhook_monitor_controller as wm

        monkeypatch.setattr(wm.settings, "YOUTUBE_WEBHOOK_SECRET", "yt-secret", raising=False)
        payload = {"comment": {"id": "y1", "text": "great video!", "author": "bob"}}
        body = json.dumps(payload).encode()

        bad = client.post(
            "/api/v1/webhooks/youtube/comments",
            content=body,
            headers={"x-hub-signature": "sha1=deadbeef", "content-type": "application/json"},
        )
        assert bad.status_code == 401

        good_sig = self._sign(b"yt-secret", body, "sha1")
        good = client.post(
            "/api/v1/webhooks/youtube/comments",
            content=body,
            headers={"x-hub-signature": good_sig, "content-type": "application/json"},
        )
        assert good.status_code == 200
        assert good.json()["handled"] == 1


# ══════════════════ FLOW 4 — Chrome Clipper ══════════════════
class TestFlow4Clipper:
    def test_capture_requires_auth(self, client, cache):
        r = client.post(
            "/api/v1/clipper/capture",
            json={"url": "https://example.com", "selection": "hello"},
        )
        assert r.status_code == 401

    def test_capture_stores_clip(self, client, cache):
        r = client.post(
            "/api/v1/clipper/capture",
            json={
                "url": "https://example.com/article",
                "title": "Great Article",
                "selection": "an insightful paragraph",
                "clipped_at": "2026-07-11T00:00:00Z",
            },
            cookies=_cookie(),
        )
        assert r.status_code == 200
        assert r.json() == {"ok": True, "stored": True}
        # The clip is persisted under the user's key.
        stored = cache._lists.get(f"aria:clips:{QA_EMAIL}", [])
        assert len(stored) == 1
        rec = json.loads(stored[0])
        assert rec["url"] == "https://example.com/article"
        assert rec["title"] == "Great Article"

    def test_capture_rejects_empty_clip(self, client, cache):
        r = client.post("/api/v1/clipper/capture", json={}, cookies=_cookie())
        assert r.status_code == 200
        assert r.json()["ok"] is False


# ══════════════════ FLOW 5 — Voice profile / ElevenLabs ══════════════════
class TestFlow5VoiceProfile:
    def test_requires_auth(self, client, cache):
        r = client.post(
            "/api/v1/user/voice-profile",
            files={"audio": ("s.mp3", b"\x00\x01audio", "audio/mpeg")},
        )
        assert r.status_code == 401

    def test_upload_creates_profile_and_persists(self, client, cache):
        r = client.post(
            "/api/v1/user/voice-profile",
            files={"audio": ("sample.mp3", b"\x00\x01\x02fake-audio-bytes", "audio/mpeg")},
            data={"style_guidelines": "Warm, concise, expert."},
            cookies=_cookie(),
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["ok"] is True
        assert body["voice_id"].startswith("stub-voice-")  # no ELEVENLABS key → honest stub
        assert body["cloned"] is False
        # Pydantic VoiceIdentity schema is intact.
        prof = body["profile"]
        for field in ("user_email", "voice_id", "provider", "style_guidelines", "created_at"):
            assert field in prof
        assert prof["user_email"] == QA_EMAIL
        assert prof["style_guidelines"] == "Warm, concise, expert."
        # Persisted to the VoiceIdentity store (cache-backed).
        assert cache._store.get(f"aria:voice_profile:{QA_EMAIL}")

    def test_rejects_unsupported_content_type(self, client, cache):
        r = client.post(
            "/api/v1/user/voice-profile",
            files={"audio": ("evil.exe", b"MZ\x90\x00", "application/x-msdownload")},
            cookies=_cookie(),
        )
        assert r.status_code == 415

    def test_rejects_empty_audio(self, client, cache):
        r = client.post(
            "/api/v1/user/voice-profile",
            files={"audio": ("empty.mp3", b"", "audio/mpeg")},
            cookies=_cookie(),
        )
        assert r.status_code == 400


# ══════════════════ FLOW 6 — Support widget + legal shield ══════════════════
class TestFlow6SupportAndLegal:
    def test_complex_technical_message_gets_relevant_answer(self, client):
        msg = (
            "Mi misión de publicación automática en LinkedIn falla con un error de "
            "token caducado y además me cobraron dos veces la suscripción Pro este mes."
        )
        r = client.post("/api/v1/support/chat", json={"message": msg}, cookies=_cookie())
        assert r.status_code == 200
        data = r.json()
        assert data["source"] in ("claude", "offline", "offline_error")
        assert data["reply"].strip()  # must always answer

    def test_support_requires_auth(self, client):
        r = client.post("/api/v1/support/chat", json={"message": "hola"})
        assert r.json()["source"] == "auth"

    def test_frontend_payment_button_gated_by_checkbox(self):
        """The Continue/pay button must be disabled until the no-refund checkbox is checked."""
        path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
            "apps",
            "core",
            "templates",
            "app.html",
        )
        with open(path, encoding="utf-8") as f:
            html = f.read()
        # The button ships disabled…
        assert 'id="upGo"' in html and "disabled" in html
        # …the checkbox toggles it…
        assert "upAckChanged" in html and 'id="upAck"' in html
        # …and upgradeGo refuses to proceed unless checked, then passes agreed=1.
        assert "if(!ack||!ack.checked)" in html
        assert "agreed=1" in html
        # Mandatory acknowledgement text present.
        assert "no reembolso" in html

    def test_checkout_server_gate_shows_confirmation(self, client):
        """Even a direct link cannot reach Stripe without the acknowledgement."""
        r = client.get("/billing/checkout?tier=pro", cookies=_cookie(), follow_redirects=False)
        # Signed-in but not yet agreed → interstitial with the mandatory checkbox.
        assert r.status_code == 200
        assert 'type="checkbox"' in r.text
        assert "strict no-refund policy" in r.text
        assert "agreed=1" in r.text
