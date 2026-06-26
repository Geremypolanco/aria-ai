"""
social_tools.py — Distribuye contenido en redes sociales via Buffer.
ARIA publica automaticamente despues de crear cada articulo o producto.
"""

from __future__ import annotations

import logging

import httpx

from apps.core.config import settings

logger = logging.getLogger("aria.social")

BUFFER_API = "https://api.bufferapp.com/1"


class SocialTools:
    """Distribuye contenido en Twitter, LinkedIn, Facebook via Buffer."""

    def __init__(self) -> None:
        self._http = httpx.AsyncClient(timeout=15.0)
        self._token = settings.BUFFER_TOKEN or settings.BUFFER_ACCESS_TOKEN
        self._profiles: list[dict] = []

    async def _get_profiles(self) -> list[dict]:
        """Obtiene los perfiles conectados en Buffer (con cache)."""
        if self._profiles:
            return self._profiles
        if not self._token:
            return []
        try:
            resp = await self._http.get(
                f"{BUFFER_API}/profiles.json",
                params={"access_token": self._token},
            )
            if resp.status_code == 200:
                self._profiles = resp.json() if isinstance(resp.json(), list) else []
                logger.info("[Social] %d perfiles en Buffer", len(self._profiles))
            return self._profiles
        except Exception as exc:
            logger.error("[Social] Error perfiles Buffer: %s", exc)
            return []

    async def post_content(self, text: str, url: str = "", media_url: str = "") -> dict:
        """Publica en todas las redes conectadas via Buffer."""
        if not self._token:
            return {"success": False, "error": "BUFFER_TOKEN no configurado"}

        profiles = await self._get_profiles()
        if not profiles:
            return {"success": False, "error": "No hay perfiles en Buffer o token invalido"}

        profile_ids = [p.get("id") for p in profiles if p.get("id")]
        full_text = f"{text}\n\n{url}".strip() if url else text

        try:
            data: dict = {
                "access_token": self._token,
                "text": full_text[:500],
            }
            for pid in profile_ids:
                data.setdefault("profile_ids[]", pid)

            # Buffer espera array como repeated keys
            form_parts = []
            for pid in profile_ids:
                form_parts.append(("profile_ids[]", pid))
            form_parts.append(("access_token", self._token))
            form_parts.append(("text", full_text[:500]))
            if media_url:
                form_parts.append(("media[link]", media_url))

            resp = await self._http.post(
                f"{BUFFER_API}/updates/create.json",
                data=form_parts,
            )
            result = resp.json()

            if result.get("success") or result.get("updates"):
                logger.info("[Social] Post enviado a %d perfiles Buffer", len(profile_ids))
                return {
                    "success": True,
                    "profiles_posted": len(profile_ids),
                    "preview": full_text[:80],
                }
            return {"success": False, "error": str(result)[:100]}

        except Exception as exc:
            logger.error("[Social] Error posteando: %s", exc)
            return {"success": False, "error": str(exc)}

    def format_article_post(self, title: str, url: str, topic: str = "") -> str:
        """Formatea un post para redes sociales de un articulo publicado."""
        hashtags = ""
        if topic:
            tag = topic.replace(" ", "").replace("-", "")[:20]
            hashtags = f"\n\n#{tag} #NegociosDigitales #IA #IngresosPasivos"
        return f"Nuevo articulo: {title}{hashtags}\n\nLeer: {url}"

    def format_product_post(self, name: str, url: str, price_usd: float) -> str:
        """Formatea un post de lanzamiento de producto digital."""
        return (
            f"Nuevo recurso disponible: {name}\n"
            f"Precio: ${price_usd:.2f}\n"
            f"Descarga aqui: {url}\n\n"
            "#ProductoDigital #IngresosPasivos #IA #Automatizacion"
        )
