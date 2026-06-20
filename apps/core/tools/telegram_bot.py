"""
AriaTelegramBot v8 — Conversational Intelligence Edition.

ARIA no es un menú. Es una IA que razona, actúa y sigue el hilo.

Principios:
  ✦ Sin teclados de botones — ARIA entiende lenguaje natural
  ✦ Sin traducciones de slash commands — AriaMind maneja todo
  ✦ Bienvenida proactiva: ARIA reporta qué ha estado haciendo
  ✦ Contexto de conversación real — recordatorio de acciones previas
  ✦ Typing indicator + placeholder para sensación de respuesta en vivo
  ✦ Markdown → HTML seguro para Telegram

Todo input pasa por AriaMind. El bot solo maneja I/O.
"""
from __future__ import annotations

import asyncio
import html
import logging
import re
from typing import Any, Optional

import httpx

from apps.core.config import settings

logger = logging.getLogger("aria.telegram_bot")

TELEGRAM_API = "https://api.telegram.org/bot"

# No keyboards — ARIA is conversational, not a menu app.

# ── Bot commands (minimal — ARIA understands natural language) ─────────────

BOT_COMMANDS = [
    {"command": "start",   "description": "Activar ARIA y ver qué ha estado haciendo"},
    {"command": "limpiar", "description": "Borrar el historial de conversación"},
]

# ── Welcome handled dynamically by _send_welcome (proactive status report) ─


