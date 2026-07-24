"""
ARIA Social Content Tools — Content distribution on social networks.

Platforms:
- Twitter/X (API v2 — free tier)
- Reddit (API — free tier)
- Pinterest (API — free)
- Discord (webhooks — free)
- LinkedIn (already in social_media.py for OAuth)
- All networks connected via social_media.py OAuth
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
        """Publishes to all available networks in parallel."""
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
        Posts a tweet via Twitter API v2.
        Requires: TWITTER_BEARER_TOKEN, TWITTER_API_KEY, TWITTER_API_SECRET,
                  TWITTER_ACCESS_TOKEN, TWITTER_ACCESS_TOKEN_SECRET
        Free tier: 1,500 tweets/month.
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
                "reason": "Twitter credentials not configured",
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
        Posts to Reddit via the official API.
        Requires: REDDIT_CLIENT_ID, REDDIT_CLIENT_SECRET, REDDIT_USERNAME, REDDIT_PASSWORD
        Free tier: generous.
        Target subreddits: r/artificial, r/entrepreneur, etc.
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
                "reason": "Reddit credentials not configured",
            }

        try:
            # Get access token
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

            # Determine subreddit based on content
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
        Creates a pin on Pinterest via API v5.
        Requires: PINTEREST_ACCESS_TOKEN (OAuth 2.0)
        Free tier: generous.
        """
        if not settings.PINTEREST_ACCESS_TOKEN:
            return {
                "success": False,
                "skipped": True,
                "reason": "PINTEREST_ACCESS_TOKEN not configured",
            }

        try:
            board_id = settings.PINTEREST_BOARD_ID or ""
            if not board_id:
                # Get the first available board
                boards_res = await self._http.get(
                    "https://api.pinterest.com/v5/boards",
                    headers={"Authorization": f"Bearer {settings.PINTEREST_ACCESS_TOKEN}"},
                )
                if boards_res.status_code == 200:
                    boards = boards_res.json().get("items", [])
                    board_id = boards[0]["id"] if boards else ""

            if not board_id:
                return {"success": False, "error": "No Pinterest board found"}

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
        Posts to Discord via Webhook.
        Requires: DISCORD_WEBHOOK_URL (create in Server Settings → Integrations)
        Completely free.
        """
        if not settings.DISCORD_WEBHOOK_URL:
            return {
                "success": False,
                "skipped": True,
                "reason": "DISCORD_WEBHOOK_URL not configured",
            }

        try:
            summary = content[:300] + "..." if len(content) > 300 else content
            embed = {
                "title": title[:256],
                "description": summary,
                "color": 5814783,  # ARIA Blue
            }
            if url:
                embed["url"] = url
                embed["fields"] = [
                    {
                        "name": "Read the full article",
                        "value": f"[Click here]({url})",
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

    # ── CONNECTED OAUTH ACCOUNTS ──────────────────────────

    async def post_via_oauth_accounts(self, text: str, url: str = "") -> dict:
        """Posts to all accounts connected via OAuth (Facebook, Instagram, LinkedIn, TikTok)."""
        try:
            from apps.core.tools.social_media import SocialMediaManager

            sm = SocialMediaManager()
            accounts = await sm.list_connected_accounts()
            if not accounts:
                return {"success": False, "skipped": True, "reason": "No OAuth accounts connected"}

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
