"""
ARIA Social Engine — Generación y distribución de contenido en redes sociales.

Capacidades:
  1. Generación de contenido optimizado por plataforma (AI-powered)
  2. Publicación en Twitter/X, Reddit, Pinterest, Discord, y OAuth (FB/IG/LI/TT)

Plataformas de generación: Instagram, LinkedIn, Twitter/X, TikTok, Facebook, YouTube
Plataformas de publicación: Twitter/X (API v2), Reddit, Pinterest (API v5), Discord (webhook)
"""

from __future__ import annotations

import base64
import logging
from typing import Any

import httpx

from apps.core.config import settings

logger = logging.getLogger("aria.social_content")


class SocialContentTools:

    def __init__(self) -> None:
        self._http = httpx.AsyncClient(timeout=30.0)

    async def post_to_all(self, text: str, article_url: str = "", title: str = "") -> dict:
        """Publica en todas las redes disponibles en paralelo."""
        import asyncio

        results = await asyncio.gather(
            self.post_twitter(text[:280]),
            self.post_reddit(title, text, article_url),
            self.post_pinterest(title, text, article_url),
            self.post_discord_webhook(title, text, article_url),
            self.post_via_oauth_accounts(text, article_url),
            return_exceptions=True,
        )
        platforms = ["twitter", "reddit", "pinterest", "discord", "oauth_accounts"]
        final = {}
        for i, r in enumerate(results):
            if isinstance(r, dict):
                final[platforms[i]] = r
            elif isinstance(r, Exception):
                final[platforms[i]] = {"success": False, "error": str(r)[:100]}
        return final

    # ── TWITTER / X ───────────────────────────────────────

    async def post_twitter(self, text: str) -> dict:
        """
        Publica tweet via Twitter API v2.
        Requiere: TWITTER_BEARER_TOKEN, TWITTER_API_KEY, TWITTER_API_SECRET,
                  TWITTER_ACCESS_TOKEN, TWITTER_ACCESS_TOKEN_SECRET
        Tier gratuito: 1,500 tweets/mes.
        """
        if not all(
            [
                settings.TWITTER_API_KEY,
                settings.TWITTER_API_SECRET,
                settings.TWITTER_ACCESS_TOKEN,
                settings.TWITTER_ACCESS_TOKEN_SECRET,
            ]
        ):
            return {
                "success": False,
                "skipped": True,
                "reason": "Twitter credentials no configuradas",
            }
        try:
            import hashlib
            import hmac
            import secrets as secrets_lib
            import time
            import urllib.parse

            method = "POST"
            url = "https://api.twitter.com/2/tweets"
            oauth_nonce = secrets_lib.token_hex(16)
            oauth_timestamp = str(int(time.time()))

            oauth_params = {
                "oauth_consumer_key": settings.TWITTER_API_KEY,
                "oauth_nonce": oauth_nonce,
                "oauth_signature_method": "HMAC-SHA1",
                "oauth_timestamp": oauth_timestamp,
                "oauth_token": settings.TWITTER_ACCESS_TOKEN,
                "oauth_version": "1.0",
            }

            param_str = "&".join(
                f"{urllib.parse.quote(k, safe='')}={urllib.parse.quote(v, safe='')}"
                for k, v in sorted(oauth_params.items())
            )
            base_str = f"{method}&{urllib.parse.quote(url, safe='')}&{urllib.parse.quote(param_str, safe='')}"
            signing_key = f"{urllib.parse.quote(settings.TWITTER_API_SECRET, safe='')}&{urllib.parse.quote(settings.TWITTER_ACCESS_TOKEN_SECRET, safe='')}"
            signature = base64.b64encode(
                hmac.new(signing_key.encode(), base_str.encode(), hashlib.sha1).digest()
            ).decode()
            oauth_params["oauth_signature"] = signature

            auth_header = "OAuth " + ", ".join(
                f'{k}="{urllib.parse.quote(v, safe="")}"' for k, v in sorted(oauth_params.items())
            )

            res = await self._http.post(
                url,
                headers={"Authorization": auth_header, "Content-Type": "application/json"},
                json={"text": text[:280]},
            )

            if res.status_code in (200, 201):
                data = res.json().get("data", {})
                tweet_id = data.get("id", "")
                tweet_url = f"https://twitter.com/i/web/status/{tweet_id}"
                logger.info("[Social] Twitter: %s", tweet_url)
                return {"success": True, "platform": "twitter", "url": tweet_url, "id": tweet_id}
            return {"success": False, "error": res.text[:200]}

        except Exception as exc:
            logger.error("[Social] Twitter error: %s", exc)
            return {"success": False, "error": str(exc)}

    # ── REDDIT ────────────────────────────────────────────

    async def post_reddit(self, title: str, text: str, url: str = "") -> dict:
        """
        Publica en Reddit via API oficial.
        Requiere: REDDIT_CLIENT_ID, REDDIT_CLIENT_SECRET, REDDIT_USERNAME, REDDIT_PASSWORD
        Tier gratuito: generoso.
        Subreddits target: r/artificial, r/entrepreneur, etc.
        """
        if not all(
            [
                settings.REDDIT_CLIENT_ID,
                settings.REDDIT_CLIENT_SECRET,
                settings.REDDIT_USERNAME,
                settings.REDDIT_PASSWORD,
            ]
        ):
            return {
                "success": False,
                "skipped": True,
                "reason": "Reddit credentials no configuradas",
            }

        try:
            # Obtener access token
            token_res = await self._http.post(
                "https://www.reddit.com/api/v1/access_token",
                auth=(settings.REDDIT_CLIENT_ID, settings.REDDIT_CLIENT_SECRET),
                data={
                    "grant_type": "password",
                    "username": settings.REDDIT_USERNAME,
                    "password": settings.REDDIT_PASSWORD,
                },
                headers={"User-Agent": "ARIA/1.0"},
            )
            if token_res.status_code != 200:
                return {"success": False, "error": "Reddit auth failed"}

            access_token = token_res.json().get("access_token")
            headers = {"Authorization": f"bearer {access_token}", "User-Agent": "ARIA/1.0"}

            # Determinar subreddit basado en el contenido
            subreddit = settings.REDDIT_TARGET_SUBREDDIT or "test"

            payload = {
                "sr": subreddit,
                "kind": "link" if url else "self",
                "title": title[:300],
                "resubmit": True,
                "nsfw": False,
                "spoiler": False,
            }
            if url:
                payload["url"] = url
            else:
                payload["text"] = text[:10000]

            post_res = await self._http.post(
                "https://oauth.reddit.com/api/submit",
                headers=headers,
                data=payload,
            )

            if post_res.status_code == 200:
                data = post_res.json().get("jquery", [])
                post_url = ""
                for item in data:
                    if isinstance(item, list):
                        for sub in item:
                            if isinstance(sub, list) and any(
                                "reddit.com/r/" in str(s) for s in sub
                            ):
                                post_url = next(
                                    (s for s in sub if isinstance(s, str) and "reddit.com/r/" in s),
                                    "",
                                )
                                break
                logger.info("[Social] Reddit posted: %s", post_url)
                return {"success": True, "platform": "reddit", "url": post_url}
            return {"success": False, "error": post_res.text[:200]}

        except Exception as exc:
            logger.error("[Social] Reddit error: %s", exc)
            return {"success": False, "error": str(exc)}

    # ── PINTEREST ─────────────────────────────────────────

    async def post_pinterest(self, title: str, description: str, link: str = "") -> dict:
        """
        Crea pin en Pinterest via API v5.
        Requiere: PINTEREST_ACCESS_TOKEN (OAuth 2.0)
        Tier gratuito: generoso.
        """
        if not settings.PINTEREST_ACCESS_TOKEN:
            return {
                "success": False,
                "skipped": True,
                "reason": "PINTEREST_ACCESS_TOKEN no configurado",
            }

        try:
            board_id = settings.PINTEREST_BOARD_ID or ""
            if not board_id:
                # Obtener primer board disponible
                boards_res = await self._http.get(
                    "https://api.pinterest.com/v5/boards",
                    headers={"Authorization": f"Bearer {settings.PINTEREST_ACCESS_TOKEN}"},
                )
                if boards_res.status_code == 200:
                    boards = boards_res.json().get("items", [])
                    board_id = boards[0]["id"] if boards else ""

            if not board_id:
                return {"success": False, "error": "No Pinterest board encontrado"}

            pin_payload: dict[str, Any] = {
                "board_id": board_id,
                "title": title[:100],
                "description": description[:500],
                "link": link,
                "media_source": {
                    "source_type": "image_url",
                    "url": settings.PINTEREST_DEFAULT_IMAGE_URL
                    or "https://via.placeholder.com/1000x1500",
                },
            }

            res = await self._http.post(
                "https://api.pinterest.com/v5/pins",
                headers={
                    "Authorization": f"Bearer {settings.PINTEREST_ACCESS_TOKEN}",
                    "Content-Type": "application/json",
                },
                json=pin_payload,
            )

            if res.status_code in (200, 201):
                data = res.json()
                pin_url = f"https://pinterest.com/pin/{data.get('id', '')}"
                logger.info("[Social] Pinterest: %s", pin_url)
                return {"success": True, "platform": "pinterest", "url": pin_url}
            return {"success": False, "error": res.text[:200]}

        except Exception as exc:
            logger.error("[Social] Pinterest error: %s", exc)
            return {"success": False, "error": str(exc)}

    # ── DISCORD WEBHOOK ───────────────────────────────────

    async def post_discord_webhook(self, title: str, content: str, url: str = "") -> dict:
        """
        Publica en Discord via Webhook.
        Requiere: DISCORD_WEBHOOK_URL (crear en Server Settings → Integrations)
        Completamente gratuito.
        """
        if not settings.DISCORD_WEBHOOK_URL:
            return {
                "success": False,
                "skipped": True,
                "reason": "DISCORD_WEBHOOK_URL no configurado",
            }

        try:
            summary = content[:300] + "..." if len(content) > 300 else content
            embed = {
                "title": title[:256],
                "description": summary,
                "color": 5814783,  # Azul ARIA
            }
            if url:
                embed["url"] = url
                embed["fields"] = [
                    {
                        "name": "Leer artículo completo",
                        "value": f"[Click aquí]({url})",
                        "inline": False,
                    }
                ]

            payload = {
                "username": "ARIA Content Bot",
                "avatar_url": "https://i.imgur.com/AfFp7pu.png",
                "embeds": [embed],
            }

            res = await self._http.post(settings.DISCORD_WEBHOOK_URL, json=payload)
            if res.status_code in (200, 204):
                return {"success": True, "platform": "discord"}
            return {"success": False, "error": res.text[:200]}

        except Exception as exc:
            logger.error("[Social] Discord webhook error: %s", exc)
            return {"success": False, "error": str(exc)}

    # ── CUENTAS OAUTH CONECTADAS ──────────────────────────

    async def post_via_oauth_accounts(self, text: str, url: str = "") -> dict:
        """Publica en todas las cuentas conectadas via OAuth (Facebook, Instagram, LinkedIn, TikTok)."""
        try:
            from apps.core.tools.social_media import SocialMediaManager

            sm = SocialMediaManager()
            accounts = await sm.list_connected_accounts()
            if not accounts:
                return {"success": False, "skipped": True, "reason": "Sin cuentas OAuth conectadas"}

            results = {}
            content = f"{text}\n{url}" if url else text

            for account in accounts:
                platform = account["platform"]
                try:
                    r = await sm.post_content(platform, content[:2000])
                    results[platform] = r
                except Exception as exc:
                    results[platform] = {"success": False, "error": str(exc)}

            success_count = sum(1 for r in results.values() if r.get("success"))
            return {"success": success_count > 0, "platforms": results, "published": success_count}

        except Exception as exc:
            logger.error("[Social] OAuth accounts error: %s", exc)
            return {"success": False, "error": str(exc)}


