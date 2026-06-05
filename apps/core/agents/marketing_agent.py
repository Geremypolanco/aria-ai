"""
MarketingAgent — Crea y distribuye contenido de marketing multicanal.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

import httpx

from apps.core.agents.base_agent import BaseAgent
from apps.core.config import settings
from apps.core.tools.ai_client import AIModel

logger = logging.getLogger("aria.marketing_agent")


class MarketingAgent(BaseAgent):
    def __init__(self) -> None:
        super().__init__(
            name="marketing_agent",
            description="Marketing — contenido multicanal y distribución",
            capabilities=["content_creation", "social_media", "email_campaigns", "image_generation"],
        )

    async def _execute(self, context: dict[str, Any]) -> dict[str, Any]:
        market_focus = context.get("market_focus", "digital products")
        language = context.get("primary_language", "en")

        content_pack = await self.create_content_pack(market_focus, language)
        if not content_pack:
            return {"success": False, "error": "No se pudo generar el content pack"}

        results: dict[str, Any] = {
            "success": True,
            "agent": "marketing_agent",
            "content_pack": content_pack,
        }

        # Publicar en redes sociales
        if settings.BUFFER_TOKEN:
            social_result = await self.publish_social(content_pack)
            results["social"] = social_result

        # Campaña de email
        if settings.MAILCHIMP_API_KEY:
            email_result = await self.create_email_campaign(content_pack, market_focus)
            results["email"] = email_result

        return results

    async def create_content_pack(
        self, niche: str, language: str
    ) -> Optional[dict[str, Any]]:
        """Genera un paquete completo de contenido para todas las plataformas."""
        pack = await self.think(
            system=(
                "Eres un experto en marketing de contenidos y copywriting de alta conversión. "
                "Creas contenido que genera clics, engagement y ventas reales."
            ),
            user=(
                f"Nicho: {niche} | Idioma: {language}\n\n"
                "Crea un content pack completo. JSON:\n"
                "{\n"
                '  "topic": "...",\n'
                '  "hook": "gancho viral de 10 palabras",\n'
                '  "twitter": "tweet de 280 chars con hashtags",\n'
                '  "instagram_caption": "caption con emojis y hashtags",\n'
                '  "linkedin_post": "post profesional de 150 palabras",\n'
                '  "blog_title": "título SEO-optimizado",\n'
                '  "blog_intro": "intro de 100 palabras",\n'
                '  "email_subject": "asunto de email de alta apertura",\n'
                '  "email_body": "cuerpo del email de 200 palabras",\n'
                '  "image_prompt": "prompt para generar imagen con FLUX.1"\n'
                "}"
            ),
            model=AIModel.CREATIVE,
            json_mode=True,
        )
        if pack:
            pack["niche"] = niche
            pack["language"] = language
            # Generar imagen si hay HF_TOKEN
            if settings.HF_TOKEN and pack.get("image_prompt"):
                image_url = await self.generate_image(pack["image_prompt"])
                pack["generated_image_url"] = image_url
            logger.info("[MarketingAgent] Content pack creado para: %s", niche)
        return pack

    async def publish_social(self, content_pack: dict[str, Any]) -> dict[str, Any]:
        """Publica contenido en redes sociales via Buffer API."""
        results = []
        profiles = await self._get_buffer_profiles()

        for profile in profiles[:3]:  # max 3 perfiles
            platform = profile.get("service", "")
            content = ""
            if "twitter" in platform.lower():
                content = content_pack.get("twitter", "")
            elif "instagram" in platform.lower():
                content = content_pack.get("instagram_caption", "")
            elif "linkedin" in platform.lower():
                content = content_pack.get("linkedin_post", "")

            if not content:
                continue

            try:
                async with httpx.AsyncClient(timeout=15.0) as client:
                    res = await client.post(
                        "https://api.bufferapp.com/1/updates/create.json",
                        data={
                            "access_token": settings.BUFFER_TOKEN,
                            "profile_ids[]": profile.get("id"),
                            "text": content[:500],
                            "scheduled_at": "",
                            "now": "true",
                        },
                    )
                    results.append({
                        "platform": platform,
                        "success": res.status_code in (200, 201),
                        "status": res.status_code,
                    })
            except Exception as exc:
                results.append({"platform": platform, "success": False, "error": str(exc)})

        logger.info("[MarketingAgent] Social published: %d plataformas", len(results))
        return {"success": True, "results": results}

    async def create_email_campaign(
        self, content_pack: dict[str, Any], niche: str
    ) -> dict[str, Any]:
        """Crea y envía una campaña de email via Mailchimp."""
        if not settings.MAILCHIMP_API_KEY or not settings.MAILCHIMP_DC:
            return {"success": False, "error": "Mailchimp no configurado"}
        try:
            base_url = f"https://{settings.MAILCHIMP_DC}.api.mailchimp.com/3.0"
            headers = {"Authorization": f"Bearer {settings.MAILCHIMP_API_KEY}"}

            async with httpx.AsyncClient(timeout=15.0) as client:
                # Obtener lista de audiencia
                lists_res = await client.get(f"{base_url}/lists", headers=headers)
                if lists_res.status_code != 200:
                    return {"success": False, "error": "No se pudo obtener lista Mailchimp"}
                lists = lists_res.json().get("lists", [])
                if not lists:
                    return {"success": False, "error": "Sin listas de audiencia en Mailchimp"}
                list_id = lists[0]["id"]

                # Crear campaña
                campaign_res = await client.post(
                    f"{base_url}/campaigns",
                    headers=headers,
                    json={
                        "type": "regular",
                        "recipients": {"list_id": list_id},
                        "settings": {
                            "subject_line": content_pack.get("email_subject", f"Novedad: {niche}"),
                            "from_name": "Aria AI",
                            "reply_to": "noreply@aria-ai.com",
                        },
                    },
                )
                if campaign_res.status_code != 200:
                    return {"success": False, "error": f"Mailchimp campaign HTTP {campaign_res.status_code}"}
                campaign_id = campaign_res.json()["id"]

                # Agregar contenido
                email_html = f"<html><body><p>{content_pack.get('email_body', '')}</p></body></html>"
                await client.put(
                    f"{base_url}/campaigns/{campaign_id}/content",
                    headers=headers,
                    json={"html": email_html},
                )

                # Enviar
                send_res = await client.post(f"{base_url}/campaigns/{campaign_id}/actions/send", headers=headers)
                success = send_res.status_code == 204
                logger.info("[MarketingAgent] Email campaign enviada: %s", campaign_id)
                return {"success": success, "campaign_id": campaign_id}
        except Exception as exc:
            logger.error("[MarketingAgent] Error en email campaign: %s", exc)
            return {"success": False, "error": str(exc)}

    async def generate_image(self, prompt: str) -> Optional[str]:
        """Genera imagen con FLUX.1 via HuggingFace."""
        if not settings.HF_TOKEN:
            return None
        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                res = await client.post(
                    "https://api-inference.huggingface.co/models/black-forest-labs/FLUX.1-schnell",
                    headers={"Authorization": f"Bearer {settings.HF_TOKEN}"},
                    json={"inputs": prompt},
                )
                if res.status_code == 200 and res.headers.get("content-type", "").startswith("image"):
                    logger.info("[MarketingAgent] Imagen generada con FLUX.1")
                    return f"data:image/jpeg;base64,{__import__('base64').b64encode(res.content).decode()}"
        except Exception as exc:
            logger.warning("[MarketingAgent] Error generando imagen: %s", exc)
        return None

    async def generate_audio(self, text: str, voice_id: str = "21m00Tcm4TlvDq8ikWAM") -> Optional[str]:
        """Genera audio con ElevenLabs."""
        if not settings.ELEVENLABS_API_KEY:
            return None
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                res = await client.post(
                    f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}",
                    headers={
                        "xi-api-key": settings.ELEVENLABS_API_KEY,
                        "Content-Type": "application/json",
                    },
                    json={
                        "text": text[:2500],
                        "model_id": "eleven_multilingual_v2",
                        "voice_settings": {"stability": 0.5, "similarity_boost": 0.75},
                    },
                )
                if res.status_code == 200:
                    logger.info("[MarketingAgent] Audio generado con ElevenLabs")
                    return f"audio_bytes:{len(res.content)}"
        except Exception as exc:
            logger.warning("[MarketingAgent] Error generando audio: %s", exc)
        return None

    async def _get_buffer_profiles(self) -> list[dict[str, Any]]:
        if not settings.BUFFER_TOKEN:
            return []
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                res = await client.get(
                    "https://api.bufferapp.com/1/profiles.json",
                    params={"access_token": settings.BUFFER_TOKEN},
                )
                if res.status_code == 200:
                    return res.json() if isinstance(res.json(), list) else []
        except Exception:
            pass
        return []
