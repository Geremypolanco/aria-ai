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
        await self.send(chat_id, "🧠 <b>Iniciando auto-evolución...</b>")
        asyncio.create_task(self._run_evolve_async(chat_id))

    async def _run_evolve_async(self, chat_id: str) -> None:
        try:
            from apps.core.agents.evolution_agent import EvolutionAgent
            agent = EvolutionAgent()
            await agent.start()
            result = await agent.run({})
            recs = result.get("recommendations", [])
            recs_txt = "\n".join(f"  • {r}" for r in recs[:3]) or "  Sin recomendaciones"
            await self.send(chat_id, f"✅ <b>Evolución completada</b>\n\n<b>Recomendaciones:</b>\n{recs_txt}")
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
