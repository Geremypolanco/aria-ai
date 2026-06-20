"""
AriaTelegramBot v7 — Elite Professional Edition.

Diseño de clase mundial:
  ✦ Typing indicator (sendChatAction) antes de cada respuesta
  ✦ Placeholder → editMessageText para sensación de streaming
  ✦ Comandos registrados con setMyCommands (/start, /ayuda, /estado, /limpiar)
  ✦ Bienvenida rica con inline keyboard
  ✦ Markdown → HTML conversion segura
  ✦ Formateo específico por tipo de herramienta
  ✦ Menú de acción rápida via inline keyboard
  ✦ Manejo robusto de errores con mensajes claros

Todo input (texto libre O comandos) sigue pasando por AriaMind.
El bot solo se encarga de I/O de alto nivel.
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

# ── Inline keyboard layouts ────────────────────────────────────────────────

QUICK_ACTIONS_KB = {
    "inline_keyboard": [
        [
            {"text": "💰 Ciclo de ingresos",   "callback_data": "quick_income"},
            {"text": "📅 Ciclo diario",         "callback_data": "quick_daily"},
        ],
        [
            {"text": "🔍 Buscar en web",        "callback_data": "quick_search"},
            {"text": "🎨 Generar imagen",        "callback_data": "quick_image"},
        ],
        [
            {"text": "📊 Estado del sistema",   "callback_data": "quick_status"},
            {"text": "🎯 Objetivos autónomos",  "callback_data": "quick_objectives"},
        ],
        [
            {"text": "🌐 Portfolio GitHub",     "callback_data": "quick_portfolio"},
            {"text": "🩺 Diagnóstico ingresos", "callback_data": "quick_diagnostico"},
        ],
        [
            {"text": "🧲 Lead Magnet",          "callback_data": "quick_magnet"},
            {"text": "🧵 Hilo Viral",            "callback_data": "quick_thread"},
        ],
        [
            {"text": "📈 Analíticas",            "callback_data": "quick_reporte"},
            {"text": "📦 Catálogo",              "callback_data": "quick_catalogo"},
        ],
        [
            {"text": "📚 Base de conocimiento", "callback_data": "quick_kb"},
            {"text": "⚙️ Ver capacidades",      "callback_data": "quick_help"},
        ],
    ]
}

START_KB = {
    "inline_keyboard": [
        [
            {"text": "⚡ Ver capacidades",     "callback_data": "quick_help"},
            {"text": "📊 Estado",               "callback_data": "quick_status"},
        ],
        [
            {"text": "💡 Ejemplo: busca tendencias de IA", "callback_data": "example_trends"},
        ],
    ]
}

# ── Bot commands to register ───────────────────────────────────────────────

BOT_COMMANDS = [
    {"command": "start",       "description": "Bienvenida e introducción a ARIA"},
    {"command": "ayuda",       "description": "Ver todas las capacidades"},
    {"command": "estado",      "description": "Estado del sistema en tiempo real"},
    {"command": "limpiar",     "description": "Limpiar historial de la conversación"},
    {"command": "ingresos",    "description": "Ejecutar ciclo de ingresos ahora"},
    {"command": "ciclo_diario","description": "Ejecutar ciclo completo de negocio del día"},
    {"command": "objetivos",   "description": "Ver objetivos estratégicos autónomos"},
    {"command": "leads",       "description": "Descubrir leads y avanzar CRM"},
    {"command": "retencion",   "description": "Lanzar campañas de retención de clientes"},
    {"command": "shopify",     "description": "Optimizar tienda Shopify"},
    {"command": "busca",       "description": "Buscar algo en internet"},
    {"command": "imagen",      "description": "Generar una imagen con IA"},
    {"command": "piensa",      "description": "Razonamiento profundo sobre un tema"},
    {"command": "metas",       "description": "Ver metas activas de ARIA"},
    {"command": "portfolio",   "description": "Crear/actualizar portfolio en GitHub Pages"},
    {"command": "diagnostico", "description": "Diagnóstico de canales de ingresos activos"},
    {"command": "briefing",    "description": "Resumen de negocio ahora mismo"},
    {"command": "afiliado",    "description": "Publicar artículo de afiliado ahora"},
    {"command": "magnet",      "description": "Crear lead magnet gratuito → funnel de captura"},
    {"command": "thread",      "description": "Crear hilo viral de Twitter/X"},
    {"command": "reporte",     "description": "Reporte de analíticas por estrategia de ingresos"},
    {"command": "demo",        "description": "Publicar demo de IA en HuggingFace Spaces (gratis)"},
    {"command": "catalogo",    "description": "Ver todos los productos y publicaciones de ARIA"},
]

# ── Welcome message ────────────────────────────────────────────────────────

WELCOME_MESSAGE = """\
<b>✦ ARIA está en línea</b>

Soy tu inteligencia operativa personal — no un chatbot genérico.

<b>Lo que puedo hacer ahora mismo:</b>
• 💰 Ejecutar ciclos de ingresos autónomos (income loop 24/7)
• 📅 Correr el ciclo diario completo: contenido + leads + outreach + retención
• 🎯 Gestionar objetivos estratégicos autónomos (6 objetivos en piloto automático)
• 👥 Descubrir leads, avanzar CRM y enviar outreach personalizado
• 🔄 Campañas de retención: win-back a inactivos + loyalty rewards a VIPs
• 🛒 Optimizar tienda Shopify: SEO, bundles, flash sales
• 🔍 Buscar e investigar en internet en tiempo real
• 🎨 Generar imágenes, música y video con IA
• 💻 Navegar la web como un humano (click, formularios, screenshots)
• 🌐 Crear sitios web, presentaciones, PDFs y software completo
• 🤖 Coordinar equipos de agentes especializados (CEO, CMO, CFO, Dev)
• 📧 Publicar contenido en blog, LinkedIn, Twitter, TikTok

