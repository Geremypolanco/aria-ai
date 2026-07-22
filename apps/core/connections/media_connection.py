"""
Media connection para ARIA AI.
Soporta Spotify (OAuth), YouTube (Google OAuth), TikTok (OAuth), Twitch (OAuth).
"""

from __future__ import annotations

import logging
from urllib.parse import urlencode

import httpx

from apps.core.connections.base import BaseConnector
from apps.core.connections.registry import register_connector

logger = logging.getLogger("aria.connections.media")

# ── Spotify ────────────────────────────────────────────────────────────────────
SPOTIFY_AUTH_URL = "https://accounts.spotify.com/authorize"
SPOTIFY_TOKEN_URL = "https://accounts.spotify.com/api/token"
SPOTIFY_API = "https://api.spotify.com/v1"
SPOTIFY_REDIRECT = "https://aria-ai.fly.dev/oauth/callback/spotify"
SPOTIFY_SCOPES = "user-read-playback-state user-modify-playback-state user-read-currently-playing playlist-read-private user-library-read user-top-read"

# ── YouTube (Google OAuth) ─────────────────────────────────────────────────────
YOUTUBE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
YOUTUBE_TOKEN_URL = "https://oauth2.googleapis.com/token"
YOUTUBE_API = "https://www.googleapis.com/youtube/v3"
YOUTUBE_REDIRECT = "https://aria-ai.fly.dev/oauth/callback/youtube"
YOUTUBE_SCOPES = "https://www.googleapis.com/auth/youtube.readonly"

# ── TikTok ─────────────────────────────────────────────────────────────────────
TIKTOK_AUTH_URL = "https://www.tiktok.com/v2/auth/authorize"
TIKTOK_TOKEN_URL = "https://open.tiktokapis.com/v2/oauth/token/"
TIKTOK_API = "https://open.tiktokapis.com/v2"
TIKTOK_REDIRECT = "https://aria-ai.fly.dev/oauth/callback/tiktok"
TIKTOK_SCOPES = "user.info.basic video.list"

# ── Twitch ──────────────────────────────────────────────────────────────────────
TWITCH_AUTH_URL = "https://id.twitch.tv/oauth2/authorize"
TWITCH_TOKEN_URL = "https://id.twitch.tv/oauth2/token"
TWITCH_API = "https://api.twitch.tv/helix"
TWITCH_REDIRECT = "https://aria-ai.fly.dev/oauth/callback/twitch"
TWITCH_SCOPES = (
    "user:read:email channel:read:stream_key moderator:read:followers channel:read:subscriptions"
)


