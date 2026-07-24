"""
oauth_hub.py — Real one-click OAuth2 connect for external providers.

This is the engine behind the dashboard "Connect" buttons. Unlike the old
waitlist (which only recorded a request), this performs a genuine OAuth2
Authorization-Code flow:

    Connect  →  provider consent screen  →  callback  →  token stored  →  Connected

Every provider needs its own developer app (Client ID + Secret) configured as
settings/secrets — the connector goes live the moment those exist, and honestly
reports "setup" until then (no fake "connected" state). A few providers don't
fit a plain redirect flow and are marked `special`:
  - shopify : OAuth is per-store (needs the shop domain) — handled as setup.
  - zapier  : integrates via API key / webhook, not a redirect OAuth.

Security: CSRF state is signed + browser-bound via a cookie (reusing
auth.make_state/check_state). PKCE is used where the provider requires it (X).
Tokens are stored per user in the cache, never exposed to the browser.
"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import secrets
import time
import urllib.parse
from dataclasses import dataclass, field

from apps.core.config import settings

logger = logging.getLogger("aria.connectors")

STATE_COOKIE = "aria_conn_state"
_TOKEN_KEY = "aria:conn:{email}:{pid}"


@dataclass(frozen=True)
class Provider:
    id: str
    name: str
    desc: str
    color: str
    icon: str
    authorize_url: str = ""
    token_url: str = ""
    scope: str = ""
    cid_key: str = ""  # settings attr holding the client id
    csec_key: str = ""  # settings attr holding the client secret
    cid_param: str = "client_id"  # some providers name it differently (tiktok: client_key)
    extra_auth: dict = field(default_factory=dict)
    pkce: bool = False
    token_basic: bool = False  # send client creds via HTTP Basic instead of body
    token_headers: dict = field(default_factory=dict)
    special: str = ""  # "" | "shopify" | "apikey"
    note: str = ""  # honest caveat shown in the UI / setup docs


# ── Registry: Claude's connector set ──────────────────────────────
# Icons/colors mirror the existing dashboard list so the UI is unchanged.
PROVIDERS: dict[str, Provider] = {
    "google": Provider(
        "google",
        "Google",
        "Gmail, Drive, Calendar",
        "#ea4335",
        "G",
        authorize_url="https://accounts.google.com/o/oauth2/v2/auth",
        token_url="https://oauth2.googleapis.com/token",
        scope="openid email profile https://www.googleapis.com/auth/gmail.send "
        "https://www.googleapis.com/auth/calendar.events "
        "https://www.googleapis.com/auth/drive.file",
        cid_key="GOOGLE_CLIENT_ID",
        csec_key="GOOGLE_CLIENT_SECRET",
        extra_auth={"access_type": "offline", "prompt": "consent"},
        note="Sensitive Google scopes require Google app verification before "
        "other users can grant them.",
    ),
    "linkedin": Provider(
        "linkedin",
        "LinkedIn",
        "Publish & grow your audience",
        "#0a66c2",
        "in",
        authorize_url="https://www.linkedin.com/oauth/v2/authorization",
        token_url="https://www.linkedin.com/oauth/v2/accessToken",
        scope="openid profile email w_member_social",
        cid_key="LINKEDIN_CLIENT_ID",
        csec_key="LINKEDIN_CLIENT_SECRET",
    ),
    "youtube": Provider(
        "youtube",
        "YouTube",
        "Upload & manage videos",
        "#ff0000",
        "▶",
        authorize_url="https://accounts.google.com/o/oauth2/v2/auth",
        token_url="https://oauth2.googleapis.com/token",
        scope="https://www.googleapis.com/auth/youtube.upload "
        "https://www.googleapis.com/auth/youtube.readonly",
        cid_key="GOOGLE_CLIENT_ID",
        csec_key="GOOGLE_CLIENT_SECRET",
        extra_auth={"access_type": "offline", "prompt": "consent"},
        note="Uses your Google OAuth app; upload scope needs Google verification.",
    ),
    "instagram": Provider(
        "instagram",
        "Instagram",
        "Post reels & images",
        "#e1306c",
        "◎",
        authorize_url="https://www.facebook.com/v21.0/dialog/oauth",
        token_url="https://graph.facebook.com/v21.0/oauth/access_token",
        scope="instagram_basic,instagram_content_publish,pages_show_list",
        cid_key="META_APP_ID",
        csec_key="META_APP_SECRET",
        note="Requires a Meta app with Instagram Graph API and App Review to "
        "publish for real users.",
    ),
    "facebook": Provider(
        "facebook",
        "Facebook",
        "Pages & posts",
        "#1877f2",
        "f",
        authorize_url="https://www.facebook.com/v21.0/dialog/oauth",
        token_url="https://graph.facebook.com/v21.0/oauth/access_token",
        scope="public_profile,pages_manage_posts,pages_read_engagement",
        cid_key="META_APP_ID",
        csec_key="META_APP_SECRET",
        note="Requires Meta App Review for the pages_* permissions.",
    ),
    "shopify": Provider(
        "shopify",
        "Shopify",
        "Products, orders, store",
        "#5a8e2f",
        "S",
        special="shopify",
        note="Shopify OAuth is per-store — connect from your store's admin or "
        "provide your shop domain + Admin API token in Settings.",
    ),
    "stripe": Provider(
        "stripe",
        "Stripe",
        "Payments & billing",
        "#635bff",
        "S",
        authorize_url="https://connect.stripe.com/oauth/authorize",
        token_url="https://connect.stripe.com/oauth/token",
        scope="read_write",
        cid_key="STRIPE_CONNECT_CLIENT_ID",
        csec_key="STRIPE_SECRET_KEY",
        note="Uses Stripe Connect (Connect client id + your secret key).",
    ),
    "slack": Provider(
        "slack",
        "Slack",
        "Notify your team",
        "#4a154b",
        "#",
        authorize_url="https://slack.com/oauth/v2/authorize",
        token_url="https://slack.com/api/oauth.v2.access",
        scope="chat:write,channels:read",
        cid_key="SLACK_CLIENT_ID",
        csec_key="SLACK_CLIENT_SECRET",
    ),
    "notion": Provider(
        "notion",
        "Notion",
        "Docs & databases",
        "#1a1a1a",
        "N",
        authorize_url="https://api.notion.com/v1/oauth/authorize",
        token_url="https://api.notion.com/v1/oauth/token",
        scope="",
        cid_key="NOTION_OAUTH_CLIENT_ID",
        csec_key="NOTION_OAUTH_CLIENT_SECRET",
        extra_auth={"owner": "user"},
        token_basic=True,
    ),
    "x": Provider(
        "x",
        "X (Twitter)",
        "Post & schedule",
        "#111111",
        "𝕏",
        authorize_url="https://twitter.com/i/oauth2/authorize",
        token_url="https://api.twitter.com/2/oauth2/token",
        scope="tweet.read tweet.write users.read offline.access",
        cid_key="TWITTER_OAUTH_CLIENT_ID",
        csec_key="TWITTER_OAUTH_CLIENT_SECRET",
        pkce=True,
        token_basic=True,
    ),
    "tiktok": Provider(
        "tiktok",
        "TikTok",
        "Short-form video",
        "#111111",
        "♪",
        authorize_url="https://www.tiktok.com/v2/auth/authorize/",
        token_url="https://open.tiktokapis.com/v2/oauth/token/",
        scope="user.info.basic,video.publish",
        cid_key="TIKTOK_CLIENT_KEY",
        csec_key="TIKTOK_CLIENT_SECRET",
        cid_param="client_key",
        note="Requires a TikTok for Developers app with the Content Posting API.",
    ),
    "zapier": Provider(
        "zapier",
        "Zapier",
        "9,000+ apps via automations",
        "#ff4a00",
        "⚡",
        special="apikey",
        note="Connect via a Zapier webhook URL / API key in Settings (Zapier "
        "does not use a redirect OAuth for this).",
    ),
    "activepieces": Provider(
        "activepieces",
        "Activepieces",
        "200+ apps, self-hosted",
        "#6e41e2",
        "AP",
        special="activepieces",
        note="Self-hosted (see infra/activepieces/) — paste your instance's MCP "
        "endpoint URL in Settings. No redirect OAuth for this either.",
    ),
}

ORDER = list(PROVIDERS.keys())


# ── configuration / status ────────────────────────────────────────
def _get(attr: str) -> str | None:
    return getattr(settings, attr, None)


def is_configured(pid: str) -> bool:
    """True when this connector has what it needs to start a real connect."""
    p = PROVIDERS.get(pid)
    if not p:
        return False
    if p.special == "shopify":
        return bool(_get("SHOPIFY_ADMIN_TOKEN") and _get("SHOPIFY_URL"))
    if p.special == "apikey":
        return bool(_get("ZAPIER_WEBHOOK_URL") or _get("ZAPIER_MCP_URL"))
    if p.special == "activepieces":
        return bool(_get("ACTIVEPIECES_MCP_URL"))
    return bool(_get(p.cid_key) and _get(p.csec_key))


def _base_url() -> str:
    from apps.core import auth

    return auth._base()


def redirect_uri(pid: str) -> str:
    return f"{_base_url()}/connectors/{pid}/callback"


# ── PKCE ──────────────────────────────────────────────────────────
def _pkce_pair() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(64)[:96]
    challenge = (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
    )
    return verifier, challenge


# ── authorize URL ─────────────────────────────────────────────────
def build_authorize(pid: str, state: str) -> tuple[str, str]:
    """Return (authorize_url, pkce_verifier). verifier is '' when PKCE unused."""
    p = PROVIDERS[pid]
    params = {
        p.cid_param: _get(p.cid_key),
        "redirect_uri": redirect_uri(pid),
        "response_type": "code",
        "state": state,
    }
    if p.scope:
        params["scope"] = p.scope
    params.update(p.extra_auth)
    verifier = ""
    if p.pkce:
        verifier, challenge = _pkce_pair()
        params["code_challenge"] = challenge
        params["code_challenge_method"] = "S256"
    return p.authorize_url + "?" + urllib.parse.urlencode(params), verifier


# ── token exchange ────────────────────────────────────────────────
async def exchange_code(pid: str, code: str, verifier: str = "") -> dict | None:
    """Exchange an auth code for a token. Returns the token dict or None."""
    p = PROVIDERS[pid]
    data = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": redirect_uri(pid),
    }
    headers = {"Accept": "application/json"}
    headers.update(p.token_headers)
    if p.token_basic:
        cid, csec = _get(p.cid_key) or "", _get(p.csec_key) or ""
        basic = base64.b64encode(f"{cid}:{csec}".encode()).decode()
        headers["Authorization"] = f"Basic {basic}"
        # PKCE public clients still send client_id in the body per RFC 7636.
        if p.pkce:
            data["client_id"] = cid
    else:
        data[p.cid_param] = _get(p.cid_key)
        data["client_secret"] = _get(p.csec_key)
    if verifier:
        data["code_verifier"] = verifier
    try:
        import httpx

        async with httpx.AsyncClient(timeout=20.0) as c:
            r = await c.post(p.token_url, data=data, headers=headers)
        if r.status_code != 200:
            logger.warning(
                "[connectors] %s token exchange %s: %s", pid, r.status_code, r.text[:200]
            )
            return None
        return r.json()
    except Exception as exc:  # noqa: BLE001
        logger.warning("[connectors] %s token exchange failed: %s", pid, exc)
        return None


# ── token storage (per user) ──────────────────────────────────────
async def save_token(email: str, pid: str, token: dict) -> None:
    record = {
        "access_token": token.get("access_token", ""),
        "refresh_token": token.get("refresh_token", ""),
        "scope": token.get("scope", ""),
        "obtained_at": int(time.time()),
        "expires_in": token.get("expires_in"),
        # Provider-specific passthrough some connectors need (e.g. Salesforce's
        # per-org instance_url, used to template its base_url).
        "instance_url": token.get("instance_url"),
    }
    try:
        from apps.core.connectors import token_crypto
        from apps.core.memory.redis_client import get_cache

        # Encrypt the whole record (access + refresh tokens) at rest — AES-256-GCM.
        blob = token_crypto.encrypt(json.dumps(record))
        await get_cache().set(
            _TOKEN_KEY.format(email=email, pid=pid),
            blob,
            ttl_seconds=400 * 24 * 3600,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("[connectors] save token failed for %s/%s: %s", email, pid, exc)


async def get_token(email: str, pid: str) -> dict | None:
    try:
        from apps.core.connectors import token_crypto
        from apps.core.memory.redis_client import get_cache

        raw = await get_cache().get(_TOKEN_KEY.format(email=email, pid=pid))
        if not raw:
            return None
        # decrypt() transparently passes through any legacy plaintext record.
        decoded = token_crypto.decrypt(raw) if isinstance(raw, str) else raw
        return json.loads(decoded) if isinstance(decoded, str) else decoded
    except Exception:
        return None


async def disconnect(email: str, pid: str) -> None:
    try:
        from apps.core.memory.redis_client import get_cache

        await get_cache().delete(_TOKEN_KEY.format(email=email, pid=pid))
    except Exception:
        pass


def callback_uri(pid: str) -> str:
    """The exact redirect URI to register in the provider's OAuth app.

    Google/YouTube reuse the already-registered login callback, so their setup
    needs no new redirect URI.
    """
    if pid in ("google", "youtube"):
        return f"{_base_url()}/auth/google/callback"
    return redirect_uri(pid)


def missing_secrets(pid: str) -> list[str]:
    """Which credential env vars still need setting for this connector."""
    p = PROVIDERS.get(pid)
    if not p:
        return []
    if p.special == "shopify":
        keys = ["SHOPIFY_URL", "SHOPIFY_ADMIN_TOKEN"]
    elif p.special == "apikey":
        keys = ["ZAPIER_WEBHOOK_URL"]
    elif p.special == "activepieces":
        keys = ["ACTIVEPIECES_MCP_URL"]
    else:
        keys = [k for k in (p.cid_key, p.csec_key) if k]
    return [k for k in keys if not _get(k)]


async def status_for(email: str) -> list[dict]:
    """UI status for every connector: connected / ready / setup."""
    out = []
    for pid in ORDER:
        p = PROVIDERS[pid]
        configured = is_configured(pid)
        connected = bool(email) and bool(await get_token(email, pid))
        state = "connected" if connected else ("ready" if configured else "setup")
        out.append(
            {
                "id": pid,
                "name": p.name,
                "desc": p.desc,
                "color": p.color,
                "icon": p.icon,
                "state": state,
                "note": p.note,
                "special": p.special,
                "redirect_uri": (
                    "" if (pid in ("google", "youtube") or p.special) else callback_uri(pid)
                ),
                "reuse_login": pid in ("google", "youtube"),
                "needs": missing_secrets(pid),
            }
        )
    return out