class AriaTelegramBot:
    """Interfaz Telegram de ARIA — I/O de clase mundial."""

    def __init__(self) -> None:
        self._http    = httpx.AsyncClient(timeout=60.0)
        self._offset  = 0
        self._running = False
        self._commands_registered = False

    # ── Setup ──────────────────────────────────────────────────────────────

    async def _register_commands(self) -> None:
        if self._commands_registered or not settings.telegram_token:
            return
        try:
            r = await self._http.post(
                f"{TELEGRAM_API}{settings.telegram_token}/setMyCommands",
                json={"commands": BOT_COMMANDS},
            )
            if r.status_code == 200 and r.json().get("ok"):
                self._commands_registered = True
                logger.info("[Bot] Commands registered")
        except Exception as exc:
            logger.warning("[Bot] setMyCommands failed: %s", exc)

    async def set_webhook(self, url: str) -> bool:
        if not settings.telegram_token:
            return False
        await self._register_commands()
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
        """Entry point for FastAPI webhook."""
        if update.get("message"):
            await self._handle_message(update["message"])
        elif update.get("callback_query"):
            await self._handle_callback(update["callback_query"])

    # ── Webhook / Polling ──────────────────────────────────────────────────

    async def start_polling(self) -> None:
        if not settings.telegram_token:
            logger.error("[Bot] TELEGRAM_TOKEN no configurado — bot inactivo")
            return
        await self._register_commands()
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
        r = await self._http.get(
            url,
            params={"timeout": 10, "offset": self._offset,
                    "allowed_updates": '["message","callback_query"]'},
            timeout=15.0,
        )
        if r.status_code != 200:
            return
        data = r.json()
        if not data.get("ok"):
            return
        for upd in data.get("result", []):
            self._offset = upd["update_id"] + 1
            if upd.get("message"):
                asyncio.create_task(self._handle_message(upd["message"]))
            elif upd.get("callback_query"):
                asyncio.create_task(self._handle_callback(upd["callback_query"]))

    # ── File downloads ─────────────────────────────────────────────────────

    async def _download_file(self, file_id: str) -> Optional[bytes]:
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

    # ── Message handling ───────────────────────────────────────────────────

    async def _handle_message(self, msg: dict[str, Any]) -> None:
        chat_id = str(msg["chat"]["id"])

        if not self._is_authorized(chat_id):
            return

        text = msg.get("text", "").strip()

        # Photo → describe with BLIP-2
        if not text and msg.get("photo"):
            text = await self._describe_user_photo(msg, chat_id)
            if not text:
                return

        # Voice/audio → transcribe with Whisper
        if not text and (msg.get("voice") or msg.get("audio")):
            text = await self._transcribe_user_audio(msg, chat_id)
            if not text:
                return

        if not text:
            return

        # /start — special welcome
        if text == "/start":
            await self._send_welcome(chat_id)
            return

        # Typing indicator immediately
        await self._send_action(chat_id, "typing")

        # Send placeholder "thinking" message
        placeholder_id = await self._send_placeholder(chat_id)

        # /limpiar resets conversation history
        if text.strip().lower() in ("/limpiar", "/clear", "/reset", "limpiar"):
            try:
                from apps.core.cognition.aria_mind import get_aria_mind
                mind = get_aria_mind()
                await mind._clear_history(chat_id)
            except Exception:
                pass
            await self._edit_or_send(chat_id, placeholder_id, "🗑 Historial borrado. ¿En qué trabajamos ahora?")
            return

        # Everything through AriaMind — no pre-programmed shortcuts
        try:
            from apps.core.cognition.aria_mind import get_aria_mind
            mind     = get_aria_mind()
            response = await mind.handle(text, chat_id)
        except Exception as exc:
            logger.error("[Bot] AriaMind error: %s", exc)
            await self._edit_or_send(chat_id, placeholder_id,
                                     "⚠️ Algo falló internamente. Inténtalo de nuevo.")
            return

        if response.silent or (
            not response.text and not response.image_bytes
            and not response.video_bytes and not response.audio_bytes
            and not response.document_bytes
        ):
            if placeholder_id:
                await self._delete_message(chat_id, placeholder_id)
            return

        # Delete placeholder before sending media
        if response.image_bytes or response.video_bytes or response.audio_bytes or response.document_bytes:
            if placeholder_id:
                await self._delete_message(chat_id, placeholder_id)

        if response.image_bytes:
            ok = await self._send_photo_bytes(chat_id, response.image_bytes, response.caption)
            if not ok and response.caption:
                await self._send(chat_id, response.caption)
            return

        if response.video_bytes:
            ok = await self._send_video_bytes(chat_id, response.video_bytes, response.caption)
            if not ok and response.caption:
                await self._send(chat_id, f"🎬 Video generado — demasiado grande para Telegram.\n{response.caption}")
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
            if response.text:
                await self._send(chat_id, response.text)
            return

        if response.text:
            await self._edit_or_send(chat_id, placeholder_id, response.text)

    async def _handle_callback(self, cbq: dict[str, Any]) -> None:
        """Acknowledge any residual callback queries gracefully."""
        cb_id = cbq.get("id", "")
        await self._answer_callback(cb_id)

    # ── Media input processing ─────────────────────────────────────────────

    async def _describe_user_photo(self, msg: dict[str, Any], chat_id: str) -> str:
        try:
            photos  = msg["photo"]
            file_id = photos[-1]["file_id"]
            caption = msg.get("caption", "").strip()

            img_bytes = await self._download_file(file_id)
            if not img_bytes:
                await self._send(chat_id, "⚠️ No pude descargar la imagen.")
                return ""

            from apps.core.tools.huggingface_suite import HuggingFaceSuite
            r = await HuggingFaceSuite().describe_image(image_bytes=img_bytes)
            description = r.get("description", "") if r.get("success") else ""

            base = (f"[El usuario envió una foto. Descripción: {description}]"
                    if description else "[El usuario envió una foto que no pude describir.]")
            return f"{base} {caption}".strip() if caption else base
        except Exception as exc:
            logger.error("[Bot] _describe_user_photo: %s", exc)
            return ""

    async def _transcribe_user_audio(self, msg: dict[str, Any], chat_id: str) -> str:
        try:
            voice   = msg.get("voice") or msg.get("audio") or {}
            file_id = voice.get("file_id", "")
            if not file_id:
                return ""

            audio_bytes = await self._download_file(file_id)
            if not audio_bytes:
                await self._send(chat_id, "⚠️ No pude descargar el audio.")
                return ""

            from apps.core.tools.huggingface_suite import HuggingFaceSuite
            r = await HuggingFaceSuite().transcribe(audio_bytes)
            transcript = r.get("transcript", "").strip() if r.get("success") else ""

            if transcript:
                return f"[Mensaje de voz transcrito]: {transcript}"
            await self._send(chat_id, "⚠️ No pude transcribir el audio.")
            return ""
        except Exception as exc:
            logger.error("[Bot] _transcribe_user_audio: %s", exc)
            return ""

    # ── Auth ───────────────────────────────────────────────────────────────

    def _is_authorized(self, chat_id: str) -> bool:
        allowed = str(getattr(settings, "TELEGRAM_CHAT_ID", "") or "").strip()
        return not allowed or str(chat_id).strip() == allowed

    # ── Markdown → HTML conversion ─────────────────────────────────────────

    @staticmethod
    def _md_to_html(text: str) -> str:
        """
        Convert Markdown-flavored text to Telegram HTML (safe subset).
        Handles: **bold**, *italic*, `code`, ```code blocks```, headers, lists.
        """
        if not text:
            return text

        # 1. Extract code blocks before HTML-escaping
        code_blocks: list[str] = []

        def save_code_block(m: re.Match) -> str:
            lang  = m.group(1) or ""
            code  = m.group(2)
            safe  = html.escape(code)
            label = f"<i>[{lang}]</i>\n" if lang else ""
            block = f"{label}<pre><code>{safe}</code></pre>"
            code_blocks.append(block)
            return f"\x00CB{len(code_blocks)-1}\x00"

        text = re.sub(r"```(\w*)\n?([\s\S]*?)```", save_code_block, text)

        # 2. HTML-escape the rest
        text = html.escape(text)

        # 3. Restore code blocks
        for i, block in enumerate(code_blocks):
            text = text.replace(f"\x00CB{i}\x00", block)

        # 4. Inline code
        text = re.sub(r"`([^`]+)`", lambda m: f"<code>{html.escape(m.group(1))}</code>", text)

        # 5. Bold **text** or __text__
        text = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", text)
        text = re.sub(r"__(.+?)__",     r"<b>\1</b>", text)

        # 6. Italic *text* or _text_ (not inside words)
        text = re.sub(r"(?<!\w)\*(?!\s)(.+?)(?<!\s)\*(?!\w)", r"<i>\1</i>", text)
        text = re.sub(r"(?<!\w)_(?!\s)(.+?)(?<!\s)_(?!\w)",   r"<i>\1</i>", text)

        # 7. Strikethrough ~~text~~
        text = re.sub(r"~~(.+?)~~", r"<s>\1</s>", text)

        # 8. Headers → bold line
        text = re.sub(r"^#{1,4}\s+(.+)$", r"<b>\1</b>", text, flags=re.MULTILINE)

        # 9. Horizontal rules → line
        text = re.sub(r"^[-*_]{3,}\s*$", "─────────────────", text, flags=re.MULTILINE)

        return text

    # ── Sending helpers ────────────────────────────────────────────────────

    async def _send_welcome(self, chat_id: str) -> None:
        """Proactive welcome: ARIA reports what she's been doing, not a menu."""
        if not settings.telegram_token:
            return
        try:
            # Delegate the whole welcome to AriaMind so she can reason and report
            from apps.core.cognition.aria_mind import get_aria_mind
            mind = get_aria_mind()
            response = await mind.handle(
                "Hola, acabo de conectarme. Dame un reporte rápido de qué has estado haciendo "
                "mientras estaba desconectado: ciclos de ingresos ejecutados, productos creados, "
                "URLs publicadas, y qué planeas hacer ahora.",
                chat_id,
            )
            text = response.text or "ARIA en línea. ¿Qué hacemos?"
            await self._send(chat_id, self._md_to_html(text), already_html=True)
        except Exception as exc:
            logger.error("[Bot] _send_welcome: %s", exc)
            await self._send(chat_id, "ARIA en línea. Habla conmigo en lenguaje natural.")

    async def _send_action(self, chat_id: str, action: str = "typing") -> None:
        if not settings.telegram_token:
            return
        try:
            await self._http.post(
                f"{TELEGRAM_API}{settings.telegram_token}/sendChatAction",
                json={"chat_id": chat_id, "action": action},
                timeout=5.0,
            )
        except Exception:
            pass

    async def _send_placeholder(self, chat_id: str) -> Optional[int]:
        """Send a subtle 'thinking' placeholder; returns message_id."""
        if not settings.telegram_token:
            return None
        try:
            r = await self._http.post(
                f"{TELEGRAM_API}{settings.telegram_token}/sendMessage",
                json={
                    "chat_id": chat_id,
                    "text": "⏳",
                    "parse_mode": "HTML",
                },
            )
            if r.status_code == 200 and r.json().get("ok"):
                return r.json()["result"]["message_id"]
        except Exception as exc:
            logger.warning("[Bot] _send_placeholder: %s", exc)
        return None

    async def _edit_or_send(self, chat_id: str, message_id: Optional[int],
                             text: str) -> None:
        """Edit placeholder if available; otherwise send new message."""
        html_text = self._md_to_html(text)

        if message_id:
            ok = await self._edit_message(chat_id, message_id, html_text)
            if ok:
                return
            # If edit fails (message too old, etc.), delete and send fresh
            await self._delete_message(chat_id, message_id)

        await self._send(chat_id, html_text, already_html=True)

    async def _edit_message(self, chat_id: str, message_id: int, html_text: str) -> bool:
        if not settings.telegram_token:
            return False
        # Chunk if needed — edit only supports single message
        chunk = html_text[:4090]
        try:
            r = await self._http.post(
                f"{TELEGRAM_API}{settings.telegram_token}/editMessageText",
                json={
                    "chat_id": chat_id,
                    "message_id": message_id,
                    "text": chunk,
                    "parse_mode": "HTML",
                    "disable_web_page_preview": True,
                },
            )
            if r.status_code == 200:
                # If text was truncated, send the remainder
                if len(html_text) > 4090:
                    remainder = html_text[4090:]
                    await self._send(chat_id, remainder, already_html=True)
                return True
            detail = r.json().get("description", "")
            if "message is not modified" in detail:
                return True
            logger.warning("[Bot] editMessageText %d: %s", r.status_code, detail)
            return False
        except Exception as exc:
            logger.error("[Bot] _edit_message: %s", exc)
            return False

    async def _delete_message(self, chat_id: str, message_id: int) -> None:
        if not settings.telegram_token or not message_id:
            return
        try:
            await self._http.post(
                f"{TELEGRAM_API}{settings.telegram_token}/deleteMessage",
                json={"chat_id": chat_id, "message_id": message_id},
                timeout=5.0,
            )
        except Exception:
            pass

    async def _answer_callback(self, callback_query_id: str) -> None:
        if not settings.telegram_token:
            return
        try:
            await self._http.post(
                f"{TELEGRAM_API}{settings.telegram_token}/answerCallbackQuery",
                json={"callback_query_id": callback_query_id},
                timeout=5.0,
            )
        except Exception:
            pass

    async def _send(self, chat_id: str, text: str, already_html: bool = False) -> bool:
        if not settings.telegram_token or not text:
            return False
        html_text = text if already_html else self._md_to_html(text)
        for chunk in [html_text[i:i+4000] for i in range(0, len(html_text), 4000)]:
            try:
                r = await self._http.post(
                    f"{TELEGRAM_API}{settings.telegram_token}/sendMessage",
                    json={
                        "chat_id": chat_id,
                        "text": chunk,
                        "parse_mode": "HTML",
                        "disable_web_page_preview": True,
                    },
                )
                if r.status_code != 200:
                    logger.warning("[Bot] sendMessage %d: %s",
                                   r.status_code, r.text[:100])
            except Exception as exc:
                logger.error("[Bot] _send: %s", exc)
        return True

    # ── Media sending ──────────────────────────────────────────────────────

    async def _send_photo_bytes(self, chat_id: str, image_bytes: bytes,
                                 caption: str = None,
                                 filename: str = "aria.png") -> bool:
        if not settings.telegram_token or not image_bytes:
            return False
        try:
            d: dict = {"chat_id": chat_id}
            if caption:
                d["caption"]    = self._md_to_html(caption)[:1024]
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
                                 caption: str = None,
                                 filename: str = "aria.mp4") -> bool:
        if not settings.telegram_token or not video_bytes:
            return False
        try:
            d: dict = {"chat_id": chat_id}
            if caption:
                d["caption"]    = self._md_to_html(caption)[:1024]
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
                                 caption: str = None,
                                 filename: str = "aria.wav") -> bool:
        if not settings.telegram_token or not audio_bytes:
            return False
        try:
            d: dict = {"chat_id": chat_id}
            if caption:
                d["caption"]    = self._md_to_html(caption)[:1024]
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
            d: dict = {"chat_id": chat_id}
            if caption:
                d["caption"]    = self._md_to_html(caption)[:1024]
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

    # ── Proactive notifications ────────────────────────────────────────────

    async def notify_owner(self, message: str) -> bool:
        """ARIA decides proactively to notify the owner. Use sparingly."""
        chat_id = str(getattr(settings, "TELEGRAM_CHAT_ID", "") or "")
        if not chat_id:
            return False
        return await self._send(chat_id, message)

    async def close(self) -> None:
        self._running = False
        await self._http.aclose()


# ── Singleton ──────────────────────────────────────────────────────────────

_bot: Optional[AriaTelegramBot] = None

def get_bot() -> AriaTelegramBot:
    global _bot
    if _bot is None:
        _bot = AriaTelegramBot()
    return _bot