@register_connector("spotify", display_name="Spotify (música, playlists)")
class SpotifyConnection(BaseConnector):

    def _client_id(self) -> str | None:
        from apps.core.config import settings

        return getattr(settings, "SPOTIFY_CLIENT_ID", None)

    def _client_secret(self) -> str | None:
        from apps.core.config import settings

        return getattr(settings, "SPOTIFY_CLIENT_SECRET", None)

    def get_auth_url(self, chat_id: str) -> str | None:
        cid = self._client_id()
        if not cid:
            return None
        params = {
            "client_id": cid,
            "response_type": "code",
            "redirect_uri": SPOTIFY_REDIRECT,
            "scope": SPOTIFY_SCOPES,
            "state": chat_id,
        }
        return f"{SPOTIFY_AUTH_URL}?{urlencode(params)}"

    async def exchange_code(self, code: str, chat_id: str) -> dict | None:
        cid = self._client_id()
        sec = self._client_secret()
        if not cid or not sec:
            raise ValueError("SPOTIFY_CLIENT_ID / SPOTIFY_CLIENT_SECRET no configurados")
        import base64

        creds = base64.b64encode(f"{cid}:{sec}".encode()).decode()
        async with httpx.AsyncClient(timeout=15.0) as http:
            r = await http.post(
                SPOTIFY_TOKEN_URL,
                data={
                    "grant_type": "authorization_code",
                    "code": code,
                    "redirect_uri": SPOTIFY_REDIRECT,
                },
                headers={"Authorization": f"Basic {creds}"},
            )
            r.raise_for_status()
            data = r.json()
            return {
                "access_token": data["access_token"],
                "refresh_token": data.get("refresh_token"),
                "service_user": "spotify_user",
            }

    def _h(self, tokens: dict) -> dict:
        return {"Authorization": f"Bearer {tokens['access_token']}"}

    async def get_current_track(self, tokens: dict) -> dict:
        async with httpx.AsyncClient(timeout=15.0) as http:
            r = await http.get(
                f"{SPOTIFY_API}/me/player/currently-playing", headers=self._h(tokens)
            )
            if r.status_code == 204:
                return {"playing": False}
            r.raise_for_status()
            item = r.json().get("item", {})
            return {
                "playing": r.json().get("is_playing"),
                "track": item.get("name"),
                "artist": ", ".join(a["name"] for a in item.get("artists", [])),
                "album": item.get("album", {}).get("name"),
                "progress_ms": r.json().get("progress_ms"),
                "duration_ms": item.get("duration_ms"),
            }

    async def get_top_tracks(
        self, tokens: dict, time_range: str = "medium_term", limit: int = 10
    ) -> list[dict]:
        async with httpx.AsyncClient(timeout=15.0) as http:
            r = await http.get(
                f"{SPOTIFY_API}/me/top/tracks",
                headers=self._h(tokens),
                params={"time_range": time_range, "limit": limit},
            )
            r.raise_for_status()
            return [
                {
                    "name": t.get("name"),
                    "artist": ", ".join(a["name"] for a in t.get("artists", [])),
                    "album": t.get("album", {}).get("name"),
                    "popularity": t.get("popularity"),
                }
                for t in r.json().get("items", [])
            ]

    async def list_playlists(self, tokens: dict, limit: int = 20) -> list[dict]:
        async with httpx.AsyncClient(timeout=15.0) as http:
            r = await http.get(
                f"{SPOTIFY_API}/me/playlists",
                headers=self._h(tokens),
                params={"limit": limit},
            )
            r.raise_for_status()
            return [
                {
                    "id": p.get("id"),
                    "name": p.get("name"),
                    "tracks": p.get("tracks", {}).get("total", 0),
                    "public": p.get("public"),
                }
                for p in r.json().get("items", [])
            ]

    async def search(self, tokens: dict, query: str, type: str = "track", limit: int = 10) -> dict:
        async with httpx.AsyncClient(timeout=15.0) as http:
            r = await http.get(
                f"{SPOTIFY_API}/search",
                headers=self._h(tokens),
                params={"q": query, "type": type, "limit": limit},
            )
            r.raise_for_status()
            return r.json()


