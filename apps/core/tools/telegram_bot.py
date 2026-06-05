"""
AriaTelegramBot v2 — Conversacional completo con ejecución autónoma de acciones.

Mejoras:
- Detecta intenciones en NL y EJECUTA la acción directamente (no solo sugiere)
- Soporte de mensajes de voz (Groq Whisper → transcripción → acción)
- Respuesta con voz via ElevenLabs
- Botones inline en cada respuesta
- Memoria de conversación en Redis (24h)
- Contexto real del sistema en cada respuesta IA
"""
from __future__ import annotations

import asyncio
import importlib
import json
import logging
from typing import Any, Optional

import httpx

from apps.core.config import settings

logger = logging.getLogger("aria.telegram_bot")

TELEGRAM_API = "https://api.telegram.org/bot"
CONVERSATION_KEY = "aria:conversation:history"
CONVERSATION_TTL = 86400  # 24h


class AriaTelegramBot:

    HELP_TEXT = (
        "🤖 <b>ARIA AI — Comandos disponibles</b>\n\n"
        "<b>📊 SISTEMA</b>\n"
        "/status — Estado completo\n"
        "/agentes — Estado de agentes\n"
        "/logs [n] — Últimos N logs\n\n"
        "<b>💰 FINANZAS</b>\n"
        "/revenue — Dashboard de ingresos\n\n"
        "<b>⚙️ CONTROL</b>\n"
        "/ciclo — Ciclo autónomo ahora\n"
        "/pausa — Pausa el scheduler\n"
        "/reanudar — Reanuda el scheduler\n"
        "/evolve — Auto-evolución\n\n"
        "<b>✅ APROBACIONES</b>\n"
        "/pendientes — Aprobaciones en espera\n"
        "/aprobar &lt;id&gt; — Aprobar acción\n"
        "/rechazar &lt;id&gt; — Rechazar acción\n\n"
        "<b>🚀 AGENTES</b>\n"
        "/pm &lt;tarea&gt; — PMAgent\n"
        "/cfo &lt;tarea&gt; — CFOAgent\n"
        "/dev &lt;tarea&gt; — DevAgent\n"
        "/marketing &lt;tarea&gt; — MarketingAgent\n"
        "/soporte &lt;consulta&gt; — SupportAgent\n\n"
        "<b>🎤 VOZ</b>\n"
        "/voz &lt;texto&gt; — Respuesta de voz\n"
        "Envía nota de voz → ARIA transcribe y actúa\n\n"
        "<b>💬 CONVERSACIÓN</b>\n"
        "Escribe en lenguaje natural — ARIA detecta\n"
        "la intención y ejecuta la acción.\n"
        "/ia &lt;pregunta&gt; — Pregunta a la IA\n"
        "/limpiar — Borra historial\n\n"
        "<b>🔍 GOOGLE SUITE</b>\n"
        "/buscar &lt;query&gt; — Búsqueda web\n"
        "/youtube &lt;query&gt; — Buscar en YouTube\n"
        "/tendencias — Trending topics en tiempo real\n"
        "/pagespeed &lt;url&gt; — Analizar velocidad SEO\n"
        "/traducir &lt;lang&gt; &lt;texto&gt; — Traducir (ej: en Hola)\n"
        "/ocr &lt;url&gt; — Extraer texto de imagen\n\n"
        "<b>🤗 HUGGINGFACE</b>\n"
        "/imagen &lt;prompt&gt; — Generar imagen con FLUX.1\n"
        "/resumir &lt;texto&gt; — Resumir texto\n"
        "/sentimiento &lt;texto&gt; — Análisis de sentimiento\n"
        "/codigo &lt;tarea&gt; — Generar código\n"
        "/clasificar &lt;texto&gt; — Zero-shot classification\n"
        "/capacidades — Ver todas las capacidades\n\n"
        "<b>🧬 AUTO-EVOLUCIÓN</b>\n"
        "/evolve — Ciclo completo (mejora código + APIs)\n"
        "/mejorar [n] — Mejorar N archivos de código\n"
        "/apis — Descubrir e integrar nuevas APIs\n"
        "/score — Score de salud del sistema\n\n"
        "/ayuda — Este menú"
    )

    INTENT_MAP = [
        {"keywords": ["estado", "status", "cómo estás", "qué está pasando", "cómo va", "reporta", "reporte", "resumen"], "action": "status"},
        {"keywords": ["ingresos", "dinero", "revenue", "cuánto has ganado", "ganancias", "ventas", "cuánto llevamos"], "action": "revenue"},
        {"keywords": ["ciclo", "trabaja", "ejecuta ahora", "analiza ahora", "busca oportunidades", "empieza a trabajar", "opera"], "action": "ciclo"},
        {"keywords": ["pausa", "para", "detente", "descansa", "stop", "detén todo"], "action": "pausa"},
        {"keywords": ["continúa", "reanuda", "sigue", "actívate", "resume", "vuelve a trabajar"], "action": "reanudar"},
        {"keywords": ["pendiente", "aprobación", "qué necesita mi aprobación", "qué espera mi ok"], "action": "pendientes"},
        {"keywords": ["evoluciona", "optimízate", "mejórate", "analiza tu rendimiento"], "action": "evolve"},
        {"keywords": ["analiza mercado", "busca nicho", "investiga mercado", "qué vender", "qué nichos hay"], "action": "pm"},
        {"keywords": ["crea producto", "publica en gumroad", "genera ingreso", "vende algo", "monetiza"], "action": "cfo"},
        {"keywords": ["desarrolla", "construye", "programa", "crea código", "lanza web", "crea una web"], "action": "dev"},
        {"keywords": ["marketing", "publica en redes", "twittea", "postea", "campaña de email", "crea contenido"], "action": "marketing"},
        {"keywords": ["logs", "errores", "qué pasó", "historial", "últimos eventos"], "action": "logs"},
        {"keywords": ["busca en google", "busca en internet", "googlea", "busca información sobre", "qué es", "quién es", "investiga sobre"], "action": "buscar"},
        {"keywords": ["busca en youtube", "busca video", "encuentra video de", "muéstrame videos de"], "action": "youtube"},
        {"keywords": ["genera imagen", "crea imagen", "imagina", "dibuja", "genera una foto de", "crea una imagen de"], "action": "imagen"},
        {"keywords": ["traduce", "tradúceme", "en inglés", "en francés", "en alemán", "en portugués", "en japonés", "en chino"], "action": "traducir"},
        {"keywords": ["resume", "resumir", "hazme un resumen de", "sintetiza"], "action": "resumir"},
        {"keywords": ["tendencias", "trending", "qué es viral", "qué está en tendencia", "qué busca la gente"], "action": "tendencias"},
        {"keywords": ["genera código", "escribe código", "programa", "crea un script", "hazme un programa"], "action": "codigo"},
        {"keywords": ["analiza sentimiento", "cómo suena esto", "es positivo o negativo", "qué sentimiento tiene"], "action": "sentimiento"},
        {"keywords": ["qué puedes hacer", "cuáles son tus capacidades", "qué funciones tienes", "muéstrame tus poderes"], "action": "capacidades"},
        {"keywords": ["mejora tu código", "optimízate", "evoluciona", "mejórate", "auto-mejora", "actualízate"], "action": "mejorar"},
        {"keywords": ["busca apis", "agrega api", "integra api", "añade api", "descubre nuevas herramientas"], "action": "apis"},
        {"keywords": ["score", "tu puntuación", "cómo estás de salud", "estado del sistema", "health check"], "action": "score"},
    ]

    ACTION_DESCRIPTIONS = {
        "status": "consultar el estado del sistema",
        "revenue": "ver el dashboard de ingresos",
        "ciclo": "disparar un ciclo autónomo",
        "pausa": "pausar el scheduler",
        "reanudar": "reanudar el scheduler",
        "pendientes": "ver aprobaciones pendientes",
        "evolve": "ejecutar auto-evolución",
        "pm": "analizar el mercado",
        "cfo": "crear y publicar un producto",
        "dev": "desarrollar un producto",
        "marketing": "ejecutar marketing",
        "logs": "ver los logs del sistema",
        "buscar": "buscar información en Google",
        "youtube": "buscar videos en YouTube",
        "imagen": "generar una imagen con FLUX.1",
        "traducir": "traducir el texto",
        "resumir": "resumir el texto",
        "tendencias": "ver trending topics en tiempo real",
        "codigo": "generar código con HuggingFace Qwen2.5",
        "sentimiento": "analizar el sentimiento del texto",
        "capacidades": "mostrar todas las capacidades de ARIA",
        "mejorar": "mejorar el código del sistema autónomamente",
        "apis": "descubrir e integrar nuevas APIs",
        "score": "ver el score de salud del sistema",
    }

    def __init__(self) -> None:
        self._token = settings.TELEGRAM_TOKEN
        self._owner_id = settings.TELEGRAM_CHAT_ID
        self._base_url = f"{TELEGRAM_API}{self._token}"
        self._http = httpx.AsyncClient(timeout=30.0)

    async def handle_update(self, update: dict[str, Any]) -> None:
        try:
            message = update.get("message") or update.get("edited_message")
            callback = update.get("callback_query")
            if message:
                await self._handle_message(message)
            elif callback:
                await self._handle_callback(callback)
        except Exception as exc:
            logger.error("[TelegramBot] Error: %s", exc)

    async def _handle_message(self, message: dict[str, Any]) -> None:
        chat_id = str(message.get("chat", {}).get("id", ""))
        text = message.get("text", "").strip()
        voice = message.get("voice")
        audio = message.get("audio")
        from_id = str(message.get("from", {}).get("id", ""))

        if not chat_id:
            return
        if from_id != self._owner_id and chat_id != self._owner_id:
            await self.send(chat_id, "⛔ No autorizado.")
            return

        if voice or audio:
            await self._handle_voice_message(message, chat_id)
            return
        if not text:
            return

        logger.info("[TelegramBot] Msg: %s", text[:80])
        if text.startswith("/"):
            await self._parse_command(text, chat_id)
        else:
            await self._handle_natural_language(text, chat_id)

    async def _handle_callback(self, callback: dict[str, Any]) -> None:
        chat_id = str(callback.get("message", {}).get("chat", {}).get("id", ""))
        data = callback.get("data", "")
        callback_id = callback.get("id", "")
        await self._http.post(f"{self._base_url}/answerCallbackQuery", json={"callback_query_id": callback_id})

        if data.startswith("aprobar:"):
            await self._do_approval(chat_id, data.split(":", 1)[1], "approved")
        elif data.startswith("rechazar:"):
            await self._do_approval(chat_id, data.split(":", 1)[1], "rejected")
        elif data.startswith("cmd:"):
            cmd = data[4:]
            actions = {
                "ciclo": lambda: self.cmd_ciclo(chat_id),
                "status": lambda: self.cmd_status(chat_id),
                "revenue": lambda: self.cmd_revenue(chat_id),
                "pendientes": lambda: self.cmd_pendientes(chat_id),
                "evolve": lambda: self.cmd_evolve(chat_id),
                "evolve_full": lambda: asyncio.ensure_future(self._run_evolve_async(chat_id, "full", 2, 1)),
                "mejorar": lambda: self.cmd_mejorar(chat_id, "2"),
                "apis": lambda: self.cmd_apis(chat_id, "1"),
                "score": lambda: self.cmd_score(chat_id),
            }
            if cmd in actions:
                await actions[cmd]()

    # ── VOZ ───────────────────────────────────────────────

    async def _handle_voice_message(self, message: dict[str, Any], chat_id: str) -> None:
        await self._send_typing(chat_id)
        try:
            voice = message.get("voice") or message.get("audio")
            file_id = voice.get("file_id")
            file_res = await self._http.get(f"{self._base_url}/getFile?file_id={file_id}")
            file_path = file_res.json().get("result", {}).get("file_path", "")
            if not file_path:
                await self.send(chat_id, "❌ No pude descargar el audio.")
                return
            audio_res = await self._http.get(f"https://api.telegram.org/file/bot{self._token}/{file_path}")
            transcript = await self._transcribe_audio(audio_res.content)
            if not transcript:
                await self.send(chat_id, "❌ No pude transcribir el audio.")
                return
            await self.send(chat_id, f"🎤 <i>Escuché:</i> {transcript}")
            await self._handle_natural_language(transcript, chat_id)
        except Exception as exc:
            logger.error("[TelegramBot] Voice error: %s", exc)
            await self.send(chat_id, "❌ Error procesando el audio.")

    async def _transcribe_audio(self, audio_bytes: bytes) -> Optional[str]:
        try:
            import io
            headers = {"Authorization": f"Bearer {settings.GROQ_API_KEY}"}
            files = {"file": ("audio.ogg", io.BytesIO(audio_bytes), "audio/ogg")}
            data = {"model": "whisper-large-v3", "language": "es"}
            res = await self._http.post(
                "https://api.groq.com/openai/v1/audio/transcriptions",
                headers=headers, files=files, data=data, timeout=30.0,
            )
            return res.json().get("text", "").strip() if res.status_code == 200 else None
        except Exception as exc:
            logger.error("[TelegramBot] Transcription error: %s", exc)
            return None

    async def _send_voice_response(self, chat_id: str, text: str) -> bool:
        if not settings.ELEVENLABS_API_KEY:
            return False
        try:
            import io
            res = await self._http.post(
                "https://api.elevenlabs.io/v1/text-to-speech/EXAVITQu4vr4xnSDxMaL",
                headers={"xi-api-key": settings.ELEVENLABS_API_KEY, "Content-Type": "application/json"},
                json={"text": text[:500], "model_id": "eleven_multilingual_v2",
                      "voice_settings": {"stability": 0.5, "similarity_boost": 0.75}},
                timeout=30.0,
            )
            if res.status_code == 200:
                files = {"voice": ("aria.mp3", io.BytesIO(res.content), "audio/mpeg")}
                await self._http.post(f"{self._base_url}/sendVoice", data={"chat_id": chat_id}, files=files)
                return True
        except Exception as exc:
            logger.error("[TelegramBot] ElevenLabs error: %s", exc)
        return False

    # ── NL + EJECUCIÓN AUTÓNOMA ───────────────────────────

    async def _handle_natural_language(self, text: str, chat_id: str) -> None:
        await self._send_typing(chat_id)
        intent = self._detect_intent(text)

        if intent:
            action = intent["action"]
            desc = self.ACTION_DESCRIPTIONS.get(action, action)
            await self.send(chat_id, f"⚡ <i>Entendido — voy a {desc}.</i>")
            await self._execute_intent(chat_id, action, text)
            return

        history = await self._get_conversation_history()
        history.append({"role": "user", "content": text})

        try:
            from apps.core.tools.ai_client import AIModel, get_ai_client
            ai = await get_ai_client()
            ctx = await self._get_system_context()
            response = await ai.complete(
                system=(
                    f"Eres ARIA, sistema autónomo de negocios digitales de {settings.OWNER_NAME}.\n"
                    f"Estado actual:\n{ctx}\n\n"
                    "Eres directa, proactiva y eficiente. Hablas en primera persona. "
                    "Ejecutas acciones directamente, no dices que el usuario use comandos. "
                    "Máximo 200 palabras. Usa HTML de Telegram. No uses asteriscos ni markdown."
                ),
                user=self._format_history(history),
                model=AIModel.FAST,
            )
            reply = response.content if response and response.success else "No pude procesar tu mensaje."
            history.append({"role": "assistant", "content": reply})
            await self._save_conversation_history(history[-20:])
            keyboard = self._quick_keyboard()
            await self.send(chat_id, reply, reply_markup=keyboard)
        except Exception as exc:
            logger.error("[TelegramBot] NL error: %s", exc)
            await self.send(chat_id, "❌ Error. Usa /ayuda para ver los comandos.")

    def _detect_intent(self, text: str) -> Optional[dict]:
        text_lower = text.lower()
        for intent in self.INTENT_MAP:
            if any(kw in text_lower for kw in intent["keywords"]):
                return intent
        return None

    async def _execute_intent(self, chat_id: str, action: str, original: str) -> None:
        mapping = {
            "status":     lambda: self.cmd_status(chat_id),
            "revenue":    lambda: self.cmd_revenue(chat_id),
            "ciclo":      lambda: self.cmd_ciclo(chat_id),
            "pausa":      lambda: self.cmd_pausa(chat_id),
            "reanudar":   lambda: self.cmd_reanudar(chat_id),
            "pendientes": lambda: self.cmd_pendientes(chat_id),
            "evolve":     lambda: self.cmd_evolve(chat_id),
            "logs":       lambda: self.cmd_logs(chat_id, "10"),
            "pm":         lambda: self.cmd_agent_run(chat_id, "pm", original),
            "cfo":        lambda: self.cmd_agent_run(chat_id, "cfo", original),
            "dev":        lambda: self.cmd_agent_run(chat_id, "dev", original),
            "marketing":  lambda: self.cmd_agent_run(chat_id, "marketing", original),
            "buscar":     lambda: self.cmd_buscar(chat_id, original),
            "youtube":    lambda: self.cmd_youtube(chat_id, original),
            "imagen":     lambda: self.cmd_imagen(chat_id, original),
            "traducir":   lambda: self.cmd_traducir(chat_id, original),
            "resumir":    lambda: self.cmd_resumir(chat_id, original),
            "tendencias": lambda: self.cmd_tendencias(chat_id),
            "codigo":     lambda: self.cmd_codigo(chat_id, original),
            "sentimiento":lambda: self.cmd_sentimiento(chat_id, original),
            "capacidades":lambda: self.cmd_capacidades(chat_id),
            "mejorar":    lambda: self.cmd_mejorar(chat_id, "2"),
            "apis":       lambda: self.cmd_apis(chat_id, "2"),
            "score":      lambda: self.cmd_score(chat_id),
        }
        handler = mapping.get(action)
        if handler:
            await handler()

    def _quick_keyboard(self) -> dict:
        return {"inline_keyboard": [[
            {"text": "📊 Status", "callback_data": "cmd:status"},
            {"text": "🚀 Ciclo", "callback_data": "cmd:ciclo"},
        ]]}

    async def _get_system_context(self) -> str:
        try:
            from apps.core.memory.supabase_client import get_db
            from apps.core.memory.redis_client import get_cache
            db = get_db()
            cache = get_cache()
            rev = await db.get_total_revenue()
            cycles = await cache.get("aria:cycle_count") or "0"
            paused = await cache.get("aria:scheduler_paused")
            return (f"Revenue: ${rev:.2f} | Ciclos: {cycles} | "
                    f"Scheduler: {'PAUSADO' if paused else 'ACTIVO'}")
        except Exception:
            return "Sistema: OPERATIVO"

    def _format_history(self, history: list[dict]) -> str:
        return "\n".join(
            f"{'Geremy' if m['role']=='user' else 'ARIA'}: {m['content']}"
            for m in history[-10:]
        )

    # ── PARSER ────────────────────────────────────────────

    async def _parse_command(self, text: str, chat_id: str) -> None:
        parts = text.split(maxsplit=1)
        cmd = parts[0].lower().split("@")[0]
        args = parts[1] if len(parts) > 1 else ""
        handlers = {
            "/start":      lambda: self.cmd_start(chat_id),
            "/ayuda":      lambda: self.cmd_ayuda(chat_id),
            "/help":       lambda: self.cmd_ayuda(chat_id),
            "/status":     lambda: self.cmd_status(chat_id),
            "/revenue":    lambda: self.cmd_revenue(chat_id),
            "/ingresos":   lambda: self.cmd_revenue(chat_id),
            "/ciclo":      lambda: self.cmd_ciclo(chat_id),
            "/pausa":      lambda: self.cmd_pausa(chat_id),
            "/reanudar":   lambda: self.cmd_reanudar(chat_id),
            "/agentes":    lambda: self.cmd_agentes(chat_id),
            "/pendientes": lambda: self.cmd_pendientes(chat_id),
            "/evolve":     lambda: self.cmd_evolve(chat_id),
            "/limpiar":    lambda: self.cmd_limpiar(chat_id),
            "/logs":       lambda: self.cmd_logs(chat_id, args),
            "/ia":         lambda: self.cmd_ia(chat_id, args),
            "/voz":        lambda: self.cmd_voz(chat_id, args),
            "/aprobar":    lambda: self.cmd_aprobar(chat_id, args),
            "/rechazar":   lambda: self.cmd_rechazar(chat_id, args),
            "/pm":         lambda: self.cmd_agent_run(chat_id, "pm", args or "analiza las mejores oportunidades de mercado"),
            "/cfo":        lambda: self.cmd_agent_run(chat_id, "cfo", args or "crea un producto digital y publícalo"),
            "/dev":        lambda: self.cmd_agent_run(chat_id, "dev", args or "construye una landing page monetizada"),
            "/marketing":  lambda: self.cmd_agent_run(chat_id, "marketing", args or "crea contenido y publica en redes sociales"),
            "/soporte":    lambda: self.cmd_agent_run(chat_id, "support", args or "revisa consultas de clientes"),
            "/buscar":     lambda: self.cmd_buscar(chat_id, args),
            "/youtube":    lambda: self.cmd_youtube(chat_id, args),
            "/imagen":     lambda: self.cmd_imagen(chat_id, args),
            "/traducir":   lambda: self.cmd_traducir(chat_id, args),
            "/resumir":    lambda: self.cmd_resumir(chat_id, args),
            "/tendencias": lambda: self.cmd_tendencias(chat_id),
            "/codigo":     lambda: self.cmd_codigo(chat_id, args),
            "/sentimiento":lambda: self.cmd_sentimiento(chat_id, args),
            "/pagespeed":  lambda: self.cmd_pagespeed(chat_id, args),
            "/ocr":        lambda: self.cmd_ocr(chat_id, args),
            "/capacidades":lambda: self.cmd_capacidades(chat_id),
            "/mejorar":    lambda: self.cmd_mejorar(chat_id, args),
            "/apis":       lambda: self.cmd_apis(chat_id, args),
            "/score":      lambda: self.cmd_score(chat_id),
        }
        h = handlers.get(cmd)
        if h:
            await h()
        else:
            await self.send(chat_id, f"❓ Comando desconocido: <code>{cmd}</code>\nUsa /ayuda.")

    # ── COMANDOS ──────────────────────────────────────────

    async def cmd_start(self, chat_id: str) -> None:
        kb = {"inline_keyboard": [
            [{"text": "📊 Estado", "callback_data": "cmd:status"}, {"text": "💰 Ingresos", "callback_data": "cmd:revenue"}],
            [{"text": "🚀 Ciclo ahora", "callback_data": "cmd:ciclo"}, {"text": "✅ Pendientes", "callback_data": "cmd:pendientes"}],
            [{"text": "🧠 Evolución", "callback_data": "cmd:evolve"}],
        ]}
        await self.send(chat_id,
            f"🤖 <b>ARIA AI — Online</b>\n\n"
            f"Bienvenido, {settings.OWNER_NAME}. Sistema operativo activo 24/7.\n\n"
            f"Soy tu sistema autónomo de negocios digitales. Detecto oportunidades, "
            f"creo productos, ejecuto marketing y genero revenue sin intervención humana.\n\n"
            f"Escríbeme en lenguaje natural — detecto tu intención y ejecuto la acción.\n"
            f"También puedes enviarme notas de voz.\n\n"
            f"/ayuda — ver todos los comandos", reply_markup=kb)

    async def cmd_ayuda(self, chat_id: str) -> None:
        await self.send(chat_id, self.HELP_TEXT)

    async def cmd_status(self, chat_id: str) -> None:
        await self._send_typing(chat_id)
        try:
            from apps.core.memory.supabase_client import get_db
            from apps.core.memory.redis_client import get_cache
            db, cache = get_db(), get_cache()
            total = await db.get_total_revenue()
            by_platform = await db.get_revenue_by_platform()
            plat = "\n".join(f"  • {k}: ${v:.2f}" for k, v in by_platform.items()) or "  Sin ingresos aún"
            agents = [("orchestrator","Orchestrator"),("pm_agent","PM"),("cfo_agent","CFO"),
                      ("dev_agent","Dev"),("marketing_agent","Marketing"),("support_agent","Soporte"),("evolution_agent","Evolución")]
            ag_lines = []
            for name, label in agents:
                alive = await cache.is_agent_alive(name)
                ag_lines.append(f"  {'🟢' if alive else '⚫'} {label}")
            cycles = await cache.get("aria:cycle_count") or "0"
            paused = await cache.get("aria:scheduler_paused")
            kb = {"inline_keyboard": [[{"text": "🚀 Ciclo", "callback_data": "cmd:ciclo"}, {"text": "💰 Ingresos", "callback_data": "cmd:revenue"}]]}
            await self.send(chat_id,
                f"📊 <b>ARIA OS — Estado</b>\n\n"
                f"💰 <b>Revenue total:</b> ${total:.2f} USD\n{plat}\n\n"
                f"🔄 Ciclos: {cycles} | ⚙️ {'⏸ PAUSADO' if paused else '▶️ ACTIVO'}\n\n"
                f"<b>Agentes:</b>\n" + "\n".join(ag_lines) + f"\n\n🕐 {_now_str()}", reply_markup=kb)
        except Exception as exc:
            await self.send(chat_id, f"❌ Error: {exc}")

    async def cmd_revenue(self, chat_id: str) -> None:
        await self._send_typing(chat_id)
        try:
            from apps.core.memory.supabase_client import get_db
            db = get_db()
            total = await db.get_total_revenue()
            by_p = await db.get_revenue_by_platform()
            recent = db._client.table("revenue").select("*").order("created_at", desc=True).limit(5).execute()
            plat = "\n".join(f"  • {k}: ${v:.2f}" for k, v in by_p.items()) or "  Sin ingresos"
            rec = "\n".join(f"  • ${r.get('amount',0):.2f} — {r.get('product_name','N/A')} ({r.get('platform','?')})"
                             for r in (recent.data or [])) or "  Sin transacciones"
            await self.send(chat_id,
                f"💰 <b>Dashboard de Ingresos</b>\n\nTotal: ${total:.2f} USD\n\n"
                f"<b>Por plataforma:</b>\n{plat}\n\n<b>Últimas 5:</b>\n{rec}\n\n🕐 {_now_str()}")
        except Exception as exc:
            await self.send(chat_id, f"❌ Error: {exc}")

    async def cmd_ciclo(self, chat_id: str) -> None:
        await self.send(chat_id, "🚀 <b>Ciclo autónomo iniciado...</b>\nTe notificaré cuando termine.")
        asyncio.create_task(self._run_cycle_async(chat_id))

    async def _run_cycle_async(self, chat_id: str) -> None:
        try:
            from apps.core.memory.redis_client import get_cache
            cache = get_cache()
            if not await cache.acquire_lock("aria:cycle_lock", ttl=3600):
                await self.send(chat_id, "⚠️ Ya hay un ciclo en ejecución.")
                return
            from apps.core.agents.orchestrator import Orchestrator
            orch = Orchestrator()
            await orch.start()
            result = await orch.run_cycle()
            ok = result.get("success", False)
            await self.send(chat_id, f"{'✅' if ok else '❌'} <b>Ciclo completado</b>\nMisiones: {len(result.get('missions', {}))}")
        except Exception as exc:
            await self.send(chat_id, f"❌ Error en ciclo: {exc}")

    async def cmd_pausa(self, chat_id: str) -> None:
        try:
            from apps.core.memory.redis_client import get_cache
            await get_cache().set("aria:scheduler_paused", "1", ttl_seconds=86400 * 7)
            await self.send(chat_id, "⏸ <b>Scheduler pausado.</b> Usa /reanudar para activar.")
        except Exception as exc:
            await self.send(chat_id, f"❌ Error: {exc}")

    async def cmd_reanudar(self, chat_id: str) -> None:
        try:
            from apps.core.memory.redis_client import get_cache
            await get_cache().delete("aria:scheduler_paused")
            await self.send(chat_id, "▶️ <b>Scheduler reanudado.</b> ARIA opera autónomamente.")
        except Exception as exc:
            await self.send(chat_id, f"❌ Error: {exc}")

    async def cmd_evolve(self, chat_id: str) -> None:
        kb = {"inline_keyboard": [[
            {"text": "💻 Solo código", "callback_data": "cmd:mejorar"},
            {"text": "🔌 Solo APIs", "callback_data": "cmd:apis"},
            {"text": "🧬 Todo", "callback_data": "cmd:evolve_full"},
        ]]}
        await self.send(chat_id,
            "🧬 <b>Auto-Evolución de ARIA</b>\n\n"
            "Selecciona el modo de evolución:\n"
            "• <b>Solo código</b> — Mejora archivos existentes\n"
            "• <b>Solo APIs</b> — Descubre e integra nuevas APIs\n"
            "• <b>Todo</b> — Ciclo completo (recomendado)\n\n"
            "⚠️ Los cambios se pushean a GitHub y se deploya automáticamente a Fly.io.",
            reply_markup=kb)

    async def _run_evolve_async(self, chat_id: str, mode: str = "full", max_files: int = 2, max_apis: int = 1) -> None:
        try:
            from apps.core.agents.evolution_agent import EvolutionAgent
            agent = EvolutionAgent()
            await agent.start()
            result = await agent.run({
                "mode": mode,
                "max_files": max_files,
                "max_apis": max_apis,
                "notify_telegram": False,  # We notify here directly
            })
            ok = result.get("success", False)
            imps = result.get("improvements", [])
            apis = result.get("new_apis", [])
            score = result.get("system_score", 0)
            new_score = result.get("new_system_score", 0)
            delta = result.get("score_delta", 0)

            lines = [f"{'✅' if ok else '❌'} <b>Evolución completa</b>\n"]
            lines.append(f"📈 Score: {score} → {new_score} ({'+'if delta>=0 else ''}{delta})")

            if imps:
                lines.append(f"\n<b>💻 Archivos mejorados ({len(imps)}):</b>")
                for i in imps[:3]:
                    f = i.get("file","").split("/")[-1]
                    d = i.get("lines_delta", 0)
                    lines.append(f"  • {f} ({'+' if d>=0 else ''}{d} líneas) → commit {i.get('commit','')}")

            if apis:
                lines.append(f"\n<b>🔌 APIs integradas ({len(apis)}):</b>")
                for a in apis[:3]:
                    lines.append(f"  • {a.get('api','?')}")
                    if a.get("env_var"):
                        lines.append(f"    ⚙️ Agrega en Fly.io Secrets: <code>{a['env_var']}</code>")

            arch = result.get("architecture_insights", {})
            if arch.get("missing_systems"):
                lines.append("\n<b>🏗 Mejoras propuestas (requieren aprobación):</b>")
                for s in arch["missing_systems"][:2]:
                    lines.append(f"  • {s[:80]}")

            lessons = result.get("lessons_learned", {})
            if lessons.get("recommendations"):
                lines.append("\n<b>📚 Aprendizajes:</b>")
                for r in lessons["recommendations"][:2]:
                    lines.append(f"  • {r[:80]}")

            lines.append("\n🚀 Cambios en GitHub — Fly.io deploying...")
            await self.send(chat_id, "\n".join(lines))
        except Exception as exc:
            logger.error("[TelegramBot] evolve error: %s", exc)
            await self.send(chat_id, f"❌ Error en evolución: {exc}")

    async def cmd_mejorar(self, chat_id: str, args: str) -> None:
        n = int(args.strip()) if args.strip().isdigit() else 2
        n = min(n, 5)
        await self.send(chat_id, f"💻 <b>Mejorando {n} archivo(s) de código...</b>\n⏳ Analizando, generando mejoras y pusheando a GitHub.")
        asyncio.create_task(self._run_evolve_async(chat_id, mode="improve_only", max_files=n))

    async def cmd_apis(self, chat_id: str, args: str) -> None:
        n = int(args.strip()) if args.strip().isdigit() else 1
        n = min(n, 3)
        await self.send(chat_id, f"🔌 <b>Descubriendo e integrando {n} API(s) nueva(s)...</b>\n⏳ Evaluando candidatas, generando código de integración y deploying.")
        asyncio.create_task(self._run_evolve_async(chat_id, mode="discover_only", max_apis=n))

    async def cmd_score(self, chat_id: str) -> None:
        await self._send_typing(chat_id)
        try:
            from apps.core.agents.evolution_agent import EvolutionAgent
            from apps.core.tools.self_improvement import SelfImprovementEngine
            from apps.core.tools.api_discovery import APIDiscoveryEngine
            agent = EvolutionAgent()
            await agent.start()
            score = await agent._calculate_system_score()
            imp_engine = SelfImprovementEngine()
            imp_stats = await imp_engine.get_improvement_stats()
            api_engine = APIDiscoveryEngine()
            integrated_apis = await api_engine.get_integrated_apis()

            bar_filled = int(score / 10)
            bar = "█" * bar_filled + "░" * (10 - bar_filled)

            await self.send(chat_id,
                f"📊 <b>Score de Salud del Sistema</b>\n\n"
                f"<b>{score}/100</b> [{bar}]\n\n"
                f"💻 Mejoras de código aplicadas: {imp_stats.get('total_improvements', 0)}\n"
                f"🔌 APIs integradas autónomamente: {len(integrated_apis)}\n\n"
                f"<b>Últimas mejoras:</b>\n"
                + "\n".join(f"  • {i.get('file','').split('/')[-1]} — {i.get('message','')[:60]}"
                             for i in imp_stats.get("recent_improvements", [])[:3])
                + (f"\n\n<b>APIs integradas:</b>\n" + "\n".join(f"  • {a.get('api','')}" for a in integrated_apis[-3:]) if integrated_apis else "")
            )
        except Exception as exc:
            await self.send(chat_id, f"❌ Error: {exc}")

    async def cmd_agentes(self, chat_id: str) -> None:
        await self._send_typing(chat_id)
        try:
            from apps.core.memory.redis_client import get_cache
            cache = get_cache()
            info = [("orchestrator","Director"),("pm_agent","Product Manager"),("cfo_agent","CFO"),
                    ("dev_agent","Developer"),("marketing_agent","Marketing"),("support_agent","Soporte"),("evolution_agent","Evolución")]
            lines = []
            for name, desc in info:
                alive = await cache.is_agent_alive(name)
                st = await cache.get_agent_status(name) or {}
                lines.append(f"{'🟢' if alive else '⚫'} <b>{desc}</b> — {st.get('state','idle')} | tareas: {st.get('tasks_done',0)}")
            await self.send(chat_id, "🤖 <b>Agentes</b>\n\n" + "\n".join(lines))
        except Exception as exc:
            await self.send(chat_id, f"❌ Error: {exc}")

    async def cmd_pendientes(self, chat_id: str) -> None:
        await self._send_typing(chat_id)
        try:
            from apps.core.memory.supabase_client import get_db
            approvals = await get_db().get_pending_approvals(limit=5)
            if not approvals:
                await self.send(chat_id, "✅ <b>Sin aprobaciones pendientes.</b>\nARIA opera de forma completamente autónoma.")
                return
            for a in approvals:
                aid = a.get("id", "")
                kb = {"inline_keyboard": [[
                    {"text": "✅ Aprobar", "callback_data": f"aprobar:{aid}"},
                    {"text": "❌ Rechazar", "callback_data": f"rechazar:{aid}"},
                ]]}
                await self.send(chat_id,
                    f"⏳ <b>Aprobación</b>\n\n"
                    f"ID: <code>{aid[:8]}</code>\n"
                    f"Agente: {a.get('agent_name','?')}\n"
                    f"Acción: {a.get('action_type','?')}\n"
                    f"Monto: ${a.get('amount_usd',0):.2f} USD\n"
                    f"Detalle: {a.get('detail','')[:200]}", reply_markup=kb)
        except Exception as exc:
            await self.send(chat_id, f"❌ Error: {exc}")

    async def cmd_logs(self, chat_id: str, args: str) -> None:
        await self._send_typing(chat_id)
        try:
            n = min(int(args.strip()) if args.strip().isdigit() else 10, 25)
            from apps.core.memory.supabase_client import get_db
            logs = await get_db().get_recent_logs(limit=n)
            if not logs:
                await self.send(chat_id, "📋 No hay logs.")
                return
            icons = {"INFO":"ℹ️","ERROR":"❌","SUCCESS":"✅","REVENUE":"💰","WARNING":"⚠️"}
            lines = [f"{icons.get(l.get('level','INFO'),'•')} [{l.get('agent','?')}] {l.get('message','')[:100]}" for l in logs]
            await self.send(chat_id, f"📋 <b>Últimos {n} logs</b>\n\n<code>" + "\n".join(lines) + "</code>")
        except Exception as exc:
            await self.send(chat_id, f"❌ Error: {exc}")

    async def cmd_ia(self, chat_id: str, args: str) -> None:
        if not args:
            await self.send(chat_id, "❓ Uso: /ia <pregunta>"); return
        await self._send_typing(chat_id)
        try:
            from apps.core.tools.ai_client import AIModel, get_ai_client
            ai = await get_ai_client()
            r = await ai.complete(
                system=f"Eres ARIA, sistema de {settings.OWNER_NAME}. Responde con profundidad. HTML Telegram.",
                user=args, model=AIModel.STRATEGY)
            await self.send(chat_id, f"🧠 <b>ARIA:</b>\n\n{r.content if r and r.success else 'Sin respuesta.'}")
        except Exception as exc:
            await self.send(chat_id, f"❌ Error: {exc}")

    async def cmd_voz(self, chat_id: str, args: str) -> None:
        if not args:
            await self.send(chat_id, "❓ Uso: /voz <texto>"); return
        await self._send_typing(chat_id)
        if not await self._send_voice_response(chat_id, args):
            await self.send(chat_id, f"🔊 <i>(ElevenLabs no configurado)</i>\n\n{args}")

    async def cmd_aprobar(self, chat_id: str, args: str) -> None:
        if not args: await self.send(chat_id, "❓ Uso: /aprobar <id>"); return
        await self._do_approval(chat_id, args.strip(), "approved")

    async def cmd_rechazar(self, chat_id: str, args: str) -> None:
        if not args: await self.send(chat_id, "❓ Uso: /rechazar <id>"); return
        await self._do_approval(chat_id, args.strip(), "rejected")

    async def _do_approval(self, chat_id: str, approval_id: str, decision: str) -> None:
        try:
            from apps.core.memory.supabase_client import get_db
            await get_db().resolve_approval(approval_id, decision)
            icon = "✅" if decision == "approved" else "❌"
            action = "aprobada" if decision == "approved" else "rechazada"
            await self.send(chat_id, f"{icon} Acción <code>{approval_id[:8]}</code> {action}.")
        except Exception as exc:
            await self.send(chat_id, f"❌ Error: {exc}")

    async def cmd_limpiar(self, chat_id: str) -> None:
        try:
            from apps.core.memory.redis_client import get_cache
            await get_cache().delete(CONVERSATION_KEY)
            await self.send(chat_id, "🗑 Historial borrado.")
        except Exception as exc:
            await self.send(chat_id, f"❌ Error: {exc}")

    async def cmd_agent_run(self, chat_id: str, agent_key: str, task: str) -> None:
        labels = {"pm":"PMAgent","cfo":"CFOAgent","dev":"DevAgent","marketing":"MarketingAgent","support":"SupportAgent"}
        await self.send(chat_id, f"🤖 <b>Ejecutando {labels.get(agent_key,agent_key)}...</b>\n<i>{task[:100]}</i>\n\nTe aviso al terminar.")
        asyncio.create_task(self._run_agent_async(chat_id, agent_key, task))

    async def _run_agent_async(self, chat_id: str, agent_key: str, task: str) -> None:
        try:
            agent_map = {
                "pm": ("apps.core.agents.pm_agent","PMAgent"),
                "cfo": ("apps.core.agents.cfo_agent","CFOAgent"),
                "dev": ("apps.core.agents.dev_agent","DevAgent"),
                "marketing": ("apps.core.agents.marketing_agent","MarketingAgent"),
                "support": ("apps.core.agents.support_agent","SupportAgent"),
            }
            if agent_key not in agent_map:
                await self.send(chat_id, f"❌ Agente desconocido: {agent_key}"); return
            mod_path, cls_name = agent_map[agent_key]
            mod = importlib.import_module(mod_path)
            agent = getattr(mod, cls_name)()
            await agent.start()
            result = await agent.run({"task": task})
            ok = result.get("success", False)
            parts = []
            for k, v in result.items():
                if k in ("success","agent"): continue
                if isinstance(v, str) and len(v) < 150: parts.append(f"<b>{k}:</b> {v}")
                elif isinstance(v, (int,float)): parts.append(f"<b>{k}:</b> {v}")
                elif isinstance(v, list): parts.append(f"<b>{k}:</b> {len(v)} items")
            summary = "\n".join(parts[:5]) or "Completado sin detalles"
            await self.send(chat_id, f"{'✅' if ok else '❌'} <b>Agente completado</b>\n\n{summary}")
        except Exception as exc:
            logger.error("[TelegramBot] Agent error %s: %s", agent_key, exc)
            await self.send(chat_id, f"❌ Error: {exc}")


    # ── GOOGLE SUITE COMMANDS ─────────────────────────────

    async def cmd_buscar(self, chat_id: str, query: str) -> None:
        if not query or query.strip() in ("", "busca"):
            await self.send(chat_id, "❓ Uso: /buscar <término>\nEjemplo: /buscar mejores nichos digitales 2025")
            return
        await self._send_typing(chat_id)
        try:
            from apps.core.tools.google_suite import GoogleSuite
            g = GoogleSuite()
            # Extraer término limpio del lenguaje natural
            import re
            clean = re.sub(r"(busca|busca en google|googlea|busca información sobre|qué es|quién es|investiga sobre)\s*", "", query.lower(), flags=re.IGNORECASE).strip() or query
            result = await g.web_search(clean, num=5)
            if result.get("success") and result.get("results"):
                lines = [f"🔍 <b>Resultados para:</b> <i>{clean}</i>\n"]
                for i, r in enumerate(result["results"][:5], 1):
                    lines.append(f"{i}. <b>{r['title'][:70]}</b>\n   <a href=\"{r['url']}\">{r['domain']}</a>\n   <i>{r['snippet'][:120]}</i>\n")
                await self.send(chat_id, "\n".join(lines))
            else:
                await self.send(chat_id, f"❌ Sin resultados para: {clean}")
        except Exception as exc:
            await self.send(chat_id, f"❌ Error en búsqueda: {exc}")

    async def cmd_youtube(self, chat_id: str, query: str) -> None:
        if not query or query.strip() in ("", "busca"):
            await self.send(chat_id, "❓ Uso: /youtube <búsqueda>\nEjemplo: /youtube how to make money online")
            return
        await self._send_typing(chat_id)
        try:
            from apps.core.tools.google_suite import GoogleSuite
            g = GoogleSuite()
            import re
            clean = re.sub(r"(busca en youtube|busca video|encuentra video de|muéstrame videos de)\s*", "", query.lower(), flags=re.IGNORECASE).strip() or query
            result = await g.youtube_search(clean, max_results=5, order="viewCount")
            if result.get("success") and result.get("results"):
                lines = [f"📺 <b>YouTube:</b> <i>{clean}</i>\n"]
                for v in result["results"][:5]:
                    vid_id = v.get("id","")
                    url = f"https://youtu.be/{vid_id}" if vid_id else ""
                    lines.append(
                        f"• <b>{v['title'][:70]}</b>\n"
                        f"  📺 {v.get('channel','?')} | {url}\n"
                    )
                await self.send(chat_id, "\n".join(lines))
            else:
                await self.send(chat_id, "❌ Sin resultados de YouTube")
        except Exception as exc:
            await self.send(chat_id, f"❌ Error: {exc}")

    async def cmd_tendencias(self, chat_id: str) -> None:
        await self._send_typing(chat_id)
        try:
            from apps.core.tools.google_suite import GoogleSuite
            import asyncio
            g = GoogleSuite()
            daily, realtime = await asyncio.gather(g.trends_daily("US"), g.trends_realtime("US"), return_exceptions=True)
            lines = ["📈 <b>Trending Topics — Google</b>\n"]
            if isinstance(realtime, dict) and realtime.get("realtime_trends"):
                lines.append("<b>🔴 En tiempo real:</b>")
                for t in realtime["realtime_trends"][:8]:
                    lines.append(f"  • {t.get('title','')[:60]}")
                lines.append("")
            if isinstance(daily, dict) and daily.get("trends"):
                lines.append("<b>📅 Tendencias del día:</b>")
                for t in daily["trends"][:8]:
                    lines.append(f"  • {t.get('topic','')[:50]} ({t.get('traffic','')} búsquedas)")
            await self.send(chat_id, "\n".join(lines) if len(lines) > 1 else "❌ Sin tendencias disponibles")
        except Exception as exc:
            await self.send(chat_id, f"❌ Error: {exc}")

    async def cmd_traducir(self, chat_id: str, args: str) -> None:
        if not args:
            await self.send(chat_id, "❓ Uso: /traducir <idioma> <texto>\nEjemplo: /traducir en Hola mundo\nIdiomas: en, fr, de, pt, ja, zh, ar, it, ru, ko")
            return
        await self._send_typing(chat_id)
        try:
            parts = args.strip().split(maxsplit=1)
            if len(parts) < 2:
                await self.send(chat_id, "❓ Uso: /traducir <idioma> <texto>\nEjemplo: /traducir en Buenos días")
                return
            target_lang = parts[0].lower()[:2]
            text = parts[1]
            from apps.core.tools.google_suite import GoogleSuite
            g = GoogleSuite()
            detect = await g.detect_language(text[:200])
            source = detect.get("language", "es")[:2] if detect.get("success") else "es"
            result = await g.translate(text, target=target_lang, source=source)
            if result.get("success"):
                lang_names = {"en":"inglés","fr":"francés","de":"alemán","pt":"portugués","ja":"japonés",
                              "zh":"chino","ar":"árabe","it":"italiano","ru":"ruso","ko":"coreano","es":"español"}
                await self.send(chat_id,
                    f"🌐 <b>Traducción</b> ({lang_names.get(source,source)} → {lang_names.get(target_lang,target_lang)})\n\n"
                    f"<i>Original:</i> {text[:200]}\n\n"
                    f"<b>Traducción:</b> {result['translated']}")
            else:
                await self.send(chat_id, f"❌ Error traduciendo: {result.get('error','')}")
        except Exception as exc:
            await self.send(chat_id, f"❌ Error: {exc}")

    async def cmd_pagespeed(self, chat_id: str, url: str) -> None:
        if not url or not url.startswith("http"):
            await self.send(chat_id, "❓ Uso: /pagespeed <url>\nEjemplo: /pagespeed https://example.com")
            return
        await self.send(chat_id, f"⏳ Analizando velocidad de {url}...")
        try:
            from apps.core.tools.google_suite import GoogleSuite
            import asyncio
            g = GoogleSuite()
            mobile, desktop = await asyncio.gather(g.pagespeed_analyze(url, "mobile"), g.pagespeed_analyze(url, "desktop"), return_exceptions=True)
            lines = [f"⚡ <b>PageSpeed:</b> {url}\n"]
            for label, data in [("📱 Móvil", mobile), ("🖥 Desktop", desktop)]:
                if isinstance(data, dict) and data.get("success"):
                    s = data.get("scores",{})
                    m = data.get("metrics",{})
                    lines.append(f"<b>{label}:</b>")
                    lines.append(f"  Performance: {s.get('performance',0)}/100 | SEO: {s.get('seo',0)}/100")
                    lines.append(f"  LCP: {m.get('lcp','')} | FCP: {m.get('fcp','')} | CLS: {m.get('cls','')}\n")
            await self.send(chat_id, "\n".join(lines))
        except Exception as exc:
            await self.send(chat_id, f"❌ Error: {exc}")

    async def cmd_ocr(self, chat_id: str, url: str) -> None:
        if not url:
            await self.send(chat_id, "❓ Uso: /ocr <url_imagen>\nExtrae texto de cualquier imagen.")
            return
        await self._send_typing(chat_id)
        try:
            from apps.core.tools.google_suite import GoogleSuite
            g = GoogleSuite()
            result = await g.vision_ocr(image_url=url)
            if result.get("success") and result.get("text"):
                await self.send(chat_id, f"📝 <b>Texto extraído:</b>\n\n<code>{result['text'][:3000]}</code>")
            else:
                await self.send(chat_id, "❌ No se encontró texto en la imagen.")
        except Exception as exc:
            await self.send(chat_id, f"❌ Error: {exc}")

    # ── HUGGINGFACE SUITE COMMANDS ────────────────────────

    async def cmd_imagen(self, chat_id: str, prompt: str) -> None:
        if not prompt or prompt.strip() in ("imagen", "genera", "dibuja"):
            await self.send(chat_id, "❓ Uso: /imagen <descripción>\nEjemplo: /imagen professional product photo of a digital course about fitness")
            return
        await self.send(chat_id, f"🎨 <b>Generando imagen con FLUX.1...</b>\n<i>{prompt[:80]}</i>\n\n⏳ Puede tomar 15-30 segundos.")
        try:
            from apps.core.tools.huggingface_suite import HuggingFaceSuite
            import io
            hf = HuggingFaceSuite()
            result = await hf.generate_image(prompt, model="black-forest-labs/FLUX.1-schnell")
            if result.get("success") and result.get("image_bytes"):
                photo_file = io.BytesIO(result["image_bytes"])
                photo_file.name = "aria_generated.png"
                files = {"photo": ("aria_generated.png", photo_file, "image/png")}
                payload = {"chat_id": chat_id, "caption": f"🎨 <b>ARIA generó:</b> {prompt[:100]}"}
                res = await self._http.post(f"{self._base_url}/sendPhoto", data=payload, files=files)
                if res.status_code != 200:
                    await self.send(chat_id, f"❌ Error enviando imagen: {res.text[:200]}")
            else:
                await self.send(chat_id, "❌ No se pudo generar la imagen. Verifica que HF_TOKEN esté configurado.")
        except Exception as exc:
            logger.error("[TelegramBot] cmd_imagen error: %s", exc)
            await self.send(chat_id, f"❌ Error generando imagen: {exc}")

    async def cmd_resumir(self, chat_id: str, text: str) -> None:
        if not text or len(text) < 10:
            await self.send(chat_id, "❓ Uso: /resumir <texto largo>\nEjemplo: /resumir <artículo o contenido>")
            return
        await self._send_typing(chat_id)
        try:
            from apps.core.tools.huggingface_suite import HuggingFaceSuite
            hf = HuggingFaceSuite()
            # Detectar idioma para usar modelo correcto
            from apps.core.tools.google_suite import GoogleSuite
            g = GoogleSuite()
            lang_res = await g.detect_language(text[:100])
            lang = lang_res.get("language","es")[:2] if lang_res.get("success") else "es"
            result = await hf.summarize(text, max_length=200, min_length=50, language=lang)
            if result.get("success"):
                await self.send(chat_id,
                    f"📄 <b>Resumen</b> ({len(text)} → {len(result['summary'])} chars)\n\n"
                    f"{result['summary']}")
            else:
                await self.send(chat_id, f"❌ Error: {result.get('error','No se pudo resumir')}")
        except Exception as exc:
            await self.send(chat_id, f"❌ Error: {exc}")

    async def cmd_sentimiento(self, chat_id: str, text: str) -> None:
        if not text:
            await self.send(chat_id, "❓ Uso: /sentimiento <texto>\nEjemplo: /sentimiento Este producto es increíble")
            return
        await self._send_typing(chat_id)
        try:
            from apps.core.tools.huggingface_suite import HuggingFaceSuite
            hf = HuggingFaceSuite()
            result = await hf.analyze_sentiment(text, multilingual=True)
            if result.get("success"):
                icons = {"positivo": "😊 POSITIVO", "negativo": "😠 NEGATIVO", "neutro": "😐 NEUTRO"}
                label = icons.get(result.get("sentiment","neutro"), result.get("sentiment",""))
                conf = result.get("confidence", 0)
                scores = result.get("all_scores", {})
                scores_txt = " | ".join(f"{k}: {v}" for k, v in scores.items())
                await self.send(chat_id,
                    f"🧠 <b>Análisis de Sentimiento</b>\n\n"
                    f"Texto: <i>{text[:150]}</i>\n\n"
                    f"Resultado: <b>{label}</b>\n"
                    f"Confianza: {conf*100:.1f}%\n"
                    f"Scores: <code>{scores_txt}</code>")
            else:
                await self.send(chat_id, f"❌ Error: {result.get('error','')}")
        except Exception as exc:
            await self.send(chat_id, f"❌ Error: {exc}")

    async def cmd_codigo(self, chat_id: str, args: str) -> None:
        if not args:
            await self.send(chat_id, "❓ Uso: /codigo <descripción de lo que necesitas>\nEjemplo: /codigo función Python que convierte CSV a JSON")
            return
        await self.send(chat_id, f"💻 <b>Generando código con Qwen2.5-Coder...</b>\n<i>{args[:80]}</i>")
        try:
            from apps.core.tools.huggingface_suite import HuggingFaceSuite
            hf = HuggingFaceSuite()
            # Detectar lenguaje de programación del args
            lang_map = {"python":"python","javascript":"javascript","js":"javascript","java":"java",
                        "typescript":"typescript","ts":"typescript","rust":"rust","go":"go","sql":"sql",
                        "html":"html","css":"css","bash":"bash","shell":"bash","php":"php","ruby":"ruby"}
            detected_lang = "python"
            for kw, lang in lang_map.items():
                if kw in args.lower():
                    detected_lang = lang
                    break
            result = await hf.generate_code(args, language=detected_lang)
            if result.get("success") and result.get("code"):
                code = result["code"][:3500]
                await self.send(chat_id,
                    f"💻 <b>Código generado ({detected_lang}):</b>\n\n"
                    f"<pre><code>{code}</code></pre>")
            else:
                await self.send(chat_id, f"❌ Error generando código: {result.get('error','')}")
        except Exception as exc:
            await self.send(chat_id, f"❌ Error: {exc}")

    async def cmd_capacidades(self, chat_id: str) -> None:
        msg = (
            "⚡ <b>ARIA AI — Capacidades Completas</b>\n\n"
            "<b>🔍 GOOGLE SUITE (11 APIs)</b>\n"
            "  • Búsqueda web (Custom Search)\n"
            "  • Búsqueda de imágenes\n"
            "  • Vision AI (OCR, objetos, logos, colores)\n"
            "  • NLP (sentimiento, entidades, categorías)\n"
            "  • Traducción (133 idiomas)\n"
            "  • Text-to-Speech (400+ voces)\n"
            "  • Speech-to-Text (99 idiomas)\n"
            "  • YouTube completo (search, stats, trending, comments)\n"
            "  • Knowledge Graph\n"
            "  • PageSpeed Insights (SEO)\n"
            "  • Google Trends en tiempo real\n\n"
            "<b>🤗 HUGGINGFACE (19 capacidades)</b>\n"
            "  • Generación de imágenes FLUX.1-schnell / SDXL\n"
            "  • Traducción (Helsinki-NLP, 1000+ pares)\n"
            "  • Resumen automático (BART, Pegasus, mT5)\n"
            "  • Análisis de sentimiento multilingüe\n"
            "  • Clasificación zero-shot (cualquier categoría)\n"
            "  • Reconocimiento de entidades (NER)\n"
            "  • Question Answering extractivo\n"
            "  • Embeddings + búsqueda semántica\n"
            "  • Text-to-Speech Bark (voces realistas)\n"
            "  • Speech-to-Text Whisper large-v3\n"
            "  • Image Captioning (BLIP-2)\n"
            "  • Detección de objetos (DETR, YOLO)\n"
            "  • Clasificación de imágenes (ViT)\n"
            "  • Generación de código (Qwen2.5-Coder)\n"
            "  • Detección de idioma (176 idiomas)\n"
            "  • Clasificación de audio / emociones\n"
            "  • Estimación de profundidad\n"
            "  • Embeddings semánticos\n"
            "  • Fill-mask / completar texto\n\n"
            "<b>🤖 AGENTES INTEGRADOS</b>\n"
            "  • PMAgent: investigación mercado completa\n"
            "  • MarketingAgent: Buffer + Mailchimp + Google\n"
            "  • DevAgent: código con Qwen2.5-Coder\n"
            "  • SupportAgent: soporte 133 idiomas\n"
            "  • CFOAgent: ingresos y finanzas\n"
            "  • EvolutionAgent: auto-mejora continua"
        )
        await self.send(chat_id, msg)

    # ── MEMORIA ───────────────────────────────────────────

    async def _get_conversation_history(self) -> list[dict]:
        try:
            from apps.core.memory.redis_client import get_cache
            raw = await get_cache().get(CONVERSATION_KEY)
            return json.loads(raw) if raw else []
        except Exception: return []

    async def _save_conversation_history(self, history: list[dict]) -> None:
        try:
            from apps.core.memory.redis_client import get_cache
            await get_cache().set(CONVERSATION_KEY, json.dumps(history, ensure_ascii=False), ttl_seconds=CONVERSATION_TTL)
        except Exception: pass

    # ── TELEGRAM API ──────────────────────────────────────

    async def send(self, chat_id: str, text: str, reply_markup: Optional[dict] = None) -> bool:
        if len(text) > 4000: text = text[:3997] + "..."
        try:
            payload: dict[str, Any] = {"chat_id": chat_id, "text": text, "parse_mode": "HTML", "disable_web_page_preview": True}
            if reply_markup: payload["reply_markup"] = reply_markup
            res = await self._http.post(f"{self._base_url}/sendMessage", json=payload)
            return res.status_code == 200
        except Exception as exc:
            logger.error("[TelegramBot] Send error: %s", exc); return False

    async def set_webhook(self, url: str) -> bool:
        try:
            res = await self._http.post(f"{self._base_url}/setWebhook",
                json={"url": url, "allowed_updates": ["message","edited_message","callback_query"]})
            return res.status_code == 200 and res.json().get("ok", False)
        except Exception as exc:
            logger.error("[TelegramBot] Webhook error: %s", exc); return False

    async def _send_typing(self, chat_id: str) -> None:
        try: await self._http.post(f"{self._base_url}/sendChatAction", json={"chat_id": chat_id, "action": "typing"})
        except Exception: pass

    async def send_to_owner(self, message: str) -> bool:
        return await self.send(self._owner_id, message)


_bot_instance: Optional[AriaTelegramBot] = None
def get_bot() -> AriaTelegramBot:
    global _bot_instance
    if _bot_instance is None:
        _bot_instance = AriaTelegramBot()
    return _bot_instance

def _now_str() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
