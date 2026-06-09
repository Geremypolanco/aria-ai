"""
AriaTelegramBot v6 — Sin comandos hardcodeados. Sin lógica de negocio.

Todo input (texto libre O comandos) pasa por AriaMind.
El bot solo se encarga de:
  - recibir mensajes
  - enviar texto, imágenes, videos, audio
  - autorización básica

AriaMind decide qué hacer, qué decir y cuándo callar.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Optional

import httpx

from apps.core.config import settings

logger = logging.getLogger("aria.telegram_bot")

TELEGRAM_API = "https://api.telegram.org/bot"


class AriaTelegramBot:
    """
    Interfaz Telegram de ARIA. Solo I/O. Sin lógica.
    """

    def __init__(self) -> None:
        self._http    = httpx.AsyncClient(timeout=60.0)
        self._offset  = 0
        self._running = False

    # ── WEBHOOK / POLLING ─────────────────────────────────────────────────

    async def set_webhook(self, url: str) -> bool:
        if not settings.telegram_token:
            return False
        try:
            r = await self._http.post(
                f"{TELEGRAM_API}{settings.telegram_token}/setWebhook",
                json={"url": url, "drop_pending_updates": True},
            )
            return r.status_code == 200 and r.json().get("ok", False)
        except Exception as exc:
            logger.error("[Bot] set_webhook: %s", exc)
            return False

    async def handle_update(self, update: dict[str, Any]) -> None:
        """Punto de entrada del webhook de FastAPI."""
        msg = update.get("message")
        if msg:
            await self._handle_message(msg)

    async def start_polling(self) -> None:
        if not settings.telegram_token:
            logger.error("[Bot] TELEGRAM_TOKEN no configurado — bot inactivo")
            return
        self._running = True
        logger.info("[Bot] Polling iniciado")
        while self._running:
            try:
                await self._poll()
            except Exception as exc:
                logger.error("[Bot] Error polling: %s", exc)
                await asyncio.sleep(5)
            await asyncio.sleep(1)

    async def _poll(self) -> None:
        url = f"{TELEGRAM_API}{settings.telegram_token}/getUpdates"
        r = await self._http.get(url,
            params={"timeout": 10, "offset": self._offset, "allowed_updates": ["message"]},
            timeout=15.0)
        if r.status_code != 200:
            return
        data = r.json()
        if not data.get("ok"):
            return
        for upd in data.get("result", []):
            self._offset = upd["update_id"] + 1
            msg = upd.get("message")
            if msg:
                asyncio.create_task(self._handle_message(msg))

    # ── PROCESAMIENTO ─────────────────────────────────────────────────────

    async def _handle_message(self, msg: dict[str, Any]) -> None:
        chat_id = str(msg["chat"]["id"])
        text    = msg.get("text", "").strip()

        if not text:
            return

        if not self._is_authorized(chat_id):
            return

        # Todo pasa por AriaMind — sin excepciones
        try:
            from apps.core.cognition.aria_mind import get_aria_mind
            mind     = get_aria_mind()
            response = await mind.handle(text, chat_id)
        except Exception as exc:
            logger.error("[Bot] AriaMind error: %s", exc)
            await self._send(chat_id, "Algo falló internamente. Inténtalo de nuevo.")
            return

        if response.silent or (not response.text and not response.image_bytes
                                and not response.video_bytes and not response.audio_bytes):
            return

        # Enviar media primero si existe
        if response.image_bytes:
            ok = await self._send_photo_bytes(chat_id, response.image_bytes, response.caption)
            if not ok and response.caption:
                await self._send(chat_id, response.caption)
            return

        if response.video_bytes:
            ok = await self._send_video_bytes(chat_id, response.video_bytes, response.caption)
            if not ok and response.caption:
                await self._send(chat_id, f"Video generado pero demasiado grande para Telegram. {response.caption}")
            return

        if response.audio_bytes:
            ok = await self._send_audio_bytes(chat_id, response.audio_bytes, response.caption)
            if not ok and response.caption:
                await self._send(chat_id, response.caption)
            return

        if response.text:
            await self._send(chat_id, response.text)

    def _is_authorized(self, chat_id: str) -> bool:
        allowed = str(getattr(settings, "TELEGRAM_CHAT_ID", "") or "").strip()
        return not allowed or str(chat_id).strip() == allowed

    # ── ENVÍO DE TEXTO ────────────────────────────────────────────────────

    async def _send(self, chat_id: str, text: str) -> bool:
        if not settings.telegram_token or not text:
            return False
        # Telegram límite: 4096 chars
        for chunk in [text[i:i+4000] for i in range(0, len(text), 4000)]:
            try:
                r = await self._http.post(
                    f"{TELEGRAM_API}{settings.telegram_token}/sendMessage",
                    json={"chat_id": chat_id, "text": chunk,
                          "parse_mode": "HTML",
                          "disable_web_page_preview": True},
                )
                if r.status_code != 200:
                    logger.warning("[Bot] sendMessage %d: %s", r.status_code, r.text[:100])
            except Exception as exc:
                logger.error("[Bot] _send: %s", exc)
        return True

    # ── ENVÍO DE MEDIA ────────────────────────────────────────────────────

    async def _send_photo_bytes(self, chat_id: str, image_bytes: bytes,
                                 caption: str = None, filename: str = "aria.png") -> bool:
        if not settings.telegram_token or not image_bytes:
            return False
        try:
            d = {"chat_id": chat_id}
            if caption:
                d["caption"] = caption[:1024]
                d["parse_mode"] = "HTML"
            r = await self._http.post(
                f"{TELEGRAM_API}{settings.telegram_token}/sendPhoto",
                data=d,
                files={"photo": (filename, image_bytes, "image/png")},
            )
            if r.status_code != 200:
                logger.error("[Bot] sendPhoto %d: %s", r.status_code, r.text[:150])
            return r.status_code == 200
        except Exception as exc:
            logger.error("[Bot] _send_photo_bytes: %s", exc)
            return False

    async def _send_video_bytes(self, chat_id: str, video_bytes: bytes,
                                 caption: str = None, filename: str = "aria.mp4") -> bool:
        if not settings.telegram_token or not video_bytes:
            return False
        try:
            d = {"chat_id": chat_id}
            if caption:
                d["caption"] = caption[:1024]
                d["parse_mode"] = "HTML"
            r = await self._http.post(
                f"{TELEGRAM_API}{settings.telegram_token}/sendVideo",
                data=d,
                files={"video": (filename, video_bytes, "video/mp4")},
            )
            return r.status_code == 200
        except Exception as exc:
            logger.error("[Bot] _send_video_bytes: %s", exc)
            return False

    async def _send_audio_bytes(self, chat_id: str, audio_bytes: bytes,
                                 caption: str = None, filename: str = "aria.wav") -> bool:
        if not settings.telegram_token or not audio_bytes:
            return False
        try:
            d = {"chat_id": chat_id}
            if caption:
                d["caption"] = caption[:1024]
                d["parse_mode"] = "HTML"
            r = await self._http.post(
                f"{TELEGRAM_API}{settings.telegram_token}/sendAudio",
                data=d,
                files={"audio": (filename, audio_bytes, "audio/wav")},
            )
            return r.status_code == 200
        except Exception as exc:
            logger.error("[Bot] _send_audio_bytes: %s", exc)
            return False

    # ── NOTIFICACIÓN PROACTIVA ────────────────────────────────────────────

    async def notify_owner(self, message: str) -> bool:
        """
        ARIA decide proactivamente notificar al dueño.
        Solo para cosas realmente importantes. No spam.
        """
        chat_id = str(getattr(settings, "TELEGRAM_CHAT_ID", "") or "")
        if not chat_id:
            return False
        return await self._send(chat_id, message)

    async def close(self) -> None:
        self._running = False
        await self._http.aclose()


# ─── SINGLETON ────────────────────────────────────────────────────────────

_bot: Optional[AriaTelegramBot] = None

def get_bot() -> AriaTelegramBot:
    global _bot
    if _bot is None:
        _bot = AriaTelegramBot()
    return _bot