@register_connector("youtube", display_name="YouTube (videos, canal)")
class YouTubeConnection(BaseConnector):

    def _client_id(self) -> str | None:
        from apps.core.config import settings

        return getattr(settings, "GOOGLE_CLIENT_ID", None)

    def _client_secret(self) -> str | None:
        from apps.core.config import settings

        return getattr(settings, "GOOGLE_CLIENT_SECRET", None)

    def get_auth_url(self, chat_id: str) -> str | None:
        cid = self._client_id()
        if not cid:
            return None
        params = {
            "client_id": cid,
            "redirect_uri": YOUTUBE_REDIRECT,
            "response_type": "code",
            "scope": YOUTUBE_SCOPES,
            "access_type": "offline",
            "state": chat_id,
        }
        return f"{YOUTUBE_AUTH_URL}?{urlencode(params)}"

    async def exchange_code(self, code: str, chat_id: str) -> dict | None:
        cid = self._client_id()
        sec = self._client_secret()
        if not cid or not sec:
            raise ValueError("GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET no configurados")
        async with httpx.AsyncClient(timeout=15.0) as http:
            r = await http.post(
                YOUTUBE_TOKEN_URL,
                data={
                    "code": code,
                    "client_id": cid,
                    "client_secret": sec,
                    "redirect_uri": YOUTUBE_REDIRECT,
                    "grant_type": "authorization_code",
                },
            )
            r.raise_for_status()
            data = r.json()
            return {
                "access_token": data["access_token"],
                "refresh_token": data.get("refresh_token"),
                "service_user": "youtube_user",
            }

    def _h(self, tokens: dict) -> dict:
        return {"Authorization": f"Bearer {tokens['access_token']}"}

    async def get_channel(self, tokens: dict) -> dict:
        async with httpx.AsyncClient(timeout=15.0) as http:
            r = await http.get(
                f"{YOUTUBE_API}/channels",
                headers=self._h(tokens),
                params={"part": "snippet,statistics", "mine": True},
            )
            r.raise_for_status()
            items = r.json().get("items", [{}])
            if not items:
                return {}
            c = items[0]
            return {
                "id": c.get("id"),
                "title": c.get("snippet", {}).get("title"),
                "subscribers": c.get("statistics", {}).get("subscriberCount"),
                "views": c.get("statistics", {}).get("viewCount"),
                "videos": c.get("statistics", {}).get("videoCount"),
            }

    async def list_videos(self, tokens: dict, limit: int = 10) -> list[dict]:
        channel = await self.get_channel(tokens)
        channel_id = channel.get("id")
        if not channel_id:
            return []
        async with httpx.AsyncClient(timeout=15.0) as http:
            r = await http.get(
                f"{YOUTUBE_API}/search",
                headers=self._h(tokens),
                params={
                    "part": "snippet",
                    "channelId": channel_id,
                    "maxResults": limit,
                    "order": "date",
                    "type": "video",
                },
            )
            r.raise_for_status()
            return [
                {
                    "id": item.get("id", {}).get("videoId"),
                    "title": item.get("snippet", {}).get("title"),
                    "published": item.get("snippet", {}).get("publishedAt"),
                    "thumbnail": item.get("snippet", {})
                    .get("thumbnails", {})
                    .get("default", {})
                    .get("url"),
                }
                for item in r.json().get("items", [])
            ]

    async def search_videos(self, tokens: dict, query: str, limit: int = 10) -> list[dict]:
        async with httpx.AsyncClient(timeout=15.0) as http:
            r = await http.get(
                f"{YOUTUBE_API}/search",
                headers=self._h(tokens),
                params={"part": "snippet", "q": query, "maxResults": limit, "type": "video"},
            )
            r.raise_for_status()
            return [
                {
                    "id": item.get("id", {}).get("videoId"),
                    "title": item.get("snippet", {}).get("title"),
                    "channel": item.get("snippet", {}).get("channelTitle"),
                    "published": item.get("snippet", {}).get("publishedAt"),
                }
                for item in r.json().get("items", [])
            ]