# ═══════════════════════════════════════════════════════════════════════════
# AI CONTENT GENERATION ENGINE
# ═══════════════════════════════════════════════════════════════════════════

_PLATFORM_SPECS = {
    "instagram": {
        "max_chars": 2200,
        "hashtags": "10-15",
        "tone": "visual, inspirational, emojis",
        "format": "Hook + story/value + CTA + hashtags. Suggest image description too.",
    },
    "linkedin": {
        "max_chars": 1300,
        "hashtags": "3-5",
        "tone": "professional, thought leadership",
        "format": "Hook line + 3-5 short paragraphs + key insight + CTA + hashtags. No emojis.",
    },
    "twitter": {
        "max_chars": 280,
        "hashtags": "2-3",
        "tone": "punchy, conversational",
        "format": "Single powerful statement or question. Hashtags at end.",
    },
    "tiktok": {
        "max_chars": 2200,
        "hashtags": "3-5",
        "tone": "Gen-Z, trending, authentic",
        "format": "HOOK (first 3 seconds script) + video script outline + CTA + hashtags + trending audio suggestion.",
    },
    "facebook": {
        "max_chars": 500,
        "hashtags": "2-3",
        "tone": "friendly, community",
        "format": "Conversational opener + value + question to engage + CTA.",
    },
    "youtube": {
        "max_chars": 5000,
        "hashtags": "10 tags",
        "tone": "SEO-optimized, engaging",
        "format": "Title (60 chars) + Description (first 150 chars critical for SEO) + full description + timestamps + tags + thumbnail text (6 words).",
    },
}


