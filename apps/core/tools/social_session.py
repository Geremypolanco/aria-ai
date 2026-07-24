"""
social_session.py — Social network access without official APIs.

ARIA can authenticate to social networks using browser sessions
(cookies) exported by the user. No need for API keys or apps
registered on each platform.

USAGE FLOW:
  1. User opens Twitter/Instagram/etc in their browser (already logged in)
  2. Installs "Cookie-Editor" (Chrome/Firefox extension)
  3. Exports the cookies as JSON
  4. Sends the JSON to ARIA via Telegram (/sesion twitter) or a web form
  5. ARIA stores the encrypted cookies in Redis/Supabase
  6. ARIA uses those cookies to interact with the platforms

SUPPORTED PLATFORMS:
  - Twitter/X    (api.x.com — cookies: auth_token, ct0)
  - Instagram    (i.instagram.com — cookies: sessionid, csrftoken, ds_user_id)
  - TikTok       (www.tiktok.com — cookies: sessionid, ttwid)
  - LinkedIn     (www.linkedin.com — cookies: li_at, JSESSIONID)
  - Facebook     (www.facebook.com — cookies: c_user, xs, datr)
  - YouTube      (www.youtube.com — cookies: SID, HSID, SSID)
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any

import httpx

logger = logging.getLogger("aria.social_session")

# ── PER-PLATFORM CONFIGURATION ─────────────────────────────────────────────

PLATFORM_CONFIG: dict[str, dict] = {
    "twitter": {
        "display_name": "Twitter / X",
        "emoji": "🐦",
        "required_cookies": ["auth_token", "ct0"],
        "optional_cookies": ["twid", "guest_id", "kdt", "d_prefs"],
        "domain": "twitter.com",
        "api_base": "https://api.x.com",
        "test_endpoint": "https://api.x.com/2/users/me",
        "test_headers": {
            "Authorization": "Bearer AAAAAAAAAAAAAAAAAAAAANRILgAAAAAAnNwIzUejRCOuH5E6I6xF8lbg38Q%3DUgnEfs4F8721iQMz14L1KDUdrXkwnOynZv45hi2aXSjskyd0WF",
        },
        "instructions": (
            "1. Open <b>twitter.com</b> in Chrome (already logged in)\n"
            "2. Install the <b>Cookie-Editor</b> extension\n"
            "3. Click Cookie-Editor → <b>Export → Export as JSON</b>\n"
            "4. Copy the whole JSON and paste it here\n\n"
            "The key cookies I need are: <code>auth_token</code> and <code>ct0</code>"
        ),
        "help_url": "https://chromewebstore.google.com/detail/cookie-editor/hlkenndednhfkekhgcdicdfddnkalmdm",
    },
    "instagram": {
        "display_name": "Instagram",
        "emoji": "📸",
        "required_cookies": ["sessionid"],
        "optional_cookies": ["csrftoken", "ds_user_id", "rur", "mid"],
        "domain": "instagram.com",
        "api_base": "https://i.instagram.com",
        "test_endpoint": "https://i.instagram.com/api/v1/accounts/current_user/?edit=true",
        "test_headers": {
            "X-IG-App-ID": "936619743392459",
            "X-IG-WWW-Claim": "0",
        },
        "instructions": (
            "1. Open <b>instagram.com</b> in Chrome (already logged in)\n"
            "2. Install <b>Cookie-Editor</b> if you don't have it\n"
            "3. Click Cookie-Editor → <b>Export → Export as JSON</b>\n"
            "4. Copy the JSON and paste it here\n\n"
            "Key cookie: <code>sessionid</code>"
        ),
        "help_url": "https://chromewebstore.google.com/detail/cookie-editor/hlkenndednhfkekhgcdicdfddnkalmdm",
    },
    "tiktok": {
        "display_name": "TikTok",
        "emoji": "🎵",
        "required_cookies": ["sessionid"],
        "optional_cookies": ["ttwid", "tt_csrf_token", "msToken", "s_v_web_id"],
        "domain": "tiktok.com",
        "api_base": "https://www.tiktok.com/api",
        "test_endpoint": "https://www.tiktok.com/api/user/detail/?uniqueId=me",
        "test_headers": {},
        "instructions": (
            "1. Open <b>tiktok.com</b> in Chrome (already logged in)\n"
            "2. Install <b>Cookie-Editor</b>\n"
            "3. Export → JSON and paste it here\n\n"
            "Key cookie: <code>sessionid</code>"
        ),
        "help_url": "https://chromewebstore.google.com/detail/cookie-editor/hlkenndednhfkekhgcdicdfddnkalmdm",
    },
    "linkedin": {
        "display_name": "LinkedIn",
        "emoji": "💼",
        "required_cookies": ["li_at"],
        "optional_cookies": ["JSESSIONID", "liap", "li_gc", "lidc", "bcookie"],
        "domain": "linkedin.com",
        "api_base": "https://www.linkedin.com/voyager/api",
        "test_endpoint": "https://www.linkedin.com/voyager/api/me",
        "test_headers": {
            "Csrf-Token": "",  # Filled in from the JSESSIONID cookie
            "X-RestLi-Protocol-Version": "2.0.0",
        },
        "instructions": (
            "1. Open <b>linkedin.com</b> in Chrome (already logged in)\n"
            "2. Install <b>Cookie-Editor</b>\n"
            "3. Export → JSON and paste it here\n\n"
            "Key cookie: <code>li_at</code>"
        ),
        "help_url": "https://chromewebstore.google.com/detail/cookie-editor/hlkenndednhfkekhgcdicdfddnkalmdm",
    },
    "facebook": {
        "display_name": "Facebook",
        "emoji": "📘",
        "required_cookies": ["c_user", "xs"],
        "optional_cookies": ["datr", "fr", "sb", "wd"],
        "domain": "facebook.com",
        "api_base": "https://www.facebook.com",
        "test_endpoint": "https://graph.facebook.com/me?fields=id,name",
        "test_headers": {},
        "instructions": (
            "1. Open <b>facebook.com</b> in Chrome (already logged in)\n"
            "2. Install <b>Cookie-Editor</b>\n"
            "3. Export → JSON and paste it here\n\n"
            "Key cookies: <code>c_user</code> and <code>xs</code>"
        ),
        "help_url": "https://chromewebstore.google.com/detail/cookie-editor/hlkenndednhfkekhgcdicdfddnkalmdm",
    },
    "youtube": {
        "display_name": "YouTube",
        "emoji": "▶️",
        "required_cookies": ["SID"],
        "optional_cookies": ["HSID", "SSID", "APISID", "SAPISID", "__Secure-3PAPISID"],
        "domain": "youtube.com",
        "api_base": "https://www.youtube.com",
        "test_endpoint": "https://www.youtube.com/feed/subscriptions",
        "test_headers": {},
        "instructions": (
            "1. Open <b>youtube.com</b> in Chrome (already logged in with Google)\n"
            "2. Install <b>Cookie-Editor</b>\n"
            "3. Export → JSON and paste it here\n\n"
            "Key cookie: <code>SID</code>"
        ),
        "help_url": "https://chromewebstore.google.com/detail/cookie-editor/hlkenndednhfkekhgcdicdfddnkalmdm",
    },
    "shopify": {
        "display_name": "Shopify Admin",
        "emoji": "🛍️",
        "required_cookies": ["_admin_session"],
        "optional_cookies": ["_secure_admin_session_id", "shopify_pay_session_id"],
        "domain": "myshopify.com",
        "api_base": "https://{shop_name}.myshopify.com/admin/api/unstable",
        "test_endpoint": "https://{shop_name}.myshopify.com/admin/shop.json",
        "test_headers": {},
        "instructions": (
            "1. Open your <b>Shopify Admin</b> panel in Chrome\n"
            "2. Install <b>Cookie-Editor</b>\n"
            "3. Export → JSON and paste it here\n\n"
            "Key cookie: <code>_admin_session</code>"
        ),
        "help_url": "https://chromewebstore.google.com/detail/cookie-editor/hlkenndednhfkekhgcdicdfddnkalmdm",
    },
    "tiktok_shop": {
        "display_name": "TikTok Shop Seller",
        "emoji": "📦",
        "required_cookies": ["sessionid"],
        "optional_cookies": ["ttwid", "tt_csrf_token", "msToken"],
        "domain": "tiktok.com",
        "api_base": "https://seller-us.tiktok.com/api/v1",
        "test_endpoint": "https://seller-us.tiktok.com/api/v1/seller/info",
        "test_headers": {},
        "instructions": (
            "1. Open <b>TikTok Shop Seller Center</b> in Chrome\n"
            "2. Install <b>Cookie-Editor</b>\n"
            "3. Export → JSON and paste it here\n\n"
            "Key cookie: <code>sessionid</code>"
        ),
        "help_url": "https://chromewebstore.google.com/detail/cookie-editor/hlkenndednhfkekhgcdicdfddnkalmdm",
    },
}

SUPPORTED_PLATFORMS = list(PLATFORM_CONFIG.keys())


class SocialSessionManager:
    """
    Manages social network sessions based on browser cookies.
    No official APIs — ARIA uses the same sessions as a real browser.
    """

    SESSION_KEY = "aria:social:session:{platform}"
    PENDING_KEY = "aria:social:pending:{chat_id}"
    PENDING_TTL = 600  # 10 minutes to paste the JSON

    def __init__(self) -> None:
        self._http = httpx.AsyncClient(timeout=30.0, follow_redirects=True)

    # ══════════════════════════════════════════════════════════════
    # 1. IMPORT SESSION FROM COOKIES
    # ══════════════════════════════════════════════════════════════

    def parse_cookies_json(self, raw: str) -> dict[str, str] | None:
        """
        Converts Cookie-Editor JSON into a flat dict {name: value}.
        Supports formats: array of {name, value} objects or a flat dict.
        """
        raw = raw.strip()
        # Strip markdown fences if the user included them
        for fence in ["```json\n", "```\n", "```"]:
            if raw.startswith(fence):
                raw = raw[len(fence) :]
        if raw.endswith("```"):
            raw = raw[:-3]
        raw = raw.strip()

        try:
            data = json.loads(raw)
        except json.JSONDecodeError as e:
            logger.warning("[SocialSession] Invalid JSON: %s", e)
            return None

        # Cookie-Editor format: list of objects with {name, value, ...}
        if isinstance(data, list):
            result = {}
            for item in data:
                if isinstance(item, dict) and "name" in item and "value" in item:
                    result[item["name"]] = item["value"]
            return result if result else None

        # Flat dict format: {"cookie_name": "cookie_value", ...}
        if isinstance(data, dict):
            # Verify the values are strings (not nested objects)
            flat = {k: str(v) for k, v in data.items() if not isinstance(v, (dict, list))}
            return flat if flat else None

        return None

    def validate_cookies_for_platform(
        self, cookies: dict[str, str], platform: str
    ) -> dict[str, Any]:
        """Verifies the cookies have the keys required for the platform."""
        cfg = PLATFORM_CONFIG.get(platform)
        if not cfg:
            return {"valid": False, "error": f"Unknown platform: {platform}"}

        required = cfg["required_cookies"]
        missing = [c for c in required if c not in cookies]

        if missing:
            return {
                "valid": False,
                "error": f"Missing required cookies: {', '.join(missing)}",
                "required": required,
                "found": list(cookies.keys()),
            }

        return {
            "valid": True,
            "platform": platform,
            "required_found": required,
            "total_cookies": len(cookies),
        }

    async def save_session(
        self, platform: str, cookies: dict[str, str], user_info: dict | None = None
    ) -> dict[str, Any]:
        """Saves the session to Redis and Supabase for persistence."""
        try:
            from apps.core.connectors.token_crypto import encrypt
            from apps.core.memory.redis_client import get_cache

            cache = get_cache()

            # These cookies are live session credentials for the user's real
            # social accounts (auth_token, li_at, sessionid, ...) — encrypt at
            # rest the same way connector OAuth tokens already are, instead
            # of storing them in plaintext despite this module's own
            # docstring claiming "ARIA stores the cookies encrypted."
            encrypted_cookies = encrypt(json.dumps(cookies))

            session_data = {
                "platform": platform,
                "cookies": encrypted_cookies,
                "user_info": user_info or {},
                "saved_at": time.time(),
                "active": True,
            }

            key = self.SESSION_KEY.format(platform=platform)
            await cache.set(key, session_data, ttl_seconds=86400 * 30)  # 30 days

            # Also save to Supabase for long-term persistence
            try:
                from apps.core.memory.supabase_client import get_db

                db = get_db()
                await db.upsert(
                    "social_sessions",
                    {
                        "platform": platform,
                        "cookies_json": encrypted_cookies,
                        "user_info": json.dumps(user_info or {}),
                        "active": True,
                        "updated_at": "now()",
                    },
                )
            except Exception as db_err:
                logger.warning("[SocialSession] Could not save to Supabase (Redis OK): %s", db_err)

            logger.info("[SocialSession] Session saved: %s (%d cookies)", platform, len(cookies))
            return {"success": True, "platform": platform, "cookies_count": len(cookies)}

        except Exception as exc:
            logger.error("[SocialSession] Error saving session %s: %s", platform, exc)
            return {"success": False, "error": str(exc)}

    async def load_session(self, platform: str) -> dict[str, Any] | None:
        """Loads the saved session for a platform."""
        try:
            from apps.core.connectors.token_crypto import decrypt
            from apps.core.memory.redis_client import get_cache

            cache = get_cache()
            key = self.SESSION_KEY.format(platform=platform)
            session = await cache.get(key)
            if session and isinstance(session, dict):
                raw_cookies = session.get("cookies")
                if isinstance(raw_cookies, str):
                    # New encrypted format (decrypt() transparently passes
                    # through legacy plaintext JSON too, so this also covers
                    # sessions saved before encryption shipped).
                    try:
                        session["cookies"] = json.loads(decrypt(raw_cookies))
                    except Exception as dec_exc:
                        logger.warning(
                            "[SocialSession] Could not decrypt cookies for %s: %s",
                            platform,
                            dec_exc,
                        )
                        session["cookies"] = {}
                return session
            # Fallback: try Supabase
            try:
                from apps.core.memory.supabase_client import get_db

                db = get_db()
                rows = await db.query("social_sessions", {"platform": platform, "active": True})
                if rows:
                    row = rows[0]
                    raw_cookies = row.get("cookies_json", "{}")
                    try:
                        cookies = json.loads(decrypt(raw_cookies))
                    except Exception:
                        cookies = {}
                    return {
                        "platform": platform,
                        "cookies": cookies,
                        "user_info": json.loads(row.get("user_info", "{}")),
                        "active": True,
                    }
            except Exception:
                pass
        except Exception as exc:
            logger.warning("[SocialSession] Could not load session %s: %s", platform, exc)
        return None

    def build_cookie_header(self, cookies: dict[str, str]) -> str:
        """Converts the cookies dict into an HTTP Cookie header."""
        return "; ".join(f"{k}={v}" for k, v in cookies.items())

    async def get_session_headers(self, platform: str) -> dict[str, str] | None:
        """Returns HTTP headers ready to use with the active session."""
        session = await self.load_session(platform)
        if not session:
            return None

        cookies = session.get("cookies", {})
        cfg = PLATFORM_CONFIG.get(platform, {})

        headers = {
            "Cookie": self.build_cookie_header(cookies),
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "es-ES,es;q=0.9,en;q=0.8",
        }

        # Platform-specific additional headers
        extra = dict(cfg.get("test_headers", {}))

        # Twitter needs the x-csrf-token header = ct0
        if platform == "twitter" and "ct0" in cookies:
            extra["x-csrf-token"] = cookies["ct0"]
            extra["x-twitter-active-user"] = "yes"
            extra["x-twitter-auth-type"] = "OAuth2Session"

        # LinkedIn needs CSRF from JSESSIONID
        if platform == "linkedin" and "JSESSIONID" in cookies:
            csrf = cookies["JSESSIONID"].strip('"')
            extra["Csrf-Token"] = csrf

        # Instagram needs X-CSRFToken
        if platform == "instagram" and "csrftoken" in cookies:
            extra["X-CSRFToken"] = cookies["csrftoken"]

        headers.update(extra)
        return headers

    # ══════════════════════════════════════════════════════════════
    # 2. VERIFY THE SESSION WORKS
    # ══════════════════════════════════════════════════════════════

    def _resolve_shop_name(self, session: dict[str, Any]) -> str:
        """Resolve the Shopify {shop_name} template placeholder — prefer a
        value already recorded on the session, fall back to the configured
        SHOPIFY_URL (normalized the same way commerce_tools.py does, since
        the env var may include a scheme prefix)."""
        stored = (session.get("user_info") or {}).get("shop_name")
        if stored:
            return stored
        from apps.core.config import settings

        shop_url = getattr(settings, "SHOPIFY_URL", None) or ""
        base = shop_url.removeprefix("https://").removeprefix("http://").rstrip("/")
        return base.split(".myshopify.com")[0] if base else ""

    async def test_session(self, platform: str) -> dict[str, Any]:
        """Makes a test request to verify the session is active."""
        session = await self.load_session(platform)
        if not session:
            return {"success": False, "error": "No session saved for " + platform}

        cfg = PLATFORM_CONFIG.get(platform, {})
        test_url = cfg.get("test_endpoint")
        if not test_url:
            return {"success": True, "message": "No test endpoint configured"}

        if "{shop_name}" in test_url:
            # Previously never substituted — every request went to the
            # literal, invalid hostname "{shop_name}.myshopify.com".
            shop_name = self._resolve_shop_name(session)
            if not shop_name:
                return {
                    "success": False,
                    "error": (
                        "Could not determine the Shopify shop_name — "
                        "configure SHOPIFY_URL or re-import the session"
                    ),
                }
            test_url = test_url.format(shop_name=shop_name)

        headers = await self.get_session_headers(platform)
        if not headers:
            return {"success": False, "error": "Could not load headers"}

        try:
            resp = await self._http.get(test_url, headers=headers, timeout=15.0)

            if resp.status_code in (200, 201):
                # Try to parse user info
                user_info = {}
                try:
                    data = resp.json()
                    if platform == "twitter":
                        u = data.get("data", {})
                        user_info = {
                            "username": u.get("username"),
                            "name": u.get("name"),
                            "id": u.get("id"),
                        }
                    elif platform == "instagram":
                        u = data.get("user", {})
                        user_info = {
                            "username": u.get("username"),
                            "full_name": u.get("full_name"),
                            "id": u.get("pk"),
                        }
                    elif platform == "linkedin":
                        user_info = {
                            "firstName": data.get("firstName", {})
                            .get("localized", {})
                            .get("es_ES", ""),
                            "lastName": data.get("lastName", {})
                            .get("localized", {})
                            .get("es_ES", ""),
                        }
                except Exception:
                    pass

                return {
                    "success": True,
                    "platform": platform,
                    "status": resp.status_code,
                    "user_info": user_info,
                }

            if resp.status_code in (401, 403):
                return {
                    "success": False,
                    "error": f"Session expired (HTTP {resp.status_code}) — re-import the cookies",
                }
            return {"success": False, "error": f"HTTP {resp.status_code}", "body": resp.text[:200]}

        except Exception as exc:
            logger.error("[SocialSession] test error %s: %s", platform, exc)
            return {"success": False, "error": str(exc)}

    # ══════════════════════════════════════════════════════════════
    # 3. ACTIONS ON EACH PLATFORM
    # ══════════════════════════════════════════════════════════════

    async def post_tweet(self, text: str) -> dict[str, Any]:
        """Posts a tweet using the active Twitter/X session."""
        headers = await self.get_session_headers("twitter")
        if not headers:
            return {
                "success": False,
                "error": "No active Twitter session. Use /sesion twitter",
            }

        try:
            payload = {
                "variables": {
                    "tweet_text": text,
                    "dark_request": False,
                    "media": {"media_entities": [], "possibly_sensitive": False},
                    "semantic_annotation_ids": [],
                },
                "features": {
                    "interactive_text_enabled": True,
                    "longform_notetweets_richtext_consumption_enabled": True,
                    "tweet_with_visibility_results_prefer_gql_limited_actions_policy_enabled": False,
                    "responsive_web_edit_tweet_api_enabled": True,
                    "standardized_nudges_misinfo": True,
                },
                "queryId": "SoVnbfCycZ7fERGCwpZkYA",
            }
            headers["Content-Type"] = "application/json"
            resp = await self._http.post(
                "https://api.x.com/graphql/SoVnbfCycZ7fERGCwpZkYA/CreateTweet",
                headers=headers,
                json=payload,
                timeout=20.0,
            )
            if resp.status_code == 200:
                data = resp.json()
                tweet_id = (
                    data.get("data", {})
                    .get("create_tweet", {})
                    .get("tweet_results", {})
                    .get("result", {})
                    .get("rest_id")
                )
                return {
                    "success": True,
                    "tweet_id": tweet_id,
                    "url": f"https://x.com/i/status/{tweet_id}" if tweet_id else None,
                }
            return {"success": False, "error": f"HTTP {resp.status_code}: {resp.text[:300]}"}
        except Exception as exc:
            return {"success": False, "error": str(exc)}

    async def post_instagram_story_text(self, text: str) -> dict[str, Any]:
        """Creates an Instagram post (text/caption via internal API)."""
        headers = await self.get_session_headers("instagram")
        if not headers:
            return {
                "success": False,
                "error": "No active Instagram session. Use /sesion instagram",
            }
        # Instagram requires an image for normal posts — return useful info
        return {
            "success": False,
            "error": "Instagram requires an image for posts. Use the marketing agent to create images first.",
            "tip": "Call /marketing with the text and ARIA will create the image and publish it.",
        }

    async def post_linkedin(self, text: str) -> dict[str, Any]:
        """Posts to LinkedIn using the active session."""
        headers = await self.get_session_headers("linkedin")
        if not headers:
            return {
                "success": False,
                "error": "No active LinkedIn session. Use /sesion linkedin",
            }

        session = await self.load_session("linkedin")
        user_info = session.get("user_info", {})
        person_id = user_info.get("id") or user_info.get("person_id", "")

        if not person_id:
            # Try to get the user's ID
            try:
                me_resp = await self._http.get(
                    "https://www.linkedin.com/voyager/api/me", headers=headers, timeout=10.0
                )
                if me_resp.status_code == 200:
                    me_data = me_resp.json()
                    person_id = me_data.get("miniProfile", {}).get("entityUrn", "").split(":")[-1]
            except Exception:
                pass

        if not person_id:
            return {"success": False, "error": "Could not get your LinkedIn person ID"}

        try:
            headers["Content-Type"] = "application/json"
            payload = {
                "author": f"urn:li:person:{person_id}",
                "lifecycleState": "PUBLISHED",
                "specificContent": {
                    "com.linkedin.ugc.ShareContent": {
                        "shareCommentary": {"text": text},
                        "shareMediaCategory": "NONE",
                    }
                },
                "visibility": {"com.linkedin.ugc.MemberNetworkVisibility": "PUBLIC"},
            }
            resp = await self._http.post(
                "https://api.linkedin.com/v2/ugcPosts",
                headers=headers,
                json=payload,
                timeout=20.0,
            )
            if resp.status_code in (200, 201):
                post_id = resp.json().get("id", "")
                return {"success": True, "post_id": post_id}
            return {"success": False, "error": f"HTTP {resp.status_code}: {resp.text[:300]}"}
        except Exception as exc:
            return {"success": False, "error": str(exc)}

    async def post_to_platform(
        self, platform: str, text: str, media_url: str | None = None
    ) -> dict[str, Any]:
        """Router: posts to the specified platform."""
        if platform == "twitter":
            return await self.post_tweet(text)
        if platform == "linkedin":
            return await self.post_linkedin(text)
        if platform == "instagram":
            return await self.post_instagram_story_text(text)
        return {"success": False, "error": f"post_to_platform not implemented for: {platform}"}

    # ══════════════════════════════════════════════════════════════
    # 4. PENDING STATE MANAGEMENT (for the Telegram flow)
    # ══════════════════════════════════════════════════════════════

    async def set_pending_import(self, chat_id: str, platform: str) -> None:
        """Marks that the user is in the process of importing cookies for a platform."""
        try:
            from apps.core.memory.redis_client import get_cache

            cache = get_cache()
            await cache.set(
                self.PENDING_KEY.format(chat_id=chat_id),
                platform,
                ttl_seconds=self.PENDING_TTL,
            )
        except Exception as exc:
            logger.warning("[SocialSession] Could not set pending: %s", exc)

    async def get_pending_import(self, chat_id: str) -> str | None:
        """Returns the platform pending cookie import, if any."""
        try:
            from apps.core.memory.redis_client import get_cache

            cache = get_cache()
            val = await cache.get(self.PENDING_KEY.format(chat_id=chat_id))
            if isinstance(val, bytes):
                return val.decode()
            return val if isinstance(val, str) else None
        except Exception:
            return None

    async def clear_pending_import(self, chat_id: str) -> None:
        """Clears the pending import state."""
        try:
            from apps.core.memory.redis_client import get_cache

            cache = get_cache()
            await cache.delete(self.PENDING_KEY.format(chat_id=chat_id))
        except Exception:
            pass

    # ══════════════════════════════════════════════════════════════
    # 5. SESSION SUMMARY
    # ══════════════════════════════════════════════════════════════

    async def list_active_sessions(self) -> list[dict[str, Any]]:
        """Lists all platforms with an active session."""
        results = []
        for platform in SUPPORTED_PLATFORMS:
            session = await self.load_session(platform)
            if session and session.get("active"):
                cfg = PLATFORM_CONFIG[platform]
                saved_at = session.get("saved_at", 0)
                age_days = int((time.time() - saved_at) / 86400) if saved_at else 0
                results.append(
                    {
                        "platform": platform,
                        "display_name": cfg["display_name"],
                        "emoji": cfg["emoji"],
                        "cookies_count": len(session.get("cookies", {})),
                        "user_info": session.get("user_info", {}),
                        "age_days": age_days,
                    }
                )
        return results

    async def delete_session(self, platform: str) -> dict[str, Any]:
        """Deletes a platform's session."""
        try:
            from apps.core.memory.redis_client import get_cache

            cache = get_cache()
            key = self.SESSION_KEY.format(platform=platform)
            await cache.delete(key)
            # Also in Supabase
            try:
                from apps.core.memory.supabase_client import get_db

                db = get_db()
                await db.update("social_sessions", {"active": False}, {"platform": platform})
            except Exception:
                pass
            return {"success": True, "platform": platform}
        except Exception as exc:
            return {"success": False, "error": str(exc)}


# ── SINGLETON ─────────────────────────────────────────────────────────────────

_manager: SocialSessionManager | None = None


def get_social_session_manager() -> SocialSessionManager:
    global _manager
    if _manager is None:
        _manager = SocialSessionManager()
    return _manager