<i>Habla conmigo en lenguaje natural. Sin comandos especiales.</i>"""


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

        # Quick slash command → natural language translation for AriaMind
        _SLASH_TRANSLATIONS: dict[str, str] = {
            "/ingresos":     "ejecuta un ciclo de ingresos ahora mismo usando run_income_cycle",
            "/ciclo_diario": "ejecuta el ciclo completo de negocio del día usando run_daily_cycle",
            "/objetivos":    "muéstrame el estado de todos los objetivos estratégicos autónomos usando check_objectives",
            "/leads":        "descubre 10 leads nuevos y avanza los contactos del CRM usando run_acquisition",
            "/retencion":    "lanza las campañas de retención de clientes: win-back e inactivos usando run_retention",
            "/shopify":      "optimiza el SEO de los productos de Shopify usando shopify_optimize con operation seo",
            "/busca":        "busca en internet: ",
            "/imagen":       "genera una imagen de: ",
            "/piensa":       "usa razonamiento profundo para analizar: ",
            "/metas":        "muéstrame mis metas activas usando get_status",
            "/portfolio":    "crea o actualiza el portfolio profesional de ARIA en GitHub Pages usando setup_portfolio",
            "/diagnostico":  "muéstrame el diagnóstico completo de todos los canales de ingresos usando diagnose_income",
            "/briefing":     "ejecuta el morning briefing ahora mismo y envíame el resumen usando run_objective con objective morning_briefing",
            "/afiliado":     "ejecuta una estrategia de contenido de afiliado ahora mismo usando run_income_cycle con strategy affiliate_content",
            "/magnet":       "crea un lead magnet gratuito ahora mismo usando run_income_cycle con strategy lead_magnet",
            "/thread":       "crea y publica un hilo viral de Twitter/X usando run_income_cycle con strategy viral_thread",
            "/reporte":      "muéstrame el reporte de analíticas por estrategia de ingresos usando get_income_analytics",
            "/demo":         "publica un demo de IA en HuggingFace Spaces usando run_income_cycle con strategy hf_spaces_demo",
            "/catalogo":     "muéstrame el catálogo completo de productos y publicaciones de ARIA usando get_product_catalog",
        }
        for cmd, translated in _SLASH_TRANSLATIONS.items():
            if text == cmd or text.startswith(cmd + " "):
                suffix = text[len(cmd):].strip()
                if translated.endswith(": "):
                    text = translated + suffix
                else:
                    text = (translated + " " + suffix).strip() if suffix else translated
                break

        # Slash commands → CommandRouter (before AriaMind)
        if text.startswith("/") and text not in ("/start",):
            try:
                from apps.core.commands.aria_commands import get_command_router
                router = get_command_router()
                if router.is_command(text):
                    cmd_response = await router.handle(text, session_id=f"telegram:{chat_id}")
                    if cmd_response:
                        await self._edit_or_send(chat_id, placeholder_id, cmd_response)
                        return
            except Exception as exc:
                logger.error("[Bot] CommandRouter error: %s", exc)

        # Everything through AriaMind
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
        """Handle inline keyboard button presses."""
        chat_id   = str(cbq["message"]["chat"]["id"])
        cb_id     = cbq["id"]
        data      = cbq.get("data", "")

        if not self._is_authorized(chat_id):
            return

        # Acknowledge the callback immediately
        await self._answer_callback(cb_id)

        mapping = {
            "quick_income":       "ejecuta un ciclo de ingresos ahora mismo",
            "quick_daily":        "ejecuta el ciclo completo de negocio del día",
            "quick_search":       "busca las últimas tendencias en inteligencia artificial",
            "quick_image":        "genera una imagen de un paisaje futurista con IA",
            "quick_status":       "/estado",
            "quick_objectives":   "muéstrame el estado de los objetivos estratégicos autónomos",
            "quick_think":        "usa razonamiento profundo para explicar qué es la computación cuántica",
            "quick_kb":           "¿qué hay en mi base de conocimiento?",
            "quick_help":         "/ayuda",
            "quick_portfolio":    "crea o actualiza el portfolio profesional de ARIA en GitHub Pages",
            "quick_diagnostico":  "muéstrame el diagnóstico completo de canales de ingresos usando diagnose_income",
            "quick_magnet":       "crea un lead magnet gratuito ahora mismo usando run_income_cycle con strategy lead_magnet",
            "quick_thread":       "crea y publica un hilo viral de Twitter/X usando run_income_cycle con strategy viral_thread",
            "quick_reporte":      "muéstrame el reporte de analíticas por estrategia de ingresos usando get_income_analytics",
            "quick_demo":         "publica un demo de IA en HuggingFace Spaces usando run_income_cycle con strategy hf_spaces_demo",
            "quick_catalogo":     "muéstrame el catálogo completo de productos y publicaciones de ARIA usando get_product_catalog",
            "example_trends":     "busca las últimas noticias sobre modelos de lenguaje grandes",
        }

        user_text = mapping.get(data)
        if user_text:
            # Synthesize a fake message object and handle it
            fake_msg = {
                "chat": {"id": int(chat_id)},
                "text": user_text,
            }
            await self._handle_message(fake_msg)

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
        if not settings.telegram_token:
            return
        try:
            await self._http.post(
                f"{TELEGRAM_API}{settings.telegram_token}/sendMessage",
                json={
                    "chat_id": chat_id,
                    "text": WELCOME_MESSAGE,
                    "parse_mode": "HTML",
                    "reply_markup": START_KB,
                },
            )
        except Exception as exc:
            logger.error("[Bot] _send_welcome: %s", exc)

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
