"""
ARIA Social Media Manager — Conexion OAuth con Facebook, Instagram, TikTok, LinkedIn.

Funcionalidades:
- Genera URLs de autorizacion OAuth para cada plataforma
- Almacena tokens de acceso en Supabase (tabla social_accounts)
- Publica contenido en cuentas conectadas
- Lista y gestiona cuentas conectadas
- Refresca tokens automaticamente

Requiere en Fly.io secrets (segun plataforma):
  Facebook/Instagram: FACEBOOK_APP_ID, FACEBOOK_APP_SECRET
  TikTok:            TIKTOK_CLIENT_KEY, TIKTOK_CLIENT_SECRET
  LinkedIn:          LINKEDIN_CLIENT_ID, LINKEDIN_CLIENT_SECRET
  URL base del servidor: ARIA_BASE_URL (ej: https://aria-ai.fly.dev)
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


# ── SCOPES POR PLATAFORMA ─────────────────────────────────

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
        "app_id_env": "FACEBOOK_APP_ID",  # Instagram usa el mismo app de Meta
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
        """Genera la URL de autorizacion OAuth para la plataforma indicada."""
        cfg = PLATFORM_CONFIGS.get(platform)
        if not cfg:
            return None

        app_id, app_secret = self._get_creds(platform)
        if not app_id or not app_secret:
            logger.warning("[SocialMedia] Credenciales no configuradas para %s", platform)
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
        """Intercambia el codigo de autorizacion por un access token."""
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
        """Obtiene el perfil del usuario autenticado."""
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
        """Guarda la cuenta conectada en Supabase."""
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
            # Upsert por plataforma
            existing = (
                db._client.table("social_accounts").select("id").eq("platform", platform).execute()
            )
            if existing.data:
                db._client.table("social_accounts").update(record).eq(
                    "platform", platform
                ).execute()
            else:
                db._client.table("social_accounts").insert(record).execute()
            logger.info("[SocialMedia] Cuenta %s guardada correctamente", platform)
            return True
        except Exception as exc:
            logger.error("[SocialMedia] save_account error: %s", exc)
            return False

    async def list_connected_accounts(self) -> list[dict]:
        """Lista todas las cuentas sociales conectadas."""
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
        """Obtiene el access token de una plataforma conectada."""
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
        """Desactiva una cuenta conectada."""
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
        Publica contenido en la plataforma indicada.
        Si viral_dna está presente, aplica mimetismo viral antes de publicar.
        """
        token = await self.get_account_token(platform)
        if not token:
            return {
                "success": False,
                "error": f"No hay cuenta de {platform} conectada. Usa /conectar {platform}",
            }

        # Aplicar ADN Viral si existe
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
            return {"success": False, "error": f"Plataforma {platform} no soportada"}
        except Exception as exc:
            logger.error("[SocialMedia] post_content error for %s: %s", platform, exc)
            return {"success": False, "error": str(exc)}

    async def _apply_viral_dna(self, content: str, dna: dict) -> str:
        """Reescribe el contenido usando IA para mimetizar formatos virales."""
        from apps.core.tools.ai_client import AIModel, get_ai_client

        prompt = (
            f"Actúa como un experto en viralidad. Reescribe el siguiente contenido siguiendo este ADN viral:\n"
            f"ADN: {json.dumps(dna)}\n\n"
            f"CONTENIDO ORIGINAL: {content}\n\n"
            f"Asegúrate de mantener el valor pero cambiar la estructura, ganchos y CTA para maximizar el engagement."
        )
        resp = await get_ai_client().complete(
            system="Eres un experto en Growth Hacking y Viralidad.",
            user=prompt,
            model=AIModel.STRATEGY,
        )
        return resp.content if resp.success else content

    async def _post_google(self, token: str, content: str, image_url: str | None) -> dict:
        """Simulación de publicación en Google Business Profile (Placeholder para API real)."""
        # Aquí iría la lógica de Google My Business API
        return {"success": True, "platform": "google", "status": "simulated_success"}

    async def _post_facebook(self, token: str, content: str, image_url: str | None) -> dict:
        """Publica en Facebook Pages."""
        # Primero obtenemos las pages del usuario
        pages_res = await self._http.get(
            "https://graph.facebook.com/v19.0/me/accounts",
            params={"access_token": token},
        )
        if pages_res.status_code != 200 or not pages_res.json().get("data"):
            # Publicar en el perfil si no hay pages
            res = await self._http.post(
                "https://graph.facebook.com/v19.0/me/feed",
                params={"access_token": token},
                json={"message": content},
            )
        else:
            # Publicar en la primera page disponible
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
            return {"success": True, "post_id": post_id, "message": "Publicado en Facebook"}
        return {"success": False, "error": res.text[:200]}

    async def _post_instagram(self, token: str, content: str, image_url: str | None) -> dict:
        """Publica en Instagram (requiere imagen para posts normales, sin imagen usa Reels caption)."""
        if not image_url:
            return {
                "success": False,
                "error": "Instagram requiere una imagen para publicar. Usa /publicar instagram [url_imagen] [caption]",
            }

        # Obtener Instagram Business Account ID
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
                "error": "No encontre cuenta de Instagram Business vinculada a tus Pages de Facebook",
            }

        # Crear container de media
        container_res = await self._http.post(
            f"https://graph.facebook.com/v19.0/{ig_account_id}/media",
            params={"access_token": token},
            json={"image_url": image_url, "caption": content},
        )
        if container_res.status_code != 200:
            return {"success": False, "error": container_res.text[:200]}

        container_id = container_res.json().get("id")

        # Publicar el container
        publish_res = await self._http.post(
            f"https://graph.facebook.com/v19.0/{ig_account_id}/media_publish",
            params={"access_token": token},
            json={"creation_id": container_id},
        )
        if publish_res.status_code == 200:
            return {
                "success": True,
                "post_id": publish_res.json().get("id"),
                "message": "Publicado en Instagram",
            }
        return {"success": False, "error": publish_res.text[:200]}

    async def _post_tiktok(self, token: str, content: str) -> dict:
        """Publica en TikTok (solo texto/descripcion — video requiere archivo)."""
        # TikTok requiere video para publicar. Por ahora retornamos instrucciones.
        return {
            "success": False,
            "error": "TikTok requiere un archivo de video para publicar. Esta funcion estara disponible pronto.",
        }

    async def _post_linkedin(self, token: str, content: str, image_url: str | None) -> dict:
        """Publica en LinkedIn."""
        # Obtener el ID del usuario
        me_res = await self._http.get(
            "https://api.linkedin.com/v2/userinfo",
            headers={"Authorization": f"Bearer {token}"},
        )
        if me_res.status_code != 200:
            return {"success": False, "error": "No pude obtener tu perfil de LinkedIn"}

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
            return {"success": True, "post_id": post_id, "message": "Publicado en LinkedIn"}
        return {"success": False, "error": res.text[:200]}