@register_connector("tiktok", display_name="TikTok (videos, cuenta)")
class TikTokConnection(BaseConnector):

    def _client_id(self) -> str | None:
        from apps.core.config import settings

        return getattr(settings, "TIKTOK_CLIENT_KEY", None)

    def _client_secret(self) -> str | None:
        from apps.core.config import settings

        return getattr(settings, "TIKTOK_CLIENT_SECRET", None)

    def get_auth_url(self, chat_id: str) -> str | None:
        cid = self._client_id()
        if not cid:
            return None
        import secrets

        state = f"{chat_id}_{secrets.token_hex(8)}"
        params = {
            "client_key": cid,
            "scope": TIKTOK_SCOPES,
            "response_type": "code",
            "redirect_uri": TIKTOK_REDIRECT,
            "state": state,
        }
        return f"{TIKTOK_AUTH_URL}?{urlencode(params)}"

    async def exchange_code(self, code: str, chat_id: str) -> dict | None:
        cid = self._client_id()
        sec = self._client_secret()
        if not cid or not sec:
            raise ValueError("TIKTOK_CLIENT_KEY / TIKTOK_CLIENT_SECRET no configurados")
        async with httpx.AsyncClient(timeout=15.0) as http:
            r = await http.post(
                TIKTOK_TOKEN_URL,
                data={
                    "client_key": cid,
                    "client_secret": sec,
                    "code": code,
                    "grant_type": "authorization_code",
                    "redirect_uri": TIKTOK_REDIRECT,
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
            r.raise_for_status()
            data = r.json().get("data", {})
            return {
                "access_token": data.get("access_token"),
                "refresh_token": data.get("refresh_token"),
                "open_id": data.get("open_id"),
                "service_user": data.get("open_id", "tiktok_user"),
            }

    def _h(self, tokens: dict) -> dict:
        return {"Authorization": f"Bearer {tokens['access_token']}"}

    async def get_user_info(self, tokens: dict) -> dict:
        async with httpx.AsyncClient(timeout=15.0) as http:
            r = await http.post(
                f"{TIKTOK_API}/user/info/",
                headers={**self._h(tokens), "Content-Type": "application/json"},
                json={
                    "fields": [
                        "open_id",
                        "union_id",
                        "avatar_url",
                        "display_name",
                        "follower_count",
                        "following_count",
                        "video_count",
                    ]
                },
            )
            r.raise_for_status()
            return r.json().get("data", {}).get("user", {})

    async def list_videos(self, tokens: dict, max_count: int = 20) -> list[dict]:
        async with httpx.AsyncClient(timeout=15.0) as http:
            r = await http.post(
                f"{TIKTOK_API}/video/list/",
                headers={**self._h(tokens), "Content-Type": "application/json"},
                params={
                    "fields": "id,title,create_time,cover_image_url,share_url,view_count,like_count,comment_count"
                },
                json={"max_count": max_count},
            )
            r.raise_for_status()
            return r.json().get("data", {}).get("videos", [])


@register_connector("twitch", display_name="Twitch (streams, canal)")
class TwitchConnection(BaseConnector):

    def _client_id(self) -> str | None:
        from apps.core.config import settings

        return getattr(settings, "TWITCH_CLIENT_ID", None)

    def _client_secret(self) -> str | None:
        from apps.core.config import settings

        return getattr(settings, "TWITCH_CLIENT_SECRET", None)

    def get_auth_url(self, chat_id: str) -> str | None:
        cid = self._client_id()
        if not cid:
            return None
        params = {
            "client_id": cid,
            "redirect_uri": TWITCH_REDIRECT,
            "response_type": "code",
            "scope": TWITCH_SCOPES,
            "state": chat_id,
        }
        return f"{TWITCH_AUTH_URL}?{urlencode(params)}"

    async def exchange_code(self, code: str, chat_id: str) -> dict | None:
        cid = self._client_id()
        sec = self._client_secret()
        if not cid or not sec:
            raise ValueError("TWITCH_CLIENT_ID / TWITCH_CLIENT_SECRET no configurados")
        async with httpx.AsyncClient(timeout=15.0) as http:
            r = await http.post(
                TWITCH_TOKEN_URL,
                data={
                    "client_id": cid,
                    "client_secret": sec,
                    "code": code,
                    "grant_type": "authorization_code",
                    "redirect_uri": TWITCH_REDIRECT,
                },
            )
            r.raise_for_status()
            data = r.json()
            return {
                "access_token": data["access_token"],
                "refresh_token": data.get("refresh_token"),
                "service_user": "twitch_user",
            }

    def _h(self, tokens: dict) -> dict:
        cid = self._client_id() or ""
        return {"Authorization": f"Bearer {tokens['access_token']}", "Client-Id": cid}

    async def get_user(self, tokens: dict) -> dict:
        async with httpx.AsyncClient(timeout=15.0) as http:
            r = await http.get(f"{TWITCH_API}/users", headers=self._h(tokens))
            r.raise_for_status()
            users = r.json().get("data", [{}])
            return users[0] if users else {}

    async def get_streams(self, tokens: dict, user_login: str = "") -> list[dict]:
        params = {}
        if user_login:
            params["user_login"] = user_login
        async with httpx.AsyncClient(timeout=15.0) as http:
            r = await http.get(f"{TWITCH_API}/streams", headers=self._h(tokens), params=params)
            r.raise_for_status()
            return [
                {
                    "id": s.get("id"),
                    "user_name": s.get("user_name"),
                    "game_name": s.get("game_name"),
                    "title": s.get("title"),
                    "viewer_count": s.get("viewer_count"),
                    "started_at": s.get("started_at"),
                }
                for s in r.json().get("data", [])
            ]

    async def get_channel_info(self, tokens: dict, broadcaster_id: str) -> dict:
        async with httpx.AsyncClient(timeout=15.0) as http:
            r = await http.get(
                f"{TWITCH_API}/channels",
                headers=self._h(tokens),
                params={"broadcaster_id": broadcaster_id},
            )
            r.raise_for_status()
            items = r.json().get("data", [{}])
            return items[0] if items else {}

    async def get_followers(self, tokens: dict, broadcaster_id: str) -> dict:
        async with httpx.AsyncClient(timeout=15.0) as http:
            r = await http.get(
                f"{TWITCH_API}/channels/followers",
                headers=self._h(tokens),
                params={"broadcaster_id": broadcaster_id},
            )
            r.raise_for_status()
            return {"total": r.json().get("total"), "data": r.json().get("data", [])}