class SocialContentEngine:
    """AI-powered social media content generator for ARIA."""

    async def create_post(
        self,
        topic: str,
        platform: str,
        tone: str = "professional",
        include_hashtags: bool = True,
    ) -> dict[str, Any]:
        """Generate platform-optimized post content using AI."""
        platform = platform.lower()
        spec = _PLATFORM_SPECS.get(platform, _PLATFORM_SPECS["instagram"])

        try:
            from apps.core.tools.ai_client import AIModel, get_ai_client

            ai = get_ai_client()

            system = (
                f"You are an expert {platform} content creator. "
                f"Write {spec['tone']} content. Max {spec['max_chars']} chars. "
                f"Include {spec['hashtags']} hashtags if appropriate. "
                f"Format: {spec['format']}"
            )
            user = f"Create a {platform} post about: {topic}. Tone: {tone}."

            resp = await ai.complete(
                system=system,
                user=user,
                model=AIModel.STRATEGY,
                max_tokens=800,
                temperature=0.7,
                agent_name="social_content",
            )
            if resp and resp.success:
                return {
                    "success": True,
                    "platform": platform,
                    "content": resp.content.strip(),
                    "char_count": len(resp.content),
                    "topic": topic,
                }
            return {"success": False, "error": "AI content generation failed"}
        except Exception as exc:
            logger.error("[SocialContent] create_post error: %s", exc)
            return {"success": False, "error": str(exc)}

    async def create_content_pack(
        self,
        topic: str,
        platforms: list[str] | None = None,
        tone: str = "professional",
    ) -> dict[str, Any]:
        """Generate content for all requested platforms simultaneously."""
        import asyncio

        if not platforms:
            platforms = ["instagram", "linkedin", "twitter", "facebook"]

        tasks = [self.create_post(topic, p, tone) for p in platforms]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        pack: dict[str, Any] = {"success": True, "topic": topic, "platforms": {}}
        for platform, result in zip(platforms, results, strict=False):
            if isinstance(result, dict):
                pack["platforms"][platform] = result
            else:
                pack["platforms"][platform] = {"success": False, "error": str(result)}

        pack["generated"] = sum(1 for r in pack["platforms"].values() if r.get("success"))
        return pack

    async def create_viral_hook(self, topic: str) -> dict[str, Any]:
        """Generate 5 viral hook variations for any topic."""
        try:
            from apps.core.tools.ai_client import AIModel, get_ai_client

            ai = get_ai_client()
            resp = await ai.complete(
                system=(
                    "You are a viral content expert. Generate 5 distinct hook variations "
                    "for social media. Each hook must be under 15 words and create curiosity or "
                    "emotional response. Format as numbered list."
                ),
                user=f"Topic: {topic}",
                model=AIModel.STRATEGY,
                max_tokens=400,
                temperature=0.9,
                agent_name="viral_hook",
            )
            if resp and resp.success:
                return {"success": True, "hooks": resp.content.strip(), "topic": topic}
            return {"success": False, "error": "Hook generation failed"}
        except Exception as exc:
            return {"success": False, "error": str(exc)}

    async def create_and_post(
        self,
        topic: str,
        platforms: list[str],
        tone: str = "professional",
    ) -> dict[str, Any]:
        """Generate content AND post it to all platforms in one call."""
        pack = await self.create_content_pack(topic, platforms, tone)
        poster = SocialContentTools()
        results: dict[str, Any] = {"generation": pack, "posting": {}}

        for platform, content_result in pack.get("platforms", {}).items():
            if not content_result.get("success"):
                results["posting"][platform] = {
                    "skipped": True,
                    "reason": "content generation failed",
                }
                continue
            text = content_result.get("content", "")
            try:
                if platform == "twitter":
                    post_r = await poster.post_twitter(text[:280])
                elif platform == "discord":
                    post_r = await poster.post_discord_webhook(topic, text)
                elif platform == "reddit":
                    post_r = await poster.post_reddit(topic, text)
                else:
                    post_r = await poster.post_via_oauth_accounts(text)
                results["posting"][platform] = post_r
            except Exception as exc:
                results["posting"][platform] = {"success": False, "error": str(exc)}

        return results
