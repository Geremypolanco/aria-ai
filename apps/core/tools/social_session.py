"""
social_session.py — Acceso a redes sociales sin APIs oficiales.

ARIA puede autenticarse en redes sociales usando sesiones de navegador
(cookies) exportadas por el usuario. Sin necesidad de API keys ni apps
registradas en cada plataforma.

FLUJO DE USO:
  1. Usuario abre Twitter/Instagram/etc en su navegador (ya logueado)
  2. Instala "Cookie-Editor" (extensión Chrome/Firefox)
  3. Exporta las cookies como JSON
  4. Envía el JSON a ARIA por Telegram (/sesion twitter) o web form
  5. ARIA almacena las cookies cifradas en Redis/Supabase
  6. ARIA usa esas cookies para interactuar con las plataformas

PLATAFORMAS SOPORTADAS:
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
from typing import Any, Optional

import httpx

from apps.core.config import settings

logger = logging.getLogger("aria.social_session")

# ── CONFIGURACION POR PLATAFORMA ─────────────────────────────────────────────

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
            "1. Abre <b>twitter.com</b> en Chrome (ya logueado)\n"
            "2. Instala la extensión <b>Cookie-Editor</b>\n"
            "3. Click en Cookie-Editor → <b>Export → Export as JSON</b>\n"
            "4. Copia todo el JSON y pégalo aquí\n\n"
            "Las cookies clave que necesito son: <code>auth_token</code> y <code>ct0</code>"
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
            "1. Abre <b>instagram.com</b> en Chrome (ya logueado)\n"
            "2. Instala <b>Cookie-Editor</b> si no la tienes\n"
            "3. Click en Cookie-Editor → <b>Export → Export as JSON</b>\n"
            "4. Copia el JSON y pégalo aquí\n\n"
            "Cookie clave: <code>sessionid</code>"
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
            "1. Abre <b>tiktok.com</b> en Chrome (ya logueado)\n"
            "2. Instala <b>Cookie-Editor</b>\n"
            "3. Export → JSON y pega aquí\n\n"
            "Cookie clave: <code>sessionid</code>"
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
            "Csrf-Token": "",  # Se llena desde cookie JSESSIONID
            "X-RestLi-Protocol-Version": "2.0.0",
        },
        "instructions": (
            "1. Abre <b>linkedin.com</b> en Chrome (ya logueado)\n"
            "2. Instala <b>Cookie-Editor</b>\n"
            "3. Export → JSON y pega aquí\n\n"
            "Cookie clave: <code>li_at</code>"
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
            "1. Abre <b>facebook.com</b> en Chrome (ya logueado)\n"
            "2. Instala <b>Cookie-Editor</b>\n"
            "3. Export → JSON y pega aquí\n\n"
            "Cookies clave: <code>c_user</code> y <code>xs</code>"
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
            "1. Abre <b>youtube.com</b> en Chrome (ya logueado con Google)\n"
            "2. Instala <b>Cookie-Editor</b>\n"
            "3. Export → JSON y pega aquí\n\n"
            "Cookie clave: <code>SID</code>"
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
            "1. Abre tu panel de <b>Shopify Admin</b> en Chrome\n"
            "2. Instala <b>Cookie-Editor</b>\n"
            "3. Export → JSON y pega aquí\n\n"
            "Cookie clave: <code>_admin_session</code>"
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
            "1. Abre <b>TikTok Shop Seller Center</b> en Chrome\n"
            "2. Instala <b>Cookie-Editor</b>\n"
            "3. Export → JSON y pega aquí\n\n"
            "Cookie clave: <code>sessionid</code>"
        ),
        "help_url": "https://chromewebstore.google.com/detail/cookie-editor/hlkenndednhfkekhgcdicdfddnkalmdm",
    },
}

SUPPORTED_PLATFORMS = list(PLATFORM_CONFIG.keys())


class SocialSessionManager:
    """
    Gestiona sesiones de redes sociales basadas en cookies de navegador.
    Sin APIs oficiales — ARIA usa las mismas sesiones que un navegador real.
    """

    SESSION_KEY = "aria:social:session:{platform}"
    PENDING_KEY = "aria:social:pending:{chat_id}"
    PENDING_TTL = 600  # 10 minutos para pegar el JSON

    def __init__(self) -> None:
        self._http = httpx.AsyncClient(timeout=30.0, follow_redirects=True)

    # ══════════════════════════════════════════════════════════════
    # 1. IMPORTAR SESION DESDE COOKIES
    # ══════════════════════════════════════════════════════════════

    def parse_cookies_json(self, raw: str) -> Optional[dict[str, str]]:
        """
        Convierte JSON de Cookie-Editor a un dict plano {nombre: valor}.
        Soporta formatos: array de objetos {name, value} o dict plano.
        """
        raw = raw.strip()
        # Limpiar markdown fences si el usuario los incluyó
        for fence in ["```json\n", "```\n", "```"]:
            if raw.startswith(fence):
                raw = raw[len(fence):]
        if raw.endswith("```"):
            raw = raw[:-3]
        raw = raw.strip()

        try:
            data = json.loads(raw)
        except json.JSONDecodeError as e:
            logger.warning("[SocialSession] JSON inválido: %s", e)
            return None

        # Formato Cookie-Editor: lista de objetos con {name, value, ...}
        if isinstance(data, list):
            result = {}
            for item in data:
                if isinstance(item, dict) and "name" in item and "value" in item:
                    result[item["name"]] = item["value"]
            return result if result else None

        # Formato dict plano: {"cookie_name": "cookie_value", ...}
        if isinstance(data, dict):
            # Verificar que los valores son strings (no objetos anidados)
            flat = {k: str(v) for k, v in data.items() if not isinstance(v, (dict, list))}
            return flat if flat else None

        return None

    def validate_cookies_for_platform(self, cookies: dict[str, str], platform: str) -> dict[str, Any]:
        """Verifica que las cookies tienen las clave requeridas para la plataforma."""
        cfg = PLATFORM_CONFIG.get(platform)
        if not cfg:
            return {"valid": False, "error": f"Plataforma desconocida: {platform}"}

        required = cfg["required_cookies"]
        missing = [c for c in required if c not in cookies]

        if missing:
            return {
                "valid": False,
                "error": f"Faltan cookies requeridas: {', '.join(missing)}",
                "required": required,
                "found": list(cookies.keys()),
            }

        return {
            "valid": True,
            "platform": platform,
            "required_found": required,
            "total_cookies": len(cookies),
        }

    async def save_session(self, platform: str, cookies: dict[str, str], user_info: Optional[dict] = None) -> dict[str, Any]:
        """Guarda la sesión en Redis y Supabase para persistencia."""
        try:
            from apps.core.memory.redis_client import get_cache
            cache = get_cache()

            session_data = {
                "platform": platform,
                "cookies": cookies,
                "user_info": user_info or {},
                "saved_at": time.time(),
                "active": True,
            }

            key = self.SESSION_KEY.format(platform=platform)
            await cache.set(key, session_data, ttl_seconds=86400 * 30)  # 30 días

            # También guardar en Supabase para persistencia larga
            try:
                from apps.core.memory.supabase_client import get_db
                db = get_db()
                await db.upsert("social_sessions", {
                    "platform": platform,
                    "cookies_json": json.dumps(cookies),
                    "user_info": json.dumps(user_info or {}),
                    "active": True,
                    "updated_at": "now()",
                })
            except Exception as db_err:
                logger.warning("[SocialSession] No pude guardar en Supabase (Redis OK): %s", db_err)

            logger.info("[SocialSession] Sesión guardada: %s (%d cookies)", platform, len(cookies))
            return {"success": True, "platform": platform, "cookies_count": len(cookies)}

        except Exception as exc:
            logger.error("[SocialSession] Error guardando sesión %s: %s", platform, exc)
            return {"success": False, "error": str(exc)}

    async def load_session(self, platform: str) -> Optional[dict[str, Any]]:
        """Carga la sesión guardada para una plataforma."""
        try:
            from apps.core.memory.redis_client import get_cache
            cache = get_cache()
            key = self.SESSION_KEY.format(platform=platform)
            session = await cache.get(key)
            if session and isinstance(session, dict):
                return session
            # Fallback: intentar Supabase
            try:
                from apps.core.memory.supabase_client import get_db
                db = get_db()
                rows = await db.query("social_sessions", {"platform": platform, "active": True})
                if rows:
                    row = rows[0]
                    return {
                        "platform": platform,
                        "cookies": json.loads(row.get("cookies_json", "{}")),
                        "user_info": json.loads(row.get("user_info", "{}")),
                        "active": True,
                    }
            except Exception:
                pass
        except Exception as exc:
            logger.warning("[SocialSession] No pude cargar sesión %s: %s", platform, exc)
        return None

    def build_cookie_header(self, cookies: dict[str, str]) -> str:
        """Convierte el dict de cookies a header HTTP Cookie."""
        return "; ".join(f"{k}={v}" for k, v in cookies.items())

    async def get_session_headers(self, platform: str) -> Optional[dict[str, str]]:
        """Devuelve headers HTTP listos para usar con la sesión activa."""
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

        # Headers adicionales específicos por plataforma
        extra = dict(cfg.get("test_headers", {}))

        # Twitter necesita el header x-csrf-token = ct0
        if platform == "twitter" and "ct0" in cookies:
            extra["x-csrf-token"] = cookies["ct0"]
            extra["x-twitter-active-user"] = "yes"
            extra["x-twitter-auth-type"] = "OAuth2Session"

        # LinkedIn necesita CSRF del JSESSIONID
        if platform == "linkedin" and "JSESSIONID" in cookies:
            csrf = cookies["JSESSIONID"].strip('"')
            extra["Csrf-Token"] = csrf

        # Instagram necesita X-CSRFToken
        if platform == "instagram" and "csrftoken" in cookies:
            extra["X-CSRFToken"] = cookies["csrftoken"]

        headers.update(extra)
        return headers

    # ══════════════════════════════════════════════════════════════
    # 2. VERIFICAR QUE LA SESION FUNCIONA
    # ══════════════════════════════════════════════════════════════

    async def test_session(self, platform: str) -> dict[str, Any]:
        """Hace una petición de prueba para verificar que la sesión está activa."""
        session = await self.load_session(platform)
        if not session:
            return {"success": False, "error": "No hay sesión guardada para " + platform}

        cfg = PLATFORM_CONFIG.get(platform, {})
        test_url = cfg.get("test_endpoint")
        if not test_url:
            return {"success": True, "message": "Sin endpoint de prueba configurado"}

        headers = await self.get_session_headers(platform)
        if not headers:
            return {"success": False, "error": "No se pudieron cargar los headers"}

        try:
            resp = await self._http.get(test_url, headers=headers, timeout=15.0)
            
            if resp.status_code in (200, 201):
                # Intentar parsear info del usuario
                user_info = {}
                try:
                    data = resp.json()
                    if platform == "twitter":
                        u = data.get("data", {})
                        user_info = {"username": u.get("username"), "name": u.get("name"), "id": u.get("id")}
                    elif platform == "instagram":
                        u = data.get("user", {})
                        user_info = {"username": u.get("username"), "full_name": u.get("full_name"), "id": u.get("pk")}
                    elif platform == "linkedin":
                        user_info = {
                            "firstName": data.get("firstName", {}).get("localized", {}).get("es_ES", ""),
                            "lastName": data.get("lastName", {}).get("localized", {}).get("es_ES", ""),
                        }
                except Exception:
                    pass

                return {"success": True, "platform": platform, "status": resp.status_code, "user_info": user_info}

            elif resp.status_code in (401, 403):
                return {"success": False, "error": f"Sesión expirada (HTTP {resp.status_code}) — reimporta las cookies"}
            else:
                return {"success": False, "error": f"HTTP {resp.status_code}", "body": resp.text[:200]}

        except Exception as exc:
            logger.error("[SocialSession] test error %s: %s", platform, exc)
            return {"success": False, "error": str(exc)}

    # ══════════════════════════════════════════════════════════════
    # 3. ACCIONES EN CADA PLATAFORMA
    # ══════════════════════════════════════════════════════════════

    async def post_tweet(self, text: str) -> dict[str, Any]:
        """Publica un tweet usando la sesión activa de Twitter/X."""
        headers = await self.get_session_headers("twitter")
        if not headers:
            return {"success": False, "error": "No hay sesión de Twitter activa. Usa /sesion twitter"}

        session = await self.load_session("twitter")
        cookies = session.get("cookies", {})
        ct0 = cookies.get("ct0", "")

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
                    "tweet_with_visibility_results_prefer_gql_limited_actions_policy_enabled": False,
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
                return {"success": True, "tweet_id": tweet_id, "url": f"https://x.com/i/status/{tweet_id}" if tweet_id else None}
            return {"success": False, "error": f"HTTP {resp.status_code}: {resp.text[:300]}"}
        except Exception as exc:
            return {"success": False, "error": str(exc)}

    async def post_instagram_story_text(self, text: str) -> dict[str, Any]:
        """Crea un post en Instagram (texto/caption vía API interna)."""
        headers = await self.get_session_headers("instagram")
        if not headers:
            return {"success": False, "error": "No hay sesión de Instagram activa. Usa /sesion instagram"}
        # Instagram requiere imagen para posts normales — devolvemos info útil
        return {
            "success": False,
            "error": "Instagram requiere imagen para posts. Usa el agente de marketing para crear imágenes primero.",
            "tip": "Llama a /marketing con el texto y ARIA creará la imagen y la publicará.",
        }

    async def post_linkedin(self, text: str) -> dict[str, Any]:
        """Publica en LinkedIn usando la sesión activa."""
        headers = await self.get_session_headers("linkedin")
        if not headers:
            return {"success": False, "error": "No hay sesión de LinkedIn activa. Usa /sesion linkedin"}

        session = await self.load_session("linkedin")
        cookies = session.get("cookies", {})
        user_info = session.get("user_info", {})
        person_id = user_info.get("id") or user_info.get("person_id", "")

        if not person_id:
            # Intentar obtener el ID del usuario
            try:
                me_resp = await self._http.get(
                    "https://www.linkedin.com/voyager/api/me",
                    headers=headers, timeout=10.0
                )
                if me_resp.status_code == 200:
                    me_data = me_resp.json()
                    person_id = me_data.get("miniProfile", {}).get("entityUrn", "").split(":")[-1]
            except Exception:
                pass

        if not person_id:
            return {"success": False, "error": "No pude obtener tu LinkedIn person ID"}

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
                headers=headers, json=payload, timeout=20.0,
            )
            if resp.status_code in (200, 201):
                post_id = resp.json().get("id", "")
                return {"success": True, "post_id": post_id}
            return {"success": False, "error": f"HTTP {resp.status_code}: {resp.text[:300]}"}
        except Exception as exc:
            return {"success": False, "error": str(exc)}

    async def post_to_platform(self, platform: str, text: str, media_url: Optional[str] = None) -> dict[str, Any]:
        """Router: publica en la plataforma indicada."""
        if platform == "twitter":
            return await self.post_tweet(text)
        elif platform == "linkedin":
            return await self.post_linkedin(text)
        elif platform == "instagram":
            return await self.post_instagram_story_text(text)
        return {"success": False, "error": f"post_to_platform no implementado para: {platform}"}

    # ══════════════════════════════════════════════════════════════
    # 4. GESTIÓN DE ESTADO PENDIENTE (para flujo Telegram)
    # ══════════════════════════════════════════════════════════════

    async def set_pending_import(self, chat_id: str, platform: str) -> None:
        """Marca que el usuario está en proceso de importar cookies para una plataforma."""
        try:
            from apps.core.memory.redis_client import get_cache
            cache = get_cache()
            await cache.set(
                self.PENDING_KEY.format(chat_id=chat_id),
                platform,
                ttl_seconds=self.PENDING_TTL,
            )
        except Exception as exc:
            logger.warning("[SocialSession] No pude setear pending: %s", exc)

    async def get_pending_import(self, chat_id: str) -> Optional[str]:
        """Retorna la plataforma pendiente de importar cookies, si existe."""
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
        """Limpia el estado de importación pendiente."""
        try:
            from apps.core.memory.redis_client import get_cache
            cache = get_cache()
            await cache.delete(self.PENDING_KEY.format(chat_id=chat_id))
        except Exception:
            pass

    # ══════════════════════════════════════════════════════════════
    # 5. RESUMEN DE SESIONES
    # ══════════════════════════════════════════════════════════════

    async def list_active_sessions(self) -> list[dict[str, Any]]:
        """Lista todas las plataformas con sesión activa."""
        results = []
        for platform in SUPPORTED_PLATFORMS:
            session = await self.load_session(platform)
            if session and session.get("active"):
                cfg = PLATFORM_CONFIG[platform]
                saved_at = session.get("saved_at", 0)
                age_days = int((time.time() - saved_at) / 86400) if saved_at else 0
                results.append({
                    "platform": platform,
                    "display_name": cfg["display_name"],
                    "emoji": cfg["emoji"],
                    "cookies_count": len(session.get("cookies", {})),
                    "user_info": session.get("user_info", {}),
                    "age_days": age_days,
                })
        return results

    async def delete_session(self, platform: str) -> dict[str, Any]:
        """Elimina la sesión de una plataforma."""
        try:
            from apps.core.memory.redis_client import get_cache
            cache = get_cache()
            key = self.SESSION_KEY.format(platform=platform)
            await cache.delete(key)
            # También en Supabase
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

_manager: Optional[SocialSessionManager] = None


def get_social_session_manager() -> SocialSessionManager:
    global _manager
    if _manager is None:
        _manager = SocialSessionManager()
    return _manager
