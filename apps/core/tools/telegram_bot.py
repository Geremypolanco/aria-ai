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

    async def _download_file(self, file_id: str) -> Optional[bytes]:
        """Descarga un archivo de Telegram dado su file_id."""
        try:
            r = await self._http.get(
                f"{TELEGRAM_API}{settings.telegram_token}/getFile",
                params={"file_id": file_id},
            )
            if r.status_code != 200:
                return None
            file_path = r.json().get("result", {}).get("file_path", "")
            if not file_path:
                return None
            dl = await self._http.get(
                f"https://api.telegram.org/file/bot{settings.telegram_token}/{file_path}",
                timeout=60.0,
            )
            return dl.content if dl.status_code == 200 else None
        except Exception as exc:
            logger.error("[Bot] _download_file %s: %s", file_id, exc)
            return None

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
            params={"timeout": 10, "offset": self._offset,
                    "allowed_updates": '["message"]'},
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

        if not self._is_authorized(chat_id):
            return

        # Determinar tipo de mensaje y construir texto para AriaMind
        text = msg.get("text", "").strip()

        # Foto enviada por el usuario → describir con BLIP-2
        if not text and msg.get("photo"):
            text = await self._describe_user_photo(msg, chat_id)
            if not text:
                return

        # Voz o audio enviado por el usuario → transcribir con Whisper
        if not text and (msg.get("voice") or msg.get("audio")):
            text = await self._transcribe_user_audio(msg, chat_id)
            if not text:
                return

        if not text:
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

        if response.silent or (
            not response.text and not response.image_bytes
            and not response.video_bytes and not response.audio_bytes
            and not response.document_bytes
        ):
            return

        # Enviar media según tipo
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

        if response.document_bytes:
            fname = response.document_filename or "documento.pdf"
            ok = await self._send_document_bytes(chat_id, response.document_bytes, fname, response.caption)
            if not ok and response.caption:
                await self._send(chat_id, response.caption)
            # Also send any explanatory text
            if response.text:
                await self._send(chat_id, response.text)
            return

        if response.text:
            await self._send(chat_id, response.text)

    async def _describe_user_photo(self, msg: dict[str, Any], chat_id: str) -> str:
        """Descarga foto del usuario, la describe con BLIP-2 y devuelve texto para AriaMind."""
        try:
            photos = msg["photo"]
            # Usar la foto de mayor resolución (último elemento)
            file_id = photos[-1]["file_id"]
            caption = msg.get("caption", "").strip()

            img_bytes = await self._download_file(file_id)
            if not img_bytes:
                await self._send(chat_id, "No pude descargar la imagen.")
                return ""

            from apps.core.tools.huggingface_suite import HuggingFaceSuite
            r = await HuggingFaceSuite().describe_image(image_bytes=img_bytes)
            description = r.get("description", "") if r.get("success") else ""

            if description:
                base = f"[El usuario envió una foto. Descripción: {description}]"
            else:
                base = "[El usuario envió una foto que no pude describir.]"

            return f"{base} {caption}".strip() if caption else base
        except Exception as exc:
            logger.error("[Bot] _describe_user_photo: %s", exc)
            return ""

    async def _transcribe_user_audio(self, msg: dict[str, Any], chat_id: str) -> str:
        """Descarga audio/voz del usuario, transcribe con Whisper y devuelve texto para AriaMind."""
        try:
            voice = msg.get("voice") or msg.get("audio") or {}
            file_id = voice.get("file_id", "")
            if not file_id:
                return ""

            audio_bytes = await self._download_file(file_id)
            if not audio_bytes:
                await self._send(chat_id, "No pude descargar el audio.")
                return ""

            from apps.core.tools.huggingface_suite import HuggingFaceSuite
            r = await HuggingFaceSuite().transcribe(audio_bytes)
            transcript = r.get("transcript", "").strip() if r.get("success") else ""

            if transcript:
                return f"[Mensaje de voz transcrito]: {transcript}"
            await self._send(chat_id, "No pude transcribir el audio.")
            return ""
        except Exception as exc:
            logger.error("[Bot] _transcribe_user_audio: %s", exc)
            return ""

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

    async def _send_document_bytes(self, chat_id: str, doc_bytes: bytes,
                                    filename: str = "documento.pdf",
                                    caption: str = None) -> bool:
        if not settings.telegram_token or not doc_bytes:
            return False
        try:
            d = {"chat_id": chat_id}
            if caption:
                d["caption"] = caption[:1024]
                d["parse_mode"] = "HTML"
            mime = "application/pdf" if filename.endswith(".pdf") else "application/octet-stream"
            r = await self._http.post(
                f"{TELEGRAM_API}{settings.telegram_token}/sendDocument",
                data=d,
                files={"document": (filename, doc_bytes, mime)},
            )
            if r.status_code != 200:
                logger.error("[Bot] sendDocument %d: %s", r.status_code, r.text[:150])
            return r.status_code == 200
        except Exception as exc:
            logger.error("[Bot] _send_document_bytes: %s", exc)
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
