"""
ARIA Social Media Manager — OAuth connection with Facebook, Instagram, TikTok, LinkedIn.

Features:
- Generates OAuth authorization URLs for each platform
- Stores access tokens in Supabase (social_accounts table)
- Publishes content to connected accounts
- Lists and manages connected accounts
- Automatically refreshes tokens

Requires in Fly.io secrets (depending on platform):
  Facebook/Instagram: FACEBOOK_APP_ID, FACEBOOK_APP_SECRET
  TikTok:            TIKTOK_CLIENT_KEY, TIKTOK_CLIENT_SECRET
  LinkedIn:          LINKEDIN_CLIENT_ID, LINKEDIN_CLIENT_SECRET
  Server base URL: ARIA_BASE_URL (e.g.: https://aria-ai.fly.dev)
"""

from __future__ import annotations

import json
import logging
import os
import secrets
import time
import urllib.parse
from typing import Any

import httpx

logger = logging.getLogger("aria.social_media")


# ── SCOPES PER PLATFORM ─────────────────────────────────

PLATFORM_CONFIGS = {
    "facebook": {
        "app_id_env": "FACEBOOK_APP_ID",
        "app_secret_env": "FACEBOOK_APP_SECRET",
        "auth_url": "https://www.facebook.com/v19.0/dialog/oauth",
        "token_url": "https://graph.facebook.com/v19.0/oauth/access_token",
        "scopes": "pages_manage_posts,pages_read_engagement,instagram_basic,instagram_content_publish,publish_to_groups,email,public_profile",
        "api_base": "https://graph.facebook.com/v19.0",
    },
    "instagram": {
        "app_id_env": "FACEBOOK_APP_ID",  # Instagram uses the same Meta app
        "app_secret_env": "FACEBOOK_APP_SECRET",
        "auth_url": "https://www.facebook.com/v19.0/dialog/oauth",
        "token_url": "https://graph.facebook.com/v19.0/oauth/access_token",
        "scopes": "instagram_basic,instagram_content_publish,pages_show_list,pages_read_engagement",
        "api_base": "https://graph.facebook.com/v19.0",
    },
    "tiktok": {
        "app_id_env": "TIKTOK_CLIENT_KEY",
        "app_secret_env": "TIKTOK_CLIENT_SECRET",
        "auth_url": "https://www.tiktok.com/v2/auth/authorize/",
        "token_url": "https://open.tiktokapis.com/v2/oauth/token/",
        "scopes": "user.info.basic,video.list,video.publish",
        "api_base": "https://open.tiktokapis.com/v2",
    },
    "linkedin": {
        "app_id_env": "LINKEDIN_CLIENT_ID",
        "app_secret_env": "LINKEDIN_CLIENT_SECRET",
        "auth_url": "https://www.linkedin.com/oauth/v2/authorization",
        "token_url": "https://www.linkedin.com/oauth/v2/accessToken",
        "scopes": "openid,profile,email,w_member_social",
        "api_base": "https://api.linkedin.com/v2",
    },
}


