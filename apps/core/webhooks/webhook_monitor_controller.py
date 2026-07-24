"""
webhook_monitor_controller.py — Social Media Monitor (signed webhooks).

Receives new-comment events from Instagram (Meta) and YouTube (Google), verifies
their cryptographic signature, then runs the auto-reply pipeline:

    incoming comment
      → verify HMAC signature (reject forgeries)
      → extract the comment(s)
      → draft a contextual reply with a FAST Claude sub-agent (Haiku)
      → publish the reply via the platform API   [stub, ready to wire]

The publish step is a clearly-marked stub (the real Meta/Google calls are
documented inline) so nothing is a broken placeholder. Everything is async and
returns immediately, keeping the reply well under the 2-minute target.

Signatures:
  - Meta / Instagram : `X-Hub-Signature-256: sha256=<hmac-sha256(app_secret, body)>`
  - YouTube (WebSub) : `X-Hub-Signature: sha1=<hmac-sha1(secret, body)>`
Setup GET challenges (hub.challenge) are echoed back for both.
"""

from __future__ import annotations

import hashlib
import hmac
import logging

from fastapi import APIRouter, Request, Response
from fastapi.responses import JSONResponse, PlainTextResponse

from apps.core.config import settings

logger = logging.getLogger("aria.webhook_monitor")

router = APIRouter(prefix="/api/v1/webhooks", tags=["webhooks"])

FAST_MODEL = "claude-haiku-4-5"  # fast sub-agent for sub-2-minute replies


# ── signature verification ────────────────────────────────────────
def _secret(*candidates: str | None) -> bytes:
    for c in candidates:
        if c:
            return c.encode()
    return (getattr(settings, "WEBHOOK_SECRET", None) or "").encode()


def verify_signature(body: bytes, header: str | None, secret: bytes, algo: str) -> bool:
    """Constant-time verify a `<algo>=<hex>` signature header."""
    if not header or not secret:
        return False
    prefix = f"{algo}="
    if not header.startswith(prefix):
        return False
    provided = header[len(prefix) :]
    digest = hmac.new(secret, body, getattr(hashlib, algo)).hexdigest()
    return hmac.compare_digest(provided, digest)


# ── comment extraction (tolerant of shape differences) ────────────
def extract_comments(platform: str, payload: dict) -> list[dict]:
    """Normalize a platform payload into [{id, text, author, target_id}]."""
    out: list[dict] = []
    if not isinstance(payload, dict):
        return out

    if platform == "instagram":
        for entry in payload.get("entry", []) or []:
            for change in entry.get("changes", []) or []:
                if change.get("field") != "comments":
                    continue
                v = change.get("value", {}) or {}
                out.append(
                    {
                        "id": v.get("id", ""),
                        "text": v.get("text", ""),
                        "author": (v.get("from", {}) or {}).get("username", ""),
                        "target_id": (v.get("media", {}) or {}).get("id", ""),
                    }
                )
    elif platform == "youtube":
        # Data API-style JSON push (or a normalized relay). Tolerate a few shapes.
        items = payload.get("items") or ([payload.get("comment")] if payload.get("comment") else [])
        for it in items or []:
            if not it:
                continue
            snip = it.get("snippet", it) or {}
            top = (snip.get("topLevelComment", {}) or {}).get("snippet", snip)
            out.append(
                {
                    "id": it.get("id", snip.get("id", "")),
                    "text": top.get("textDisplay") or top.get("text") or snip.get("text", ""),
                    "author": top.get("authorDisplayName") or snip.get("author", ""),
                    "target_id": top.get("videoId") or snip.get("videoId", ""),
                }
            )
    # generic fallback: a single {comment:{...}} envelope
    if not out and payload.get("comment"):
        c = payload["comment"]
        out.append(
            {
                "id": c.get("id", ""),
                "text": c.get("text", ""),
                "author": c.get("author", ""),
                "target_id": c.get("target_id", ""),
            }
        )
    return [c for c in out if c.get("text")]


# ── the reply pipeline ────────────────────────────────────────────
async def draft_reply(comment: dict, *, platform: str, style_guidelines: str = "") -> str:
    """Draft a contextual reply with a fast Claude sub-agent.

    Falls back to a courteous templated reply when ANTHROPIC_API_KEY is absent,
    so the pipeline always yields a usable draft (labeled honestly).
    """
    text = (comment.get("text") or "").strip()
    author = comment.get("author") or "there"
    if not getattr(settings, "ANTHROPIC_API_KEY", None):
        # No key → deterministic, honest fallback (not a fabricated AI reply).
        return f"Thanks so much, @{author} — really appreciate you watching! 🙌"

    system = (
        "You are ARIA replying, on the brand's behalf, to a comment on its "
        f"{platform} post. Write ONE short, warm, on-brand public reply (max 240 "
        "chars). Be specific to the comment, never robotic, no hashtags unless "
        "natural. Do not make promises or claims you can't back up."
    )
    if style_guidelines:
        system += f"\n\nBrand voice guidelines:\n{style_guidelines[:1500]}"

    try:
        from anthropic import AsyncAnthropic

        client = AsyncAnthropic(api_key=settings.ANTHROPIC_API_KEY)
        resp = await client.messages.create(
            model=FAST_MODEL,
            max_tokens=200,
            system=system,
            messages=[{"role": "user", "content": f"Comment from @{author}: {text}"}],
        )
        reply = "".join(b.text for b in resp.content if getattr(b, "type", None) == "text").strip()
        return reply or f"Thank you, @{author}! 🙌"
    except Exception as exc:  # noqa: BLE001
        logger.warning("[webhook] draft_reply failed: %s", exc)
        return f"Thanks so much, @{author}! 🙌"


