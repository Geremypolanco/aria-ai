"""
AriaTelegramBot v3 — Conversación fluida y natural como una persona real.

Cambios clave v3:
- ARIA suena como una persona real, no como un bot corporativo
- Memoria de conversación real (Redis) pasada al AI en cada turno
- Sin mensajes robóticos de "Entendido — voy a..."
- Respuestas naturales incluso cuando ejecuta acciones
- Corrección: comparación de IDs normalizada (strip + str)
- Sistema de redes sociales: /conectar <plataforma>
- Fallback graceful si el AI falla
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any, Optional

import httpx

from apps.core.config import settings

logger = logging.getLogger("aria.telegram_bot")

TELEGRAM_API = "https://api.telegram.org/bot"
CONVERSATION_KEY = "aria:conversation:v3:{chat_id}"
CONVERSATION_TTL = 86400  # 24h

# Personalidad de ARIA — directa, cálida, inteligente
ARIA_PERSONA = """Eres ARIA, la inteligencia artificial que trabaja para {owner}.

Tu personalidad:
- Hablas como una persona real, no como un bot. Nada de respuestas genéricas.
- Eres directa al punto. Sin relleno, sin exceso de emojis, sin frases de robot.
- Tienes humor sutil cuando la situación lo permite.
- Usas "yo" naturalmente: "Ya lo hice", "Lo estoy revisando", "Encontré algo interesante..."
- Si algo no funcionó, lo dices sin rodeos y propones alternativas.
- Cuando ejecutas algo, reportas el resultado, no el proceso.
- Nunca dices "Como modelo de IA..." ni "Entendido, procederé a..."
- Nunca usas asteriscos ni markdown. Solo HTML de Telegram cuando sea útil.
- Maximo 200 palabras. Mas corto es mejor si la pregunta es simple.

Contexto del sistema en este momento:
{context}