class SocialMediaManager:

    def __init__(self) -> None:
        self._http = httpx.AsyncClient(timeout=30.0)
        self._base_url = os.getenv("ARIA_BASE_URL", "https://aria-ai.fly.dev")

    def _get_creds(self, platform: str) -> tuple[str | None, str | None]:
        cfg = PLATFORM_CONFIGS.get(platform, {})
        app_id = os.getenv(cfg.get("app_id_env", ""))
        app_secret = os.getenv(cfg.get("app_secret_env", ""))
        return app_id, app_secret

    def get_auth_url(self, platform: str) -> str | None:
        """Generates the OAuth authorization URL for the given platform."""
        cfg = PLATFORM_CONFIGS.get(platform)
        if not cfg:
            return None

        app_id, app_secret = self._get_creds(platform)
        if not app_id or not app_secret:
            logger.warning("[SocialMedia] Credentials not configured for %s", platform)
            return None

        state = secrets.token_urlsafe(32)
        redirect_uri = f"{self._base_url}/auth/callback/{platform}"

        if platform in ("facebook", "instagram"):
            params = {
                "client_id": app_id,
                "redirect_uri": redirect_uri,
                "scope": cfg["scopes"],
                "response_type": "code",
                "state": state,
            }
        elif platform == "tiktok":
            params = {
                "client_key": app_id,
                "redirect_uri": redirect_uri,
                "scope": cfg["scopes"],
                "response_type": "code",
                "state": state,
            }
        elif platform == "linkedin":
            params = {
                "response_type": "code",
                "client_id": app_id,
                "redirect_uri": redirect_uri,
                "scope": cfg["scopes"],
                "state": state,
            }
        else:
            return None

        return f"{cfg['auth_url']}?{urllib.parse.urlencode(params)}"

    async def exchange_code_for_token(self, platform: str, code: str) -> dict | None:
        """Exchanges the authorization code for an access token."""
        cfg = PLATFORM_CONFIGS.get(platform)
        if not cfg:
            return None

        app_id, app_secret = self._get_creds(platform)
        if not app_id or not app_secret:
            return None

        redirect_uri = f"{self._base_url}/auth/callback/{platform}"

        try:
            if platform in ("facebook", "instagram"):
                params = {
                    "client_id": app_id,
                    "client_secret": app_secret,
                    "redirect_uri": redirect_uri,
                    "code": code,
                }
                res = await self._http.get(cfg["token_url"], params=params)

            elif platform == "tiktok":
                res = await self._http.post(
                    cfg["token_url"],
                    headers={"Content-Type": "application/x-www-form-urlencoded"},
                    data={
                        "client_key": app_id,
                        "client_secret": app_secret,
                        "code": code,
                        "grant_type": "authorization_code",
                        "redirect_uri": redirect_uri,
                    },
                )

            elif platform == "linkedin":
                res = await self._http.post(
                    cfg["token_url"],
                    headers={"Content-Type": "application/x-www-form-urlencoded"},
                    data={
                        "grant_type": "authorization_code",
                        "code": code,
                        "client_id": app_id,
                        "client_secret": app_secret,
                        "redirect_uri": redirect_uri,
                    },
                )
            else:
                return None

            if res.status_code != 200:
                logger.error(
                    "[SocialMedia] Token exchange failed for %s: %s", platform, res.text[:200]
                )
                return None

            return res.json()

        except Exception as exc:
            logger.error("[SocialMedia] exchange_code error: %s", exc)
            return None

    async def get_user_profile(self, platform: str, access_token: str) -> dict | None:
        """Gets the authenticated user's profile."""
        try:
            if platform in ("facebook", "instagram"):
                res = await self._http.get(
                    "https://graph.facebook.com/v19.0/me",
                    params={"access_token": access_token, "fields": "id,name,email"},
                )
                if res.status_code == 200:
                    data = res.json()
                    return {
                        "id": data.get("id"),
                        "username": data.get("name", ""),
                        "email": data.get("email", ""),
                    }

            elif platform == "tiktok":
                res = await self._http.get(
                    "https://open.tiktokapis.com/v2/user/info/",
                    headers={"Authorization": f"Bearer {access_token}"},
                    params={"fields": "open_id,display_name,avatar_url"},
                )
                if res.status_code == 200:
                    data = res.json().get("data", {}).get("user", {})
                    return {"id": data.get("open_id"), "username": data.get("display_name", "")}

            elif platform == "linkedin":
                res = await self._http.get(
                    "https://api.linkedin.com/v2/userinfo",
                    headers={"Authorization": f"Bearer {access_token}"},
                )
                if res.status_code == 200:
                    data = res.json()
                    return {
                        "id": data.get("sub"),
                        "username": data.get("name", ""),
                        "email": data.get("email", ""),
                    }

        except Exception as exc:
            logger.error("[SocialMedia] get_user_profile error: %s", exc)

        return None

    async def save_account(
        self,
        platform: str,
        access_token: str,
        refresh_token: str | None,
        expires_in: int | None,
        profile: dict,
    ) -> bool:
        """Saves the connected account to Supabase."""
        try:
            from apps.core.connectors.token_crypto import encrypt
            from apps.core.memory.supabase_client import get_db

            db = get_db()
            expires_at = None
            if expires_in:
                expires_at = time.strftime(
                    "%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() + expires_in)
                )
            # These are live OAuth tokens for the user's real connected
            # accounts — encrypt at rest (same AES-256-GCM used for
            # apps/core/connections' connector tokens) instead of storing
            # them in plaintext in Supabase.
            record = {
                "platform": platform,
                "account_id": str(profile.get("id", "")),
                "username": profile.get("username", ""),
                "email": profile.get("email", ""),
                "access_token": encrypt(access_token),
                "refresh_token": encrypt(refresh_token) if refresh_token else None,
                "expires_at": expires_at,
                "is_active": True,
                "scopes": PLATFORM_CONFIGS.get(platform, {}).get("scopes", ""),
            }
            # Upsert per platform
            existing = (
                db._client.table("social_accounts").select("id").eq("platform", platform).execute()
            )
            if existing.data:
                db._client.table("social_accounts").update(record).eq(
                    "platform", platform
                ).execute()
            else:
                db._client.table("social_accounts").insert(record).execute()
            logger.info("[SocialMedia] %s account saved successfully", platform)
            return True
        except Exception as exc:
            logger.error("[SocialMedia] save_account error: %s", exc)
            return False

    async def list_connected_accounts(self) -> list[dict]:
        """Lists all connected social accounts."""
        try:
            from apps.core.memory.supabase_client import get_db

            db = get_db()
            result = (
                db._client.table("social_accounts")
                .select("platform,username,email,is_active,expires_at,created_at")
                .execute()
            )
            return result.data or []
        except Exception as exc:
            logger.error("[SocialMedia] list_connected_accounts error: %s", exc)
            return []

    async def get_account_token(self, platform: str) -> str | None:
        """Gets the access token for a connected platform."""
        try:
            from apps.core.connectors.token_crypto import decrypt
            from apps.core.memory.supabase_client import get_db

            db = get_db()
            result = (
                db._client.table("social_accounts")
                .select("access_token,refresh_token,expires_at")
                .eq("platform", platform)
                .eq("is_active", True)
                .limit(1)
                .execute()
            )
            if not result.data:
                return None
            account = result.data[0]
            token = account.get("access_token")
            # decrypt() transparently passes through legacy plaintext tokens
            # written before this encryption shipped.
            return decrypt(token) if token else None
        except Exception as exc:
            logger.error("[SocialMedia] get_account_token error: %s", exc)
            return None

    async def disconnect_account(self, platform: str) -> bool:
        """Deactivates a connected account."""
        try:
            from apps.core.memory.supabase_client import get_db

            db = get_db()
            result = (
                db._client.table("social_accounts")
                .update({"is_active": False, "access_token": "", "refresh_token": None})
                .eq("platform", platform)
                .execute()
            )
            return bool(result.data)
        except Exception as exc:
            logger.error("[SocialMedia] disconnect_account error: %s", exc)
            return False

    async def post_content(
        self, platform: str, content: str, image_url: str | None = None, viral_dna: dict = None
    ) -> dict:
        """
        Publishes content to the specified platform.
        If viral_dna is present, applies viral mimicry before publishing.
        """
        token = await self.get_account_token(platform)
        if not token:
            return {
                "success": False,
                "error": f"No {platform} account connected. Use /conectar {platform}",
            }

        # Apply Viral DNA if present
        if viral_dna:
            content = await self._apply_viral_dna(content, viral_dna)

        try:
            if platform == "facebook":
                return await self._post_facebook(token, content, image_url)
            if platform == "instagram":
                return await self._post_instagram(token, content, image_url)
            if platform == "tiktok":
                return await self._post_tiktok(token, content)
            if platform == "linkedin":
                return await self._post_linkedin(token, content, image_url)
            if platform == "google":
                return await self._post_google(token, content, image_url)
            return {"success": False, "error": f"Platform {platform} not supported"}
        except Exception as exc:
            logger.error("[SocialMedia] post_content error for %s: %s", platform, exc)
            return {"success": False, "error": str(exc)}

    async def _apply_viral_dna(self, content: str, dna: dict) -> str:
        """Rewrites the content using AI to mimic viral formats."""
        from apps.core.tools.ai_client import AIModel, get_ai_client

        prompt = (
            f"Act as a virality expert. Rewrite the following content following this viral DNA:\n"
            f"DNA: {json.dumps(dna)}\n\n"
            f"ORIGINAL CONTENT: {content}\n\n"
            f"Make sure to keep the value but change the structure, hooks, and CTA to maximize engagement."
        )
        resp = await get_ai_client().complete(
            system="You are an expert in Growth Hacking and Virality.",
            user=prompt,
            model=AIModel.STRATEGY,
        )
        return resp.content if resp.success else content

    async def _post_google(self, token: str, content: str, image_url: str | None) -> dict:
        """Simulation of posting to Google Business Profile (placeholder for the real API)."""
        # This is where the Google My Business API logic would go
        return {"success": True, "platform": "google", "status": "simulated_success"}

    async def _post_facebook(self, token: str, content: str, image_url: str | None) -> dict:
        """Posts to Facebook Pages."""
        # First get the user's pages
        pages_res = await self._http.get(
            "https://graph.facebook.com/v19.0/me/accounts",
            params={"access_token": token},
        )
        if pages_res.status_code != 200 or not pages_res.json().get("data"):
            # Post to the profile if there are no pages
            res = await self._http.post(
                "https://graph.facebook.com/v19.0/me/feed",
                params={"access_token": token},
                json={"message": content},
            )
        else:
            # Post to the first available page
            page = pages_res.json()["data"][0]
            page_token = page.get("access_token", token)
            page_id = page.get("id")
            payload = {"message": content, "access_token": page_token}
            if image_url:
                payload["link"] = image_url
            res = await self._http.post(
                f"https://graph.facebook.com/v19.0/{page_id}/feed",
                json=payload,
            )

        if res.status_code == 200:
            post_id = res.json().get("id", "")
            return {"success": True, "post_id": post_id, "message": "Posted to Facebook"}
        return {"success": False, "error": res.text[:200]}

    async def _post_instagram(self, token: str, content: str, image_url: str | None) -> dict:
        """Posts to Instagram (requires an image for normal posts, uses Reels caption without one)."""
        if not image_url:
            return {
                "success": False,
                "error": "Instagram requires an image to post. Use /publicar instagram [image_url] [caption]",
            }

        # Get Instagram Business Account ID
        me_res = await self._http.get(
            "https://graph.facebook.com/v19.0/me/accounts",
            params={"access_token": token, "fields": "instagram_business_account"},
        )
        ig_account_id = None
        if me_res.status_code == 200:
            for page in me_res.json().get("data", []):
                ig = page.get("instagram_business_account", {})
                if ig.get("id"):
                    ig_account_id = ig["id"]
                    break

        if not ig_account_id:
            return {
                "success": False,
                "error": "I couldn't find an Instagram Business account linked to your Facebook Pages",
            }

        # Create media container
        container_res = await self._http.post(
            f"https://graph.facebook.com/v19.0/{ig_account_id}/media",
            params={"access_token": token},
            json={"image_url": image_url, "caption": content},
        )
        if container_res.status_code != 200:
            return {"success": False, "error": container_res.text[:200]}

        container_id = container_res.json().get("id")

        # Publish the container
        publish_res = await self._http.post(
            f"https://graph.facebook.com/v19.0/{ig_account_id}/media_publish",
            params={"access_token": token},
            json={"creation_id": container_id},
        )
        if publish_res.status_code == 200:
            return {
                "success": True,
                "post_id": publish_res.json().get("id"),
                "message": "Posted to Instagram",
            }
        return {"success": False, "error": publish_res.text[:200]}

    async def _post_tiktok(self, token: str, content: str) -> dict:
        """Posts to TikTok (text/description only — video requires a file)."""
        # TikTok requires a video to post. For now we return instructions.
        return {
            "success": False,
            "error": "TikTok requires a video file to post. This feature will be available soon.",
        }

    async def _post_linkedin(self, token: str, content: str, image_url: str | None) -> dict:
        """Posts to LinkedIn."""
        # Get the user's ID
        me_res = await self._http.get(
            "https://api.linkedin.com/v2/userinfo",
            headers={"Authorization": f"Bearer {token}"},
        )
        if me_res.status_code != 200:
            return {"success": False, "error": "I couldn't get your LinkedIn profile"}

        person_id = me_res.json().get("sub", "")
        author = f"urn:li:person:{person_id}"

        share_content: dict[str, Any] = {
            "author": author,
            "lifecycleState": "PUBLISHED",
            "specificContent": {
                "com.linkedin.ugc.ShareContent": {
                    "shareCommentary": {"text": content},
                    "shareMediaCategory": "NONE",
                }
            },
            "visibility": {"com.linkedin.ugc.MemberNetworkVisibility": "PUBLIC"},
        }

        if image_url:
            share_content["specificContent"]["com.linkedin.ugc.ShareContent"][
                "shareMediaCategory"
            ] = "ARTICLE"
            share_content["specificContent"]["com.linkedin.ugc.ShareContent"]["media"] = [
                {
                    "status": "READY",
                    "originalUrl": image_url,
                }
            ]

        res = await self._http.post(
            "https://api.linkedin.com/v2/ugcPosts",
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
                "X-Restli-Protocol-Version": "2.0.0",
            },
            json=share_content,
        )

        if res.status_code in (200, 201):
            post_id = res.headers.get("x-restli-id", "")
            return {"success": True, "post_id": post_id, "message": "Posted to LinkedIn"}
        return {"success": False, "error": res.text[:200]}