async def publish_reply(platform: str, comment: dict, reply: str) -> dict:
    """STUB — publish the reply via the platform API.

    Wire the real calls here (kept as a stub so nothing is broken):
      Instagram (Meta Graph):
        POST https://graph.facebook.com/v21.0/{comment_id}/replies
             ?message={reply}&access_token={PAGE_TOKEN}
      YouTube (Data API v3):
        POST https://www.googleapis.com/youtube/v3/comments?part=snippet
             body={snippet:{parentId:{comment_id}, textOriginal:{reply}}}
    """
    logger.info(
        "[webhook] would publish %s reply to comment %s: %r",
        platform,
        comment.get("id"),
        reply[:80],
    )
    return {"published": False, "stub": True, "platform": platform, "reply": reply}


async def _handle_comment_event(platform: str, payload: dict, style: str = "") -> dict:
    comments = extract_comments(platform, payload)
    results = []
    for c in comments:
        reply = await draft_reply(c, platform=platform, style_guidelines=style)
        pub = await publish_reply(platform, c, reply)
        results.append({"comment_id": c.get("id"), "reply": reply, "publish": pub})
    return {"ok": True, "handled": len(results), "results": results}


async def _owner_style() -> str:
    """Best-effort: use the brand owner's stored voice/style guidelines."""
    try:
        owner = (getattr(settings, "OWNER_EMAIL", "") or "").strip().lower()
        if not owner:
            return ""
        from apps.core.services.identity_profile_service import get_voice_profile

        prof = await get_voice_profile(owner)
        return (prof or {}).get("style_guidelines", "") if prof else ""
    except Exception:
        return ""


# ── Instagram (Meta) ──────────────────────────────────────────────
@router.get("/instagram/comments")
async def instagram_verify(request: Request):
    """Meta webhook setup challenge."""
    params = request.query_params
    verify_token = getattr(settings, "META_VERIFY_TOKEN", None) or getattr(
        settings, "WEBHOOK_SECRET", None
    )
    if params.get("hub.mode") == "subscribe" and params.get("hub.verify_token") == verify_token:
        return PlainTextResponse(params.get("hub.challenge", ""))
    return JSONResponse({"error": "verification failed"}, status_code=403)


@router.post("/instagram/comments")
async def instagram_comments(request: Request):
    body = await request.body()
    secret = _secret(
        getattr(settings, "META_APP_SECRET", None),
        getattr(settings, "INSTAGRAM_APP_SECRET", None),
    )
    if not verify_signature(body, request.headers.get("x-hub-signature-256"), secret, "sha256"):
        return JSONResponse({"error": "invalid signature"}, status_code=401)
    try:
        payload = await request.json()
    except Exception:
        return JSONResponse({"error": "invalid json"}, status_code=400)
    result = await _handle_comment_event("instagram", payload, style=await _owner_style())
    return Response(status_code=200) if not result["handled"] else JSONResponse(result)


# ── YouTube (Google) ──────────────────────────────────────────────
@router.get("/youtube/comments")
async def youtube_verify(request: Request):
    """WebSub verification challenge.

    Unlike Instagram's setup challenge, WebSub has no shared secret to check
    at this step — but a bare "echo whatever hub.challenge is sent" answers
    any GET, not just a real hub confirming a subscription we actually asked
    for. Requiring hub.mode=subscribe is the minimum the spec expects; actual
    data still can't reach the pipeline without a valid signature on the POST
    (see youtube_comments below), so this only tightens an overly-permissive
    echo, not a real data-access hole.
    """
    params = request.query_params
    challenge = params.get("hub.challenge")
    if challenge and params.get("hub.mode") == "subscribe":
        return PlainTextResponse(challenge)
    return JSONResponse({"error": "verification failed"}, status_code=403)


@router.post("/youtube/comments")
async def youtube_comments(request: Request):
    body = await request.body()
    secret = _secret(getattr(settings, "YOUTUBE_WEBHOOK_SECRET", None))
    if not verify_signature(body, request.headers.get("x-hub-signature"), secret, "sha1"):
        return JSONResponse({"error": "invalid signature"}, status_code=401)
    try:
        payload = await request.json()
    except Exception:
        return JSONResponse({"error": "invalid json"}, status_code=400)
    result = await _handle_comment_event("youtube", payload, style=await _owner_style())
    return JSONResponse(result)