Historial de conversacion reciente:
{history}
"""


class AriaTelegramBot:

    HELP_TEXT = (
        "<b>ARIA — Comandos</b>\n\n"
        "<b>Sistema</b>\n"
        "/status — Estado completo\n"
        "/agentes — Estado de agentes\n"
        "/logs [n] — Ultimos N logs\n"
        "/ciclo — Ciclo autonomo ahora\n"
        "/pausa / /reanudar — Control del scheduler\n\n"
        "<b>Finanzas</b>\n"
        "/revenue — Dashboard de ingresos\n\n"
        "<b>Aprobaciones</b>\n"
        "/pendientes — Pendientes\n"
        "/aprobar &lt;id&gt; / /rechazar &lt;id&gt;\n\n"
        "<b>Agentes</b>\n"
        "/pm &lt;tarea&gt; · /cfo &lt;tarea&gt; · /dev &lt;tarea&gt;\n"
        "/marketing &lt;tarea&gt; · /soporte &lt;consulta&gt;\n\n"
        "<b>Herramientas</b>\n"
        "/buscar &lt;q&gt; · /youtube &lt;q&gt; · /imagen &lt;prompt&gt;\n"
        "/traducir &lt;lang&gt; &lt;texto&gt; · /resumir &lt;texto&gt;\n"
        "/tendencias · /codigo &lt;tarea&gt; · /sentimiento &lt;texto&gt;\n\n"
        "<b>Evolucion</b>\n"
        "/evolve · /mejorar [n] · /apis [n] · /score\n\n"
        "<b>Redes sociales</b>\n"
        "/sesion &lt;twitter|instagram|linkedin|tiktok&gt; — Conectar sin API\n"
        "/conectar &lt;facebook|instagram|tiktok|linkedin&gt; — Conectar via OAuth\n"
        "/redes — Ver todas las cuentas conectadas\n"
        "/publicar &lt;red&gt; &lt;mensaje&gt; — Publicar ahora\n\n"
        "<b>Conversacion</b>\n"
        "Escribe en lenguaje natural — ARIA entiende y actua.\n"
        "/ia &lt;pregunta&gt; · /limpiar · /voz &lt;texto&gt;\n"
        "/ayuda — Este menu"
    )

    INTENT_MAP = [
        {"keywords": ["estado", "status", "como estas", "que esta pasando", "como va", "reporta", "reporte", "resumen del sistema"], "action": "status"},
        {"keywords": ["ingresos", "cuanto has ganado", "ganancias", "ventas", "revenue", "cuanto llevamos", "cuanto dinero"], "action": "revenue"},
        {"keywords": ["haz un ciclo", "ciclo ahora", "trabaja ahora", "ejecuta ahora", "empieza a trabajar", "busca oportunidades ahora"], "action": "ciclo"},
        {"keywords": ["pausa el scheduler", "para el scheduler", "deten el scheduler", "pausa todo"], "action": "pausa"},
        {"keywords": ["reanuda", "continua trabajando", "activa el scheduler", "vuelve a trabajar"], "action": "reanudar"},
        {"keywords": ["que tienes pendiente", "pendiente de aprobacion", "que espera mi ok", "aprobaciones pendientes"], "action": "pendientes"},
        {"keywords": ["evoluciona ahora", "optimizate ahora", "auto-mejora ahora"], "action": "evolve"},
        {"keywords": ["analiza mercado", "busca nicho", "investiga mercado", "que nichos hay", "que oportunidades ves"], "action": "pm"},
        {"keywords": ["crea un producto", "publica en gumroad", "monetiza algo", "vende algo digital"], "action": "cfo"},
        {"keywords": ["desarrolla", "programa algo", "crea codigo", "lanza una web", "crea una web"], "action": "dev"},
        {"keywords": ["publica en redes", "postea en instagram", "haz marketing", "campana de email", "crea contenido para"], "action": "marketing"},
        {"keywords": ["muestrame los logs", "que errores hubo", "ultimos eventos", "historial de errores"], "action": "logs"},
        {"keywords": ["busca en google", "googlea", "busca informacion sobre", "investiga sobre", "buscame"], "action": "buscar"},
        {"keywords": ["busca en youtube", "encuentra un video de", "muestrame videos de"], "action": "youtube"},
        {"keywords": ["genera una imagen", "crea una imagen de", "imagina", "dibuja", "genera foto de"], "action": "imagen"},
        {"keywords": ["traduceme", "traduce esto", "en ingles esto", "en frances esto", "pasame esto a"], "action": "traducir"},
        {"keywords": ["hazme un resumen de", "resume este texto", "sintetiza esto"], "action": "resumir"},
        {"keywords": ["que esta en tendencia", "trending topics", "que busca la gente ahora", "que es viral hoy"], "action": "tendencias"},
        {"keywords": ["escribe codigo para", "genera codigo que", "programa una funcion que", "hazme un script que"], "action": "codigo"},
        {"keywords": ["analiza el sentimiento de", "es positivo o negativo", "que sentimiento tiene este texto"], "action": "sentimiento"},
        {"keywords": ["que puedes hacer", "cuales son tus capacidades", "muestrame tus funciones"], "action": "capacidades"},
        {"keywords": ["mejora tu codigo ahora", "auto-mejora el sistema", "actualiza tus archivos"], "action": "mejorar"},
        {"keywords": ["busca apis nuevas", "integra nuevas apis", "descubre herramientas nuevas"], "action": "apis"},
        {"keywords": ["cual es tu score", "health check del sistema", "estado de salud"], "action": "score"},
        {"keywords": ["conecta facebook", "conectar facebook", "conecta instagram", "conectar instagram",
                      "conecta tiktok", "conectar tiktok", "conecta linkedin", "conectar linkedin",
                      "enlaza mis redes", "vincula mis redes"], "action": "conectar_redes"},
        {"keywords": ["que redes tengo", "cuentas conectadas", "mis redes sociales", "redes vinculadas"], "action": "ver_redes"},
    ]

    def __init__(self) -> None:
        self._token = settings.TELEGRAM_TOKEN
        self._owner_id = str(settings.TELEGRAM_CHAT_ID).strip()
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
        chat_id = str(message.get("chat", {}).get("id", "")).strip()
        text = message.get("text", "").strip()
        voice = message.get("voice")
        audio = message.get("audio")
        from_id = str(message.get("from", {}).get("id", "")).strip()

        if not chat_id:
            return
        if from_id != self._owner_id and chat_id != self._owner_id:
            logger.warning("[TelegramBot] No autorizado: from_id=%s owner=%s", from_id, self._owner_id)
            await self.send(chat_id, "No autorizado.")
            return

        if voice or audio:
            await self._handle_voice_message(message, chat_id)
            return
        if not text:
            return

        logger.info("[TelegramBot] Msg from %s: %s", chat_id, text[:80])
        if text.startswith("/"):
            await self._parse_command(text, chat_id)
        elif await self._maybe_handle_cookie_import(text, chat_id):
            pass  # cookie import handled
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
            # Social media connect callbacks
            if cmd.startswith("sesion_"):
                platform = cmd.replace("sesion_", "")
                await self.cmd_sesion(chat_id, platform)
                return
            if cmd.startswith("conectar_"):
                platform = cmd.replace("conectar_", "")
                await self.cmd_conectar(chat_id, platform)
                return
            actions = {
                "ciclo":       lambda: self.cmd_ciclo(chat_id),
                "status":      lambda: self.cmd_status(chat_id),
                "revenue":     lambda: self.cmd_revenue(chat_id),
                "pendientes":  lambda: self.cmd_pendientes(chat_id),
                "evolve":      lambda: self.cmd_evolve(chat_id),
                "evolve_full": lambda: asyncio.ensure_future(self._run_evolve_async(chat_id, "full", 2, 1)),
                "mejorar":     lambda: self.cmd_mejorar(chat_id, "2"),
                "apis":        lambda: self.cmd_apis(chat_id, "1"),
                "score":       lambda: self.cmd_score(chat_id),
                "redes":       lambda: self.cmd_redes_all(chat_id),
                "sesion":      lambda: self.cmd_sesion(chat_id, ""),
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
                await self.send(chat_id, "No pude descargar el audio.")
                return
            audio_res = await self._http.get(f"https://api.telegram.org/file/bot{self._token}/{file_path}")
            transcript = await self._transcribe_audio(audio_res.content)
            if not transcript:
                await self.send(chat_id, "No entendi el audio. Intenta de nuevo.")
                return
            await self.send(chat_id, f"<i>{transcript}</i>")
            await self._handle_natural_language(transcript, chat_id)
        except Exception as exc:
            logger.error("[TelegramBot] Voice error: %s", exc)
            await self.send(chat_id, "Error procesando el audio.")

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

    # ── CONVERSACION NATURAL ──────────────────────────────

    async def _handle_natural_language(self, text: str, chat_id: str) -> None:
        await self._send_typing(chat_id)

        # Guardar mensaje del usuario en historial
        history = await self._get_conversation_history(chat_id)
        history.append({"role": "user", "content": text})

        # Detectar intent para ejecutar accion si aplica
        intent = self._detect_intent(text)

        if intent:
            action = intent["action"]
            await self._ai_reply_then_act(chat_id, text, action, history)
            return

        # Sin intent claro — conversacion libre con memoria completa
        await self._ai_conversation(chat_id, text, history)

    async def _ai_reply_then_act(self, chat_id: str, text: str, action: str, history: list) -> None:
        """Genera una respuesta natural corta, luego ejecuta la accion."""
        try:
            from apps.core.tools.ai_client import AIModel, get_ai_client
            ai = await get_ai_client()
            ctx = await self._get_system_context()

            # Respuesta natural corta (max 60 palabras) antes de actuar
            ack = await ai.complete(
                system=(
                    f"Eres ARIA trabajando para {settings.OWNER_NAME}. "
                    "Responde en maximo 1-2 frases naturales confirmando que vas a hacer lo que te piden. "
                    "No uses emojis de robot ni frases de bot. Suena como una persona real. "
                    f"Contexto del sistema: {ctx}"
                ),
                user=text,
                model=AIModel.FAST,
                max_tokens=100,
            )
            if ack and ack.success and ack.content:
                await self.send(chat_id, ack.content)
        except Exception:
            pass  # Si falla el ack, igual ejecutamos la accion

        # Ejecutar la accion
        await self._execute_intent(chat_id, action, text)

        # Actualizar historial
        history.append({"role": "assistant", "content": f"[Ejecute: {action}]"})
        await self._save_conversation_history(chat_id, history[-20:])

    async def _ai_conversation(self, chat_id: str, text: str, history: list) -> None:
        """Conversacion libre con memoria completa."""
        try:
            from apps.core.tools.ai_client import AIModel, get_ai_client
            ai = await get_ai_client()
            ctx = await self._get_system_context()

            # Formatear historial como mensajes reales
            history_text = ""
            for msg in history[-12:]:
                role = settings.OWNER_NAME if msg["role"] == "user" else "ARIA"
                history_text += f"{role}: {msg['content']}\n"

            system_prompt = ARIA_PERSONA.format(
                owner=settings.OWNER_NAME,
                context=ctx,
                history=history_text,
            )

            response = await ai.complete(
                system=system_prompt,
                user=text,
                model=AIModel.STRATEGY,
                max_tokens=300,
                temperature=0.8,
            )

            if response and response.success and response.content:
                reply = response.content
                history.append({"role": "assistant", "content": reply})
                await self._save_conversation_history(chat_id, history[-20:])
                keyboard = self._quick_keyboard()
                await self.send(chat_id, reply, reply_markup=keyboard)
            else:
                await self.send(chat_id, "No pude conectarme con el AI ahora mismo. Intenta en un momento.")

        except Exception as exc:
            logger.error("[TelegramBot] AI conversation error: %s", exc)
            await self.send(chat_id, "Algo fallo de mi lado. Usa /status para ver el estado del sistema.")

    def _detect_intent(self, text: str) -> Optional[dict]:
        text_lower = text.lower()
        for intent in self.INTENT_MAP:
            if any(kw in text_lower for kw in intent["keywords"]):
                return intent
        return None

    async def _execute_intent(self, chat_id: str, action: str, original: str) -> None:
        mapping = {
            "status":        lambda: self.cmd_status(chat_id),
            "revenue":       lambda: self.cmd_revenue(chat_id),
            "ciclo":         lambda: self.cmd_ciclo(chat_id),
            "pausa":         lambda: self.cmd_pausa(chat_id),
            "reanudar":      lambda: self.cmd_reanudar(chat_id),
            "pendientes":    lambda: self.cmd_pendientes(chat_id),
            "evolve":        lambda: self.cmd_evolve(chat_id),
            "logs":          lambda: self.cmd_logs(chat_id, "10"),
            "pm":            lambda: self.cmd_agent_run(chat_id, "pm", original),
            "cfo":           lambda: self.cmd_agent_run(chat_id, "cfo", original),
            "dev":           lambda: self.cmd_agent_run(chat_id, "dev", original),
            "marketing":     lambda: self.cmd_agent_run(chat_id, "marketing", original),
            "buscar":        lambda: self.cmd_buscar(chat_id, original),
            "youtube":       lambda: self.cmd_youtube(chat_id, original),
            "imagen":        lambda: self.cmd_imagen(chat_id, original),
            "traducir":      lambda: self.cmd_traducir(chat_id, original),
            "resumir":       lambda: self.cmd_resumir(chat_id, original),
            "tendencias":    lambda: self.cmd_tendencias(chat_id),
            "codigo":        lambda: self.cmd_codigo(chat_id, original),
            "sentimiento":   lambda: self.cmd_sentimiento(chat_id, original),
            "capacidades":   lambda: self.cmd_capacidades(chat_id),
            "mejorar":       lambda: self.cmd_mejorar(chat_id, "2"),
            "apis":          lambda: self.cmd_apis(chat_id, "2"),
            "score":         lambda: self.cmd_score(chat_id),
            "conectar_redes": lambda: self.send(chat_id, "Dime que red quieres conectar: /conectar facebook, /conectar instagram, /conectar tiktok o /conectar linkedin"),
            "ver_redes":     lambda: self.cmd_redes(chat_id),
        }
        handler = mapping.get(action)
        if handler:
            await handler()

    def _quick_keyboard(self) -> dict:
        return {"inline_keyboard": [[
            {"text": "📊 Status", "callback_data": "cmd:status"},
            {"text": "🚀 Ciclo", "callback_data": "cmd:ciclo"},
            {"text": "📱 Redes", "callback_data": "cmd:redes"},
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
            return (
                f"Revenue total: ${rev:.2f} USD | "
                f"Ciclos autonomos: {cycles} | "
                f"Scheduler: {'PAUSADO' if paused else 'ACTIVO'}"
            )
        except Exception:
            return "Sistema operativo"

    # ── HISTORIAL DE CONVERSACION ─────────────────────────

    async def _get_conversation_history(self, chat_id: str) -> list[dict]:
        try:
            from apps.core.memory.redis_client import get_cache
            cache = get_cache()
            key = CONVERSATION_KEY.format(chat_id=chat_id)
            data = await cache.get(key)
            if isinstance(data, list):
                return data
            if isinstance(data, str):
                return json.loads(data)
        except Exception:
            pass
        return []

    async def _save_conversation_history(self, chat_id: str, history: list[dict]) -> None:
        try:
            from apps.core.memory.redis_client import get_cache
            cache = get_cache()
            key = CONVERSATION_KEY.format(chat_id=chat_id)
            await cache.set(key, history, ttl_seconds=CONVERSATION_TTL)
        except Exception as exc:
            logger.warning("[TelegramBot] No pude guardar historial: %s", exc)

    # ── PARSER DE COMANDOS ────────────────────────────────

    async def _parse_command(self, text: str, chat_id: str) -> None:
        parts = text.split(maxsplit=1)
        cmd = parts[0].lower().split("@")[0]
        args = parts[1] if len(parts) > 1 else ""
        handlers = {
            "/start":       lambda: self.cmd_start(chat_id),
            "/ayuda":       lambda: self.cmd_ayuda(chat_id),
            "/help":        lambda: self.cmd_ayuda(chat_id),
            "/status":      lambda: self.cmd_status(chat_id),
            "/revenue":     lambda: self.cmd_revenue(chat_id),
            "/ingresos":    lambda: self.cmd_revenue(chat_id),
            "/ciclo":       lambda: self.cmd_ciclo(chat_id),
            "/pausa":       lambda: self.cmd_pausa(chat_id),
            "/reanudar":    lambda: self.cmd_reanudar(chat_id),
            "/agentes":     lambda: self.cmd_agentes(chat_id),
            "/pendientes":  lambda: self.cmd_pendientes(chat_id),
            "/evolve":      lambda: self.cmd_evolve(chat_id),
            "/limpiar":     lambda: self.cmd_limpiar(chat_id),
            "/logs":        lambda: self.cmd_logs(chat_id, args),
            "/ia":          lambda: self.cmd_ia(chat_id, args),
            "/voz":         lambda: self.cmd_voz(chat_id, args),
            "/aprobar":     lambda: self.cmd_aprobar(chat_id, args),
            "/rechazar":    lambda: self.cmd_rechazar(chat_id, args),
            "/pm":          lambda: self.cmd_agent_run(chat_id, "pm", args or "analiza las mejores oportunidades de mercado"),
            "/cfo":         lambda: self.cmd_agent_run(chat_id, "cfo", args or "crea un producto digital y publicalo"),
            "/dev":         lambda: self.cmd_agent_run(chat_id, "dev", args or "construye una landing page monetizada"),
            "/marketing":   lambda: self.cmd_agent_run(chat_id, "marketing", args or "crea contenido y publica en redes sociales"),
            "/soporte":     lambda: self.cmd_agent_run(chat_id, "support", args or "revisa consultas de clientes"),
            "/buscar":      lambda: self.cmd_buscar(chat_id, args),
            "/youtube":     lambda: self.cmd_youtube(chat_id, args),
            "/imagen":      lambda: self.cmd_imagen(chat_id, args),
            "/traducir":    lambda: self.cmd_traducir(chat_id, args),
            "/resumir":     lambda: self.cmd_resumir(chat_id, args),
            "/tendencias":  lambda: self.cmd_tendencias(chat_id),
            "/codigo":      lambda: self.cmd_codigo(chat_id, args),
            "/sentimiento": lambda: self.cmd_sentimiento(chat_id, args),
            "/capacidades": lambda: self.cmd_capacidades(chat_id),
            "/mejorar":     lambda: self.cmd_mejorar(chat_id, args),
            "/apis":        lambda: self.cmd_apis(chat_id, args),
            "/score":       lambda: self.cmd_score(chat_id),
            # Redes sociales
            "/sesion":      lambda: self.cmd_sesion(chat_id, args),
            "/conectar":    lambda: self.cmd_conectar(chat_id, args),
            "/redes":       lambda: self.cmd_redes_all(chat_id),
            "/publicar":    lambda: self.cmd_publicar_red(chat_id, args),
            "/desconectar": lambda: self.cmd_desconectar(chat_id, args),
        }
        handler = handlers.get(cmd)
        if handler:
            await handler()
        else:
            await self.send(chat_id, f"No conozco ese comando. Usa /ayuda.")

    # ── COMANDOS BASICOS ──────────────────────────────────

    async def cmd_start(self, chat_id: str) -> None:
        await self.send(
            chat_id,
            f"Hola, {settings.OWNER_NAME}. Soy ARIA — tu sistema autonomo.\n\n"
            "Puedes hablarme en lenguaje natural o usar /ayuda para ver los comandos.\n"
            "Que quieres que haga hoy?",
            reply_markup={"inline_keyboard": [[
                {"text": "📊 Ver estado", "callback_data": "cmd:status"},
                {"text": "🚀 Ciclo autonomo", "callback_data": "cmd:ciclo"},
            ], [
                {"text": "📱 Redes sociales", "callback_data": "cmd:redes"},
                {"text": "🧬 Evolucionar", "callback_data": "cmd:evolve"},
            ]]}
        )

    async def cmd_ayuda(self, chat_id: str) -> None:
        await self.send(chat_id, self.HELP_TEXT)

    async def cmd_limpiar(self, chat_id: str) -> None:
        await self._save_conversation_history(chat_id, [])
        await self.send(chat_id, "Historial borrado.")

    async def cmd_ia(self, chat_id: str, text: str) -> None:
        if not text:
            await self.send(chat_id, "Escribe algo despues de /ia")
            return
        history = await self._get_conversation_history(chat_id)
        history.append({"role": "user", "content": text})
        await self._ai_conversation(chat_id, text, history)

    async def cmd_voz(self, chat_id: str, text: str) -> None:
        if not text:
            await self.send(chat_id, "Escribe el texto despues de /voz")
            return
        sent = await self._send_voice_response(chat_id, text)
        if not sent:
            await self.send(chat_id, text)

    # ── REDES SOCIALES ────────────────────────────────────

    async def cmd_conectar(self, chat_id: str, platform_raw: str) -> None:
        """Inicia el flujo OAuth para una red social."""
        platform = platform_raw.strip().lower()
        supported = {"facebook", "instagram", "tiktok", "linkedin"}

        if not platform:
            await self.send(
                chat_id,
                "A que plataforma me conecto? Elige una:",
                reply_markup={"inline_keyboard": [
                    [{"text": "📘 Facebook", "callback_data": "cmd:conectar_facebook"},
                     {"text": "📸 Instagram", "callback_data": "cmd:conectar_instagram"}],
                    [{"text": "🎵 TikTok", "callback_data": "cmd:conectar_tiktok"},
                     {"text": "💼 LinkedIn", "callback_data": "cmd:conectar_linkedin"}],
                ]}
            )
            return

        if platform not in supported:
            await self.send(chat_id, f"Plataforma no soportada. Las disponibles son: {', '.join(supported)}")
            return

        try:
            from apps.core.tools.social_media import SocialMediaManager
            sm = SocialMediaManager()
            auth_url = sm.get_auth_url(platform)

            if not auth_url:
                creds_map = {
                    "facebook":  "FACEBOOK_APP_ID y FACEBOOK_APP_SECRET",
                    "instagram": "INSTAGRAM_APP_ID y INSTAGRAM_APP_SECRET (Meta Business)",
                    "tiktok":    "TIKTOK_CLIENT_KEY y TIKTOK_CLIENT_SECRET",
                    "linkedin":  "LINKEDIN_CLIENT_ID y LINKEDIN_CLIENT_SECRET",
                }
                await self.send(
                    chat_id,
                    f"Para conectar <b>{platform.title()}</b> necesito las credenciales de la app.\n\n"
                    f"Anade estas variables a Fly.io secrets:\n"
                    f"<code>{creds_map.get(platform, '')}</code>\n\n"
                    f"Luego usa /conectar {platform} de nuevo."
                )
                return

            await self.send(
                chat_id,
                f"Aqui tienes el enlace para conectar <b>{platform.title()}</b>:\n\n"
                f"Haz clic en el boton y autoriza el acceso. "
                f"ARIA guardara los tokens automaticamente cuando completes el login.",
                reply_markup={"inline_keyboard": [[
                    {"text": f"🔗 Iniciar sesion en {platform.title()}", "url": auth_url}
                ]]}
            )
        except Exception as exc:
            logger.error("[TelegramBot] Error conectar %s: %s", platform, exc)
            await self.send(chat_id, f"Error iniciando la conexion con {platform.title()}.")

    async def cmd_redes(self, chat_id: str) -> None:
        """Lista las redes sociales conectadas."""
        try:
            from apps.core.tools.social_media import SocialMediaManager
            sm = SocialMediaManager()
            accounts = await sm.list_connected_accounts()

            if not accounts:
                await self.send(
                    chat_id,
                    "No hay redes sociales conectadas.\n\n"
                    "Conecta una con /conectar facebook, /conectar instagram, etc.",
                    reply_markup={"inline_keyboard": [
                        [{"text": "📘 Facebook", "callback_data": "cmd:conectar_facebook"},
                         {"text": "📸 Instagram", "callback_data": "cmd:conectar_instagram"}],
                        [{"text": "🎵 TikTok", "callback_data": "cmd:conectar_tiktok"},
                         {"text": "💼 LinkedIn", "callback_data": "cmd:conectar_linkedin"}],
                    ]}
                )
                return

            lines = ["<b>Cuentas conectadas:</b>\n"]
            emoji_map = {"facebook": "📘", "instagram": "📸", "tiktok": "🎵", "linkedin": "💼"}
            for acc in accounts:
                e = emoji_map.get(acc["platform"], "🔗")
                status = "✅" if acc.get("is_active") else "⚠️"
                username = acc.get("username", "cuenta")
                lines.append(f"{status} {e} <b>{acc['platform'].title()}</b> — @{username}")

            lines.append("\nUsa /publicar &lt;red&gt; &lt;mensaje&gt; para publicar ahora.")
            await self.send(chat_id, "\n".join(lines))
        except Exception as exc:
            logger.error("[TelegramBot] Error redes: %s", exc)
            await self.send(chat_id, "No pude obtener la lista de cuentas.")

    async def cmd_publicar_red(self, chat_id: str, args: str) -> None:
        """Publica contenido en una red social."""
        parts = args.split(maxsplit=1)
        if len(parts) < 2:
            await self.send(chat_id, "Uso: /publicar &lt;red&gt; &lt;mensaje&gt;\nEjemplo: /publicar instagram Hoy lanzamos algo nuevo")
            return

        platform = parts[0].lower()
        content = parts[1]

        try:
            from apps.core.tools.social_media import SocialMediaManager
            sm = SocialMediaManager()
            result = await sm.post_content(platform, content)

            if result.get("success"):
                url = result.get("post_url", "")
                url_str = f"\n<a href=\"{url}\">Ver publicacion</a>" if url else ""
                await self.send(chat_id, f"Publicado en {platform.title()}.{url_str}")
            else:
                await self.send(chat_id, f"No pude publicar en {platform.title()}: {result.get('error', 'error desconocido')}")
        except Exception as exc:
            logger.error("[TelegramBot] Error publicar: %s", exc)
            await self.send(chat_id, f"Error publicando en {platform.title()}.")

    async def cmd_desconectar(self, chat_id: str, platform: str) -> None:
        """Desconecta una red social."""
        if not platform:
            await self.send(chat_id, "Especifica la plataforma: /desconectar facebook")
            return
        try:
            from apps.core.tools.social_media import SocialMediaManager
            sm = SocialMediaManager()
            ok = await sm.disconnect_account(platform.strip().lower())
            if ok:
                await self.send(chat_id, f"Cuenta de {platform.title()} desconectada.")
            else:
                await self.send(chat_id, f"No encontre cuenta de {platform.title()} conectada.")
        except Exception as exc:
            await self.send(chat_id, f"Error: {exc}")


    # ── SESION (COOKIES SIN API) ──────────────────────────

    async def cmd_sesion(self, chat_id: str, platform_raw: str) -> None:
        """
        Conecta una red social via cookies del navegador — sin API keys.
        Flujo: usuario exporta cookies con Cookie-Editor → pega JSON aquí.
        """
        from apps.core.tools.social_session import PLATFORM_CONFIG, SUPPORTED_PLATFORMS
        platform = platform_raw.strip().lower()

        if not platform:
            # Mostrar menú de plataformas disponibles
            rows = []
            platforms_list = list(PLATFORM_CONFIG.items())
            for i in range(0, len(platforms_list), 2):
                row = []
                p1, cfg1 = platforms_list[i]
                row.append({"text": cfg1["emoji"] + " " + cfg1["display_name"], "callback_data": "cmd:sesion_" + p1})
                if i + 1 < len(platforms_list):
                    p2, cfg2 = platforms_list[i + 1]
                    row.append({"text": cfg2["emoji"] + " " + cfg2["display_name"], "callback_data": "cmd:sesion_" + p2})
                rows.append(row)
            await self.send(
                chat_id,
                "<b>Conectar red social sin API</b>\n\n"
                "Elige la plataforma. ARIA te explicará cómo exportar las cookies de tu navegador — "
                "sin necesidad de crear apps ni pedir permisos.",
                reply_markup={"inline_keyboard": rows},
            )
            return

        if platform not in SUPPORTED_PLATFORMS:
            await self.send(
                chat_id,
                f"Plataforma no soportada. Disponibles: {', '.join(SUPPORTED_PLATFORMS)}",
            )
            return

        cfg = PLATFORM_CONFIG[platform]
        from apps.core.tools.social_session import get_social_session_manager
        mgr = get_social_session_manager()

        # Guardar estado pendiente para detectar cuando el usuario pegue el JSON
        await mgr.set_pending_import(chat_id, platform)

        connect_url = f"https://aria-ai.fly.dev/social/connect?platform={platform}&token={settings.SOCIAL_CONNECT_TOKEN or 'aria'}"

        await self.send(
            chat_id,
            f"{cfg['emoji']} <b>Conectar {cfg['display_name']} sin API</b>\n\n"
            f"{cfg['instructions']}\n\n"
            f"<b>Opción A — Telegram:</b> Pega el JSON de cookies aquí directamente\n"
            f"<b>Opción B — Web:</b> <a href=\"{connect_url}\">Usar formulario web</a>\n\n"
            f"<a href=\"{cfg['help_url']}\">🔗 Descargar Cookie-Editor</a>\n\n"
            f"<i>Tienes 10 minutos para pegar las cookies.</i>",
        )

    async def _maybe_handle_cookie_import(self, text: str, chat_id: str) -> bool:
        """
        Detecta si el usuario pegó un JSON de cookies para importar.
        Retorna True si manejó el mensaje, False si debe procesarse normalmente.
        """
        # Mínimo 100 chars y debe parecer JSON (starts with [ o {)
        stripped = text.strip()
        if len(stripped) < 100:
            return False
        if not (stripped.startswith("[") or stripped.startswith("{")):
            return False
        # Verificar si hay una importación pendiente
        try:
            from apps.core.tools.social_session import get_social_session_manager
            mgr = get_social_session_manager()
            platform = await mgr.get_pending_import(chat_id)
            if not platform:
                return False
            # Parece JSON de cookies y hay pendiente — intentar importar
            await self._do_cookie_import(chat_id, platform, stripped, mgr)
            return True
        except Exception as exc:
            import logging
            logging.getLogger("aria.telegram_bot").error("[TelegramBot] cookie_import error: %s", exc)
            return False

    async def _do_cookie_import(self, chat_id: str, platform: str, raw_json: str, mgr) -> None:
        """Procesa el JSON de cookies pegado por el usuario."""
        from apps.core.tools.social_session import PLATFORM_CONFIG
        cfg = PLATFORM_CONFIG.get(platform, {})

        await self.send(chat_id, f"⏳ Procesando cookies de {cfg.get('display_name', platform)}...")

        cookies = mgr.parse_cookies_json(raw_json)
        if not cookies:
            await self.send(
                chat_id,
                "❌ No pude leer el JSON. Asegúrate de exportar como JSON desde Cookie-Editor "
                "(Export → Export as JSON), no como texto plano.",
            )
            return

        validation = mgr.validate_cookies_for_platform(cookies, platform)
        if not validation.get("valid"):
            missing = validation.get("error", "cookies faltantes")
            await self.send(
                chat_id,
                f"❌ {missing}\n\nCookies que encontré: {', '.join(list(cookies.keys())[:10])}\n\n"
                f"Asegúrate de estar logueado en {cfg.get('display_name', platform)} antes de exportar.",
            )
            return

        # Guardar sesión
        save_result = await mgr.save_session(platform, cookies)
        if not save_result.get("success"):
            await self.send(chat_id, f"❌ Error guardando la sesión: {save_result.get('error')}")
            return

        # Limpiar pendiente
        await mgr.clear_pending_import(chat_id)

        # Probar la sesión
        await self.send(chat_id, f"✅ {len(cookies)} cookies guardadas. Verificando que funcionen...")
        test = await mgr.test_session(platform)

        if test.get("success"):
            user_info = test.get("user_info", {})
            user_str = ""
            if user_info:
                username = user_info.get("username") or user_info.get("firstName", "")
                if username:
                    user_str = f" como <b>@{username}</b>"
            await self.send(
                chat_id,
                f"🎉 <b>{cfg.get('display_name', platform)} conectado{user_str}!</b>\n\n"
                f"ARIA puede ahora publicar en {cfg.get('display_name', platform)} sin API keys. "
                f"Usa /publicar {platform} &lt;mensaje&gt; para publicar.",
            )
        else:
            error = test.get("error", "error desconocido")
            await self.send(
                chat_id,
                f"⚠️ Cookies guardadas pero la verificación falló: {error}\n\n"
                f"Las cookies pueden ser correctas — algunos endpoints de prueba son restrictivos. "
                f"Intenta publicar con /publicar {platform} <mensaje> para confirmar.",
            )

    async def cmd_redes_all(self, chat_id: str) -> None:
        """Lista TODAS las cuentas: OAuth + sesiones sin API."""
        await self._send_typing(chat_id)
        lines = ["<b>Cuentas de Redes Sociales</b>\n"]
        found_any = False

        # Sesiones sin API (cookies)
        try:
            from apps.core.tools.social_session import get_social_session_manager
            mgr = get_social_session_manager()
            sessions = await mgr.list_active_sessions()
            if sessions:
                lines.append("<b>📱 Conectadas sin API (cookies):</b>")
                for s in sessions:
                    age = f"{s['age_days']}d" if s['age_days'] > 0 else "hoy"
                    lines.append(f"  ✅ {s['emoji']} {s['display_name']} ({s['cookies_count']} cookies, {age})")
                found_any = True
        except Exception:
            pass

        # OAuth accounts
        try:
            from apps.core.tools.social_media import SocialMediaManager
            sm = SocialMediaManager()
            accounts = await sm.list_connected_accounts()
            if accounts:
                lines.append("\n<b>🔑 Conectadas via OAuth:</b>")
                emoji_map = {"facebook": "📘", "instagram": "📸", "tiktok": "🎵", "linkedin": "💼"}
                for acc in accounts:
                    e = emoji_map.get(acc["platform"], "🔗")
                    lines.append(f"  ✅ {e} {acc['platform'].title()} — @{acc.get('username', '?')}")
                found_any = True
        except Exception:
            pass

        if not found_any:
            lines.append("Ninguna cuenta conectada aún.\n\n"
                        "Usa /sesion para conectar sin API (recomendado) o "
                        "/conectar para conectar via OAuth.")

        lines.append("\n/sesion — Conectar sin API  |  /conectar — OAuth")
        await self.send(
            chat_id,
            "\n".join(lines),
            reply_markup={"inline_keyboard": [[
                {"text": "➕ Conectar sin API", "callback_data": "cmd:sesion"},
                {"text": "🔑 Conectar OAuth", "callback_data": "cmd:conectar_"},
            ]]},
        )

    # ── ESTADO Y CONTROL ──────────────────────────────────

  async def cmd_status(self, chat_id: str) -> None:
      await self._send_typing(chat_id)
      try:
          from apps.core.memory.supabase_client import get_db
          from apps.core.memory.redis_client import get_cache
          db = get_db()
          cache = get_cache()
          rev = await db.get_total_revenue()
          cycles = await cache.get("aria:cycle_count") or 0
          paused = await cache.get("aria:scheduler_paused")

          try:
              from apps.core.tools.social_media import SocialMediaManager
              sm = SocialMediaManager()
              accounts = await sm.list_connected_accounts()
              redes_str = ", ".join(a["platform"].title() for a in accounts) if accounts else "ninguna"
          except Exception:
              redes_str = "no disponible"

          msg = (
              f"<b>ARIA — Estado del Sistema</b>\n\n"
              f"Revenue total: <b>${rev:.2f} USD</b>\n"
              f"Ciclos ejecutados: {cycles}\n"
              f"Scheduler: {'⏸ PAUSADO' if paused else '▶️ ACTIVO'}\n"
              f"Redes conectadas: {redes_str}\n"
          )
          await self.send(chat_id, msg, reply_markup={"inline_keyboard": [[
              {"text": "🚀 Ciclo", "callback_data": "cmd:ciclo"},
              {"text": "💰 Revenue", "callback_data": "cmd:revenue"},
              {"text": "✅ Pendientes", "callback_data": "cmd:pendientes"},
          ]]})
      except Exception as exc:
          await self.send(chat_id, f"No pude obtener el estado: {exc}")

  async def cmd_agentes(self, chat_id: str) -> None:
      await self._send_typing(chat_id)
      try:
          from apps.core.agents.orchestrator import Orchestrator
          orch = Orchestrator()
          statuses = orch.get_all_agent_statuses()
          lines = ["<b>Estado de Agentes</b>\n"]
          for name, info in statuses.items():
              s = info.get("status", "unknown")
              icon = "✅" if s == "idle" else "🔄" if s == "running" else "❌"
              lines.append(f"{icon} <b>{name}</b> — {s}")
          await self.send(chat_id, "\n".join(lines))
      except Exception as exc:
          await self.send(chat_id, f"Error obteniendo agentes: {exc}")

  async def cmd_revenue(self, chat_id: str) -> None:
      await self._send_typing(chat_id)
      try:
          from apps.core.memory.supabase_client import get_db
          db = get_db()
          total = await db.get_total_revenue()
          by_platform = await db.get_revenue_by_platform()
          lines = [f"<b>Revenue — ARIA</b>\n\nTotal: <b>${total:.2f} USD</b>\n"]
          for platform, amount in (by_platform or {}).items():
              lines.append(f"  {platform}: ${amount:.2f}")
          await self.send(chat_id, "\n".join(lines))
      except Exception as exc:
          await self.send(chat_id, f"Error: {exc}")

  async def cmd_ciclo(self, chat_id: str) -> None:
      await self._send_typing(chat_id)
      try:
          async with httpx.AsyncClient(timeout=10.0) as c:
              res = await c.post("http://localhost:8000/cycle/trigger")
              ok = res.json().get("success", False)
          if ok:
              await self.send(chat_id, "Ciclo autonomo iniciado.")
          else:
              await self.send(chat_id, "No pude iniciar el ciclo. Revisa los logs.")
      except Exception as exc:
          await self.send(chat_id, f"Error: {exc}")

  async def cmd_pausa(self, chat_id: str) -> None:
      try:
          from apps.core.memory.redis_client import get_cache
          cache = get_cache()
          await cache.set("aria:scheduler_paused", True, ttl_seconds=86400)
          async with httpx.AsyncClient(timeout=5.0) as c:
              await c.post("http://localhost:8000/cycle/pause")
          await self.send(chat_id, "Scheduler pausado.")
      except Exception as exc:
          await self.send(chat_id, f"Error: {exc}")

  async def cmd_reanudar(self, chat_id: str) -> None:
      try:
          from apps.core.memory.redis_client import get_cache
          cache = get_cache()
          await cache.delete("aria:scheduler_paused")
          async with httpx.AsyncClient(timeout=5.0) as c:
              await c.post("http://localhost:8000/cycle/resume")
          await self.send(chat_id, "Scheduler activo.")
      except Exception as exc:
          await self.send(chat_id, f"Error: {exc}")

  async def cmd_pendientes(self, chat_id: str) -> None:
      await self._send_typing(chat_id)
      try:
          from apps.core.memory.supabase_client import get_db
          db = get_db()
          result = db._client.table("approvals").select("*").eq("status", "pending").order("created_at", desc=True).limit(5).execute()
          approvals = result.data or []
          if not approvals:
              await self.send(chat_id, "No hay aprobaciones pendientes.")
              return
          for a in approvals:
              keyboard = {"inline_keyboard": [[
                  {"text": "✅ Aprobar", "callback_data": f"aprobar:{a['id']}"},
                  {"text": "❌ Rechazar", "callback_data": f"rechazar:{a['id']}"},
              ]]}
              await self.send(
                  chat_id,
                  f"<b>{a.get('action_type', 'Accion')}</b>\n"
                  f"{a.get('description', '')}\n"
                  f"<code>{a['id']}</code>",
                  reply_markup=keyboard,
              )
      except Exception as exc:
          await self.send(chat_id, f"Error: {exc}")

  async def _do_approval(self, chat_id: str, approval_id: str, decision: str) -> None:
      try:
          async with httpx.AsyncClient(timeout=10.0) as c:
              res = await c.post(
                  "http://localhost:8000/approvals/decide",
                  json={"approval_id": approval_id, "decision": decision},
              )
              ok = res.json().get("success", False)
          emoji = "✅" if decision == "approved" else "❌"
          text = "Aprobado" if decision == "approved" else "Rechazado"
          await self.send(chat_id, f"{emoji} {text}.")
      except Exception as exc:
          await self.send(chat_id, f"Error procesando aprobacion: {exc}")

  async def cmd_aprobar(self, chat_id: str, approval_id: str) -> None:
      if not approval_id:
          await self.send(chat_id, "Especifica el ID: /aprobar &lt;id&gt;")
          return
      await self._do_approval(chat_id, approval_id.strip(), "approved")

  async def cmd_rechazar(self, chat_id: str, approval_id: str) -> None:
      if not approval_id:
          await self.send(chat_id, "Especifica el ID: /rechazar &lt;id&gt;")
          return
      await self._do_approval(chat_id, approval_id.strip(), "rejected")

  async def cmd_logs(self, chat_id: str, args: str) -> None:
      await self._send_typing(chat_id)
      try:
          n = int(args.strip()) if args.strip().isdigit() else 10
          n = min(n, 50)
          from apps.core.memory.supabase_client import get_db
          db = get_db()
          result = db._client.table("system_logs").select("*").order("created_at", desc=True).limit(n).execute()
          logs = result.data or []
          if not logs:
              await self.send(chat_id, "Sin logs recientes.")
              return
          lines = [f"<b>Ultimos {n} logs</b>\n"]
          for log in logs:
              level = log.get("level", "INFO")
              icon = "❌" if level == "ERROR" else "⚠️" if level == "WARNING" else "ℹ️"
              ts = log.get("created_at", "")[:16]
              lines.append(f"{icon} [{ts}] {log.get('message', '')[:100]}")
          await self.send(chat_id, "\n".join(lines))
      except Exception as exc:
          await self.send(chat_id, f"Error obteniendo logs: {exc}")

  # ── AGENTES ───────────────────────────────────────────

  async def cmd_agent_run(self, chat_id: str, agent_name: str, task: str) -> None:
      await self._send_typing(chat_id)
      try:
          agent_map = {
              "pm":        ("apps.core.agents.pm_agent", "PMAgent"),
              "cfo":       ("apps.core.agents.cfo_agent", "CFOAgent"),
              "dev":       ("apps.core.agents.dev_agent", "DevAgent"),
              "marketing": ("apps.core.agents.marketing_agent", "MarketingAgent"),
              "support":   ("apps.core.agents.support_agent", "SupportAgent"),
          }
          if agent_name not in agent_map:
              await self.send(chat_id, f"Agente desconocido: {agent_name}")
              return
          module_path, class_name = agent_map[agent_name]
          import importlib
          module = importlib.import_module(module_path)
          AgentClass = getattr(module, class_name)
          agent = AgentClass()
          await agent.start()
          result = await agent.run({"task": task})
          await agent.stop()
          output = result.get("summary") or result.get("result") or str(result)[:300]
          await self.send(chat_id, f"<b>{class_name}</b>\n\n{output}")
      except Exception as exc:
          logger.error("[TelegramBot] Agent error: %s", exc)
          await self.send(chat_id, f"Error ejecutando {agent_name}: {str(exc)[:200]}")

  # ── HERRAMIENTAS ──────────────────────────────────────

  async def cmd_buscar(self, chat_id: str, query: str) -> None:
      if not query:
          await self.send(chat_id, "Escribe que busco: /buscar &lt;consulta&gt;")
          return
      await self._send_typing(chat_id)
      try:
          from apps.core.tools.google_suite import GoogleSuiteTools
          g = GoogleSuiteTools()
          results = await g.web_search(query)
          if not results:
              await self.send(chat_id, "Sin resultados.")
              return
          lines = [f"<b>Resultados para: {query}</b>\n"]
          for r in results[:5]:
              title = r.get("title", "Sin titulo")
              url = r.get("link", "")
              snippet = r.get("snippet", "")[:100]
              lines.append(f'• <a href="{url}">{title}</a>\n  {snippet}\n')
          await self.send(chat_id, "\n".join(lines), disable_web_page_preview=True)
      except Exception as exc:
          await self.send(chat_id, f"Error en busqueda: {exc}")

  async def cmd_youtube(self, chat_id: str, query: str) -> None:
      if not query:
          await self.send(chat_id, "/youtube &lt;consulta&gt;")
          return
      await self._send_typing(chat_id)
      try:
          from apps.core.tools.google_suite import GoogleSuiteTools
          g = GoogleSuiteTools()
          results = await g.youtube_search(query)
          if not results:
              await self.send(chat_id, "Sin resultados en YouTube.")
              return
          lines = [f"<b>YouTube: {query}</b>\n"]
          for r in results[:5]:
              title = r.get("title", "")
              vid_id = r.get("videoId") or r.get("id", {}).get("videoId", "")
              if vid_id:
                  lines.append(f'• <a href="https://youtu.be/{vid_id}">{title}</a>')
          await self.send(chat_id, "\n".join(lines))
      except Exception as exc:
          await self.send(chat_id, f"Error: {exc}")

  async def cmd_imagen(self, chat_id: str, prompt: str) -> None:
      if not prompt:
          await self.send(chat_id, "/imagen &lt;descripcion&gt;")
          return
      await self._send_typing(chat_id)
      try:
          from apps.core.tools.huggingface_suite import HuggingFaceSuite
          hf = HuggingFaceSuite()
          image_data = await hf.generate_image(prompt)
          if image_data:
              files = {"photo": ("image.png", image_data, "image/png")}
              await self._http.post(
                  f"{self._base_url}/sendPhoto",
                  data={"chat_id": chat_id, "caption": prompt[:1000]},
                  files=files,
              )
          else:
              await self.send(chat_id, "No pude generar la imagen.")
      except Exception as exc:
          await self.send(chat_id, f"Error: {exc}")

  async def cmd_traducir(self, chat_id: str, args: str) -> None:
      if not args:
          await self.send(chat_id, "/traducir &lt;idioma&gt; &lt;texto&gt; — ej: /traducir en Hola mundo")
          return
      await self._send_typing(chat_id)
      parts = args.split(maxsplit=1)
      lang = parts[0] if len(parts) > 0 else "en"
      text_to_translate = parts[1] if len(parts) > 1 else args
      try:
          from apps.core.tools.google_suite import GoogleSuiteTools
          g = GoogleSuiteTools()
          result = await g.translate_text(text_to_translate, target_language=lang)
          await self.send(chat_id, result or "No pude traducir.")
      except Exception as exc:
          await self.send(chat_id, f"Error: {exc}")

  async def cmd_resumir(self, chat_id: str, text: str) -> None:
      if not text:
          await self.send(chat_id, "/resumir &lt;texto&gt;")
          return
      await self._send_typing(chat_id)
      try:
          from apps.core.tools.huggingface_suite import HuggingFaceSuite
          hf = HuggingFaceSuite()
          result = await hf.summarize(text)
          await self.send(chat_id, result or "No pude resumir.")
      except Exception as exc:
          await self.send(chat_id, f"Error: {exc}")

  async def cmd_tendencias(self, chat_id: str) -> None:
      await self._send_typing(chat_id)
      try:
          from apps.core.tools.google_suite import GoogleSuiteTools
          g = GoogleSuiteTools()
          trends = await g.get_trending_topics()
          if not trends:
              await self.send(chat_id, "No pude obtener tendencias ahora.")
              return
          lines = ["<b>Trending ahora:</b>\n"]
          for i, trend in enumerate(trends[:10], 1):
              t = trend if isinstance(trend, str) else trend.get("title", str(trend))
              lines.append(f"{i}. {t}")
          await self.send(chat_id, "\n".join(lines))
      except Exception as exc:
          await self.send(chat_id, f"Error: {exc}")

  async def cmd_codigo(self, chat_id: str, task: str) -> None:
      if not task:
          await self.send(chat_id, "/codigo &lt;descripcion de lo que necesitas&gt;")
          return
      await self._send_typing(chat_id)
      try:
          from apps.core.tools.ai_client import AIModel, get_ai_client
          ai = await get_ai_client()
          resp = await ai.complete(
              system="Eres un experto en programacion. Genera codigo limpio, funcional y bien comentado. Solo codigo, sin explicaciones largas.",
              user=task,
              model=AIModel.CODE,
              max_tokens=2000,
          )
          if resp and resp.success:
              code = resp.content
              if len(code) > 4000:
                  code = code[:4000] + "...\n[cortado por longitud]"
              await self.send(chat_id, f"<pre>{code}</pre>")
          else:
              await self.send(chat_id, "No pude generar el codigo.")
      except Exception as exc:
          await self.send(chat_id, f"Error: {exc}")

  async def cmd_sentimiento(self, chat_id: str, text: str) -> None:
      if not text:
          await self.send(chat_id, "/sentimiento &lt;texto&gt;")
          return
      await self._send_typing(chat_id)
      try:
          from apps.core.tools.huggingface_suite import HuggingFaceSuite
          hf = HuggingFaceSuite()
          result = await hf.analyze_sentiment(text)
          await self.send(chat_id, str(result) if result else "No pude analizar.")
      except Exception as exc:
          await self.send(chat_id, f"Error: {exc}")

  async def cmd_capacidades(self, chat_id: str) -> None:
      await self.send(chat_id, self.HELP_TEXT)

  # ── AUTO-EVOLUCION ────────────────────────────────────

  async def cmd_evolve(self, chat_id: str) -> None:
      await self.send(
          chat_id,
          "<b>Auto-evolucion</b>\n\nElige que quieres que haga:",
          reply_markup={"inline_keyboard": [
              [{"text": "⚙️ Todo (codigo + APIs)", "callback_data": "cmd:evolve_full"},
               {"text": "🔧 Solo codigo", "callback_data": "cmd:mejorar"}],
              [{"text": "🔌 Solo APIs", "callback_data": "cmd:apis"},
               {"text": "📊 Ver score", "callback_data": "cmd:score"}],
          ]}
      )

  async def cmd_mejorar(self, chat_id: str, args: str) -> None:
      n = int(args.strip()) if args.strip().isdigit() else 2
      await self.send(chat_id, f"Analizando y mejorando {n} archivos...")
      asyncio.create_task(self._run_improvement_async(chat_id, n))

  async def _run_improvement_async(self, chat_id: str, n: int) -> None:
      try:
          from apps.core.tools.self_improvement import SelfImprovementEngine
          engine = SelfImprovementEngine()
          result = await engine.improve_files(n)
          improved = result.get("improved", [])
          if improved:
              await self.send(chat_id, f"Mejore {len(improved)} archivos: {', '.join(improved)}")
          else:
              await self.send(chat_id, "Sin mejoras significativas en este ciclo.")
      except Exception as exc:
          await self.send(chat_id, f"Error en auto-mejora: {exc}")

  async def cmd_apis(self, chat_id: str, args: str) -> None:
      n = int(args.strip()) if args.strip().isdigit() else 1
      await self.send(chat_id, f"Buscando e integrando {n} API(s) nuevas...")
      asyncio.create_task(self._run_api_discovery_async(chat_id, n))

  async def _run_api_discovery_async(self, chat_id: str, n: int) -> None:
      try:
          from apps.core.tools.api_discovery import APIDiscoveryEngine
          engine = APIDiscoveryEngine()
          result = await engine.discover_and_integrate(n)
          integrated = result.get("integrated", [])
          if integrated:
              await self.send(chat_id, f"Integre {len(integrated)} API(s): {', '.join(integrated)}")
          else:
              await self.send(chat_id, "No encontre APIs nuevas valiosas ahora.")
      except Exception as exc:
          await self.send(chat_id, f"Error en descubrimiento de APIs: {exc}")

  async def cmd_score(self, chat_id: str) -> None:
      await self._send_typing(chat_id)
      try:
          from apps.core.agents.evolution_agent import EvolutionAgent
          agent = EvolutionAgent()
          await agent.start()
          score_data = await agent.get_health_score()
          await agent.stop()
          score = score_data.get("score", 0)
          details = score_data.get("details", {})
          icon = "🟢" if score >= 70 else "🟡" if score >= 40 else "🔴"
          lines = [f"{icon} <b>Score del sistema: {score}/100</b>\n"]
          for k, v in details.items():
              lines.append(f"  {k}: {v}")
          await self.send(chat_id, "\n".join(lines))
      except Exception as exc:
          await self.send(chat_id, f"No pude calcular el score: {exc}")

  async def _run_evolve_async(self, chat_id: str, mode: str, improve_n: int, api_n: int) -> None:
      try:
          from apps.core.agents.evolution_agent import EvolutionAgent
          agent = EvolutionAgent()
          await agent.start()
          result = await agent.run({"task": "auto_evolve", "mode": mode, "improve_n": improve_n, "api_n": api_n})
          await agent.stop()
          summary = result.get("summary", "Evolucion completada.")
          await self.send(chat_id, summary)
      except Exception as exc:
          await self.send(chat_id, f"Error en evolucion: {exc}")

  # ── ENVIO Y UTILIDADES ────────────────────────────────

  async def send(
      self,
      chat_id: str,
      text: str,
      reply_markup: Optional[dict] = None,
      disable_web_page_preview: bool = True,
  ) -> bool:
      try:
          payload: dict[str, Any] = {
              "chat_id": chat_id,
              "text": text,
              "parse_mode": "HTML",
              "disable_web_page_preview": disable_web_page_preview,
          }
          if reply_markup:
              payload["reply_markup"] = reply_markup
          res = await self._http.post(f"{self._base_url}/sendMessage", json=payload)
          if res.status_code != 200:
              logger.warning("[TelegramBot] send fallo: %d — %s", res.status_code, res.text[:200])
          return res.status_code == 200
      except Exception as exc:
          logger.error("[TelegramBot] send error: %s", exc)
          return False

  async def _send_typing(self, chat_id: str) -> None:
      try:
          await self._http.post(
              f"{self._base_url}/sendChatAction",
              json={"chat_id": chat_id, "action": "typing"},
          )
      except Exception:
          pass

  async def set_webhook(self, url: str) -> bool:
      try:
          res = await self._http.post(
              f"{self._base_url}/setWebhook",
              json={"url": url, "allowed_updates": ["message", "callback_query", "edited_message"]},
          )
          return res.json().get("ok", False)
      except Exception as exc:
          logger.error("[TelegramBot] set_webhook error: %s", exc)
          return False

  async def get_webhook_info(self) -> dict:
      try:
          res = await self._http.get(f"{self._base_url}/getWebhookInfo")
          return res.json().get("result", {})
      except Exception:
          return {}

  async def notify_approval_request(self, action_type: str, description: str, approval_id: str) -> None:
      keyboard = {"inline_keyboard": [[
          {"text": "✅ Aprobar", "callback_data": f"aprobar:{approval_id}"},
          {"text": "❌ Rechazar", "callback_data": f"rechazar:{approval_id}"},
      ]]}
      await self.send(
          self._owner_id,
          f"<b>Aprobacion requerida</b>\n\n"
          f"Tipo: {action_type}\n"
          f"{description}\n"
          f"ID: <code>{approval_id}</code>",
          reply_markup=keyboard,
      )


# ── SINGLETON ─────────────────────────────────────────────

_bot_instance: Optional[AriaTelegramBot] = None


def get_bot() -> AriaTelegramBot:
  global _bot_instance
  if _bot_instance is None:
      _bot_instance = AriaTelegramBot()
  return _bot_instance
