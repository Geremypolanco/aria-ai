"""Unit tests for the three new feature components:
clipper backend, social webhook monitor, and the identity/voice service.
"""

from __future__ import annotations

import hashlib
import hmac
import json

from apps.core.services.identity_profile_service import VoiceIdentity, clone_voice_elevenlabs
from apps.core.webhooks import webhook_monitor_controller as wm


# ── webhook signature verification ────────────────────────────────
def test_verify_signature_valid_and_invalid():
    secret = b"topsecret"
    body = b'{"hello":"world"}'
    good = "sha256=" + hmac.new(secret, body, hashlib.sha256).hexdigest()
    assert wm.verify_signature(body, good, secret, "sha256") is True
    assert wm.verify_signature(body, "sha256=deadbeef", secret, "sha256") is False
    assert wm.verify_signature(body, None, secret, "sha256") is False
    assert wm.verify_signature(body, good, b"", "sha256") is False  # no secret


def test_verify_signature_sha1_youtube():
    secret = b"yt"
    body = b"<feed/>"
    good = "sha1=" + hmac.new(secret, body, hashlib.sha1).hexdigest()
    assert wm.verify_signature(body, good, secret, "sha1") is True


# ── comment extraction ────────────────────────────────────────────
def test_extract_instagram_comments():
    payload = {
        "entry": [
            {
                "changes": [
                    {
                        "field": "comments",
                        "value": {
                            "id": "c1",
                            "text": "love this!",
                            "from": {"username": "alice"},
                            "media": {"id": "m9"},
                        },
                    }
                ]
            }
        ]
    }
    out = wm.extract_comments("instagram", payload)
    assert out == [{"id": "c1", "text": "love this!", "author": "alice", "target_id": "m9"}]


def test_extract_youtube_and_generic():
    yt = {"comment": {"id": "y1", "text": "nice video", "author": "bob", "target_id": "v2"}}
    out = wm.extract_comments("youtube", yt)
    assert out and out[0]["text"] == "nice video" and out[0]["author"] == "bob"
    # empty-text comments are dropped
    assert wm.extract_comments("instagram", {"entry": []}) == []


# ── reply pipeline (no API key → honest fallback, no network) ──────
async def test_draft_reply_fallback_without_key(monkeypatch):
    monkeypatch.setattr(wm.settings, "ANTHROPIC_API_KEY", None, raising=False)
    reply = await wm.draft_reply({"text": "great!", "author": "cara"}, platform="instagram")
    assert "cara" in reply and len(reply) <= 240


async def test_publish_reply_is_stub():
    out = await wm.publish_reply("instagram", {"id": "c1"}, "thanks!")
    assert out["stub"] is True and out["published"] is False


async def test_handle_event_end_to_end_stub(monkeypatch):
    monkeypatch.setattr(wm.settings, "ANTHROPIC_API_KEY", None, raising=False)
    payload = {"comment": {"id": "c1", "text": "amazing", "author": "dee"}}
    res = await wm._handle_comment_event("youtube", payload)
    assert res["handled"] == 1
    assert res["results"][0]["publish"]["stub"] is True


# ── identity / voice service ──────────────────────────────────────
def test_voice_identity_model():
    vi = VoiceIdentity(user_email="U@X.com", voice_id="v1", style_guidelines="be witty")
    d = vi.to_dict()
    assert d["user_email"] == "U@X.com"
    assert d["voice_id"] == "v1"
    assert d["style_guidelines"] == "be witty"
    assert d["provider"] == "elevenlabs"


async def test_clone_voice_stub_without_key(monkeypatch):
    monkeypatch.setattr(
        __import__("apps.core.services.identity_profile_service", fromlist=["settings"]).settings,
        "ELEVENLABS_API_KEY",
        None,
        raising=False,
    )
    voice_id, is_real = await clone_voice_elevenlabs(b"\x00\x01audio", "s.mp3", "test")
    assert is_real is False
    assert voice_id.startswith("stub-voice-")


# ── clipper request model ─────────────────────────────────────────
def test_clip_request_caps_lengths():
    from apps.core.routes.clipper import ClipRequest

    c = ClipRequest(url="http://x", title="t", selection="hi", clipped_at="2026")
    assert json.loads(c.model_dump_json())["selection"] == "hi"
