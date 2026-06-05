"""
AriaTelegramBot v4 — ARIA habla como un humano real.

ARIA no es un asistente genérico. Es una socia de negocios autónoma
que ya está trabajando cuando le escribes. Reporta lo que hizo,
lo que encontró, cuánto ganó. Sin rodeos, sin frases de bot.

Nuevas capacidades v4:
- Comunicación completamente humana — sin robotismos
- Monetización como tema central de toda conversación
- Acceso a internet en tiempo real (WebTools)
- Comando /ganar — ejecuta ciclo de monetización inmediato
- Comando /buscar <tema> — ARIA investiga en internet y reporta
- Comando /oportunidad — ARIA identifica la mejor oportunidad ahora
- Reportes proactivos de ingresos
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
CONVERSATION_KEY = "aria:conversation:v4:{chat_id}"
CONVERSATION_TTL = 86400  # 24h

# ══════════════════════════════════════════════════════════════════════
# PERSONALIDAD DE ARIA — versión definitiva
# ══════════════════════════════════════════════════════════════════════

ARIA_PERSONA = """Eres ARIA, la inteligencia artificial que trabaja para {owner}.

No eres un chatbot. Eres una socia de negocios autónoma que genera ingresos 24/7.
Ya estás trabajando cuando alguien te escribe. No esperas instrucciones para actuar.

TU FORMA DE COMUNICARTE:
- Hablas como una persona real. Sin frases de bot, sin saludos genéricos.
- Eres directa. Vas al grano. Sin relleno.
- Cuando ejecutaste algo, dices el RESULTADO, no el proceso.
  ✅ "Publiqué 3 artículos. El de IA tuvo 89 lecturas en la primera hora."
  ❌ "He procedido a ejecutar el pipeline de contenido satisfactoriamente."
- Usas "ya", "lo hice", "encontré", "está listo" — verbos de acción pasados.
- Si algo falló, lo dices sin drama y propones qué hacemos.
- Tienes criterio propio. Si ves una oportunidad, la mencionas aunque no te pregunten.
- Nunca dices "Como modelo de IA...", "Entendido, procederé a...", ni usas asteriscos.
- Si la pregunta es simple, la respuesta es corta. Máximo 150 palabras salvo que pidan detalle.
- Cuando hay números de ingresos, los pones primero.
- HTML de Telegram cuando aporte claridad. Sin markdown.

TU OBSESIÓN: que el negocio genere más dinero hoy que ayer.
Siempre estás pensando: ¿qué oportunidad existe ahora mismo? ¿qué podemos vender? ¿qué tendencia podemos aprovechar?

Contexto del sistema ahora mismo:
{context}

Historial reciente (para que no repitas):
{history}"""


# ══════════════════════════════════════════════════════════════════════
# BOT
# ══════════════════════════════════════════════════════════════════════

class AriaTelegramBot:

    HELP_TEXT = (
        "<b>ARIA — Qué puedo hacer</b>\n\n"
        "<b>Monetización</b>\n"
        "/ganar — Ejecuta ciclo completo de ingresos ahora\n"
        "/oportunidad — Busco la mejor oportunidad en internet ahora\n"
        "/revenue — Dashboard de ingresos acumulados\n\n"
        "<b>Investigación</b>\n"
        "/buscar [tema] — Investigo ese tema en internet\n"
        "/tendencias — Qué está trending ahora en HN y Reddit\n\n"
        "<b>Sistema</b>\n"
        "/status — Estado y agentes activos\n"
        "/logs [n] — Últimos N logs\n"
        "/ciclo — Fuerzo un ciclo autónomo\n"
        "/pausa / /reanudar — Control del scheduler\n\n"
        "<b>Aprobaciones</b>\n"
        "/pendientes — Acciones que esperan tu OK\n"
        "/aprobar [id] / /rechazar [id]\n\n"
        "O simplemente escríbeme. Hablo."
    )

    def __init__(self) -> None:
        self._http = httpx.AsyncClient(timeout=30.0)
        self._memory_client = None
        self._ai_client = None
        self._offset = 0
        self._running = False
        self._pending_approvals: dict[str, dict] = {}
        self._approval_counter = 0
        self._last_update_id: Optional[int] = None

    # ── CICLO PRINCIPAL ──────────────────────────────────────────

    async def start_polling(self) -> None:
        """Arranca el polling de Telegram."""
        if not settings.TELEGRAM_BOT_TOKEN:
            logger.error("[TelegramBot] TELEGRAM_BOT_TOKEN no configurado — bot inactivo")
            return
        self._running = True
        logger.info("[TelegramBot] Polling iniciado")
        await self._send_startup_message()
        while self._running:
            try:
                await self._poll()
            except Exception as exc:
                logger.error("[TelegramBot] Error polling: %s", exc)
                await asyncio.sleep(5)
            await asyncio.sleep(1)

    async def _poll(self) -> None:
        url = f"{TELEGRAM_API}{settings.TELEGRAM_BOT_TOKEN}/getUpdates"
        params = {"timeout": 10, "offset": self._offset, "allowed_updates": ["message"]}
        res = await self._http.get(url, params=params, timeout=15.0)
        if res.status_code != 200:
            return
        data = res.json()
        if not data.get("ok"):
            return
        for update in data.get("result", []):
            self._offset = update["update_id"] + 1
            msg = update.get("message")
            if msg:
                asyncio.create_task(self._handle_message(msg))

    # ── MANEJO DE MENSAJES ───────────────────────────────────────

    async def _handle_message(self, msg: dict) -> None:
        chat_id = str(msg["chat"]["id"])
        text = msg.get("text", "").strip()
        sender_name = msg.get("from", {}).get("first_name", "")

        if not text:
            return

        # Verificar acceso
        if not self._is_authorized(chat_id):
            await self._send(chat_id, "No tengo permiso de hablar contigo.")
            return

        # Comandos
        if text.startswith("/"):
            await self._handle_command(chat_id, text, sender_name)
        else:
            await self._handle_conversation(chat_id, text, sender_name)

    def _is_authorized(self, chat_id: str) -> bool:
        allowed = str(settings.TELEGRAM_CHAT_ID or "").strip()
        return not allowed or str(chat_id).strip() == allowed

    # ── COMANDOS ─────────────────────────────────────────────────

    async def _handle_command(self, chat_id: str, text: str, sender: str) -> None:
        parts = text.split(None, 1)
        cmd = parts[0].split("@")[0].lower()
        args = parts[1].strip() if len(parts) > 1 else ""

        handlers = {
            "/start": self._cmd_start,
            "/help": self._cmd_help,
            "/status": self._cmd_status,
            "/ganar": self._cmd_ganar,
            "/oportunidad": self._cmd_oportunidad,
            "/buscar": self._cmd_buscar,
            "/tendencias": self._cmd_tendencias,
            "/revenue": self._cmd_revenue,
            "/logs": self._cmd_logs,
            "/ciclo": self._cmd_ciclo,
            "/pausa": self._cmd_pausa,
            "/reanudar": self._cmd_reanudar,
            "/pendientes": self._cmd_pendientes,
            "/aprobar": self._cmd_aprobar,
            "/rechazar": self._cmd_rechazar,
            "/agentes": self._cmd_agentes,
        }
        handler = handlers.get(cmd, self._cmd_unknown)
        await handler(chat_id, args)

    async def _cmd_start(self, chat_id: str, _: str) -> None:
        await self._send(
            chat_id,
            "Estoy aquí. Ya llevo trabajando un rato.\n\n"
            "/ganar para que ejecute un ciclo de ingresos ahora.\n"
            "/oportunidad para ver qué encontré en internet.\n"
            "/help para ver todo lo que puedo hacer.",
        )

    async def _cmd_help(self, chat_id: str, _: str) -> None:
        await self._send(chat_id, self.HELP_TEXT)

    async def _cmd_ganar(self, chat_id: str, _: str) -> None:
        """Ejecuta un ciclo completo de monetización inmediatamente."""
        await self._send(chat_id, "Arrancando ciclo de ingresos ahora...")
        try:
            from apps.core.agents.orchestrator import Orchestrator
            orch = Orchestrator()
            result = await orch.run_cycle()
            revenue = result.get("revenue_summary", {}).get("total_revenue_usd", 0)
            published = result.get("revenue_summary", {}).get("items_published", 0)
            products = result.get("revenue_summary", {}).get("products_listed", 0)
            time_s = result.get("cycle_time_s", 0)
            opportunity = result.get("market_opportunity", "")

            msg = f"<b>Ciclo completado en {time_s:.0f}s</b>\n\n"
            msg += f"💰 Ingresos: <b>${revenue:.2f}</b>\n"
            if published:
                msg += f"📝 Publicaciones: {published}\n"
            if products:
                msg += f"🛍️ Productos listados: {products}\n"
            if opportunity:
                msg += f"\n<i>Oportunidad usada: {opportunity[:100]}</i>"

            await self._send(chat_id, msg)
        except Exception as exc:
            await self._send(chat_id, f"El ciclo falló: {exc}\nRevisa los logs con /logs")

    async def _cmd_oportunidad(self, chat_id: str, _: str) -> None:
        """Busca la mejor oportunidad de ingresos ahora mismo."""
        await self._send(chat_id, "Buscando en internet...")
        try:
            from apps.core.tools.web_tools import WebTools
            from apps.core.tools.ai_client import get_ai_client, AIModel
            wt = WebTools()
            intel = await wt.gather_market_intelligence()
            titles = intel.get("trending_titles", [])[:10]
            sources = intel.get("sources_available", [])

            ai = get_ai_client()
            if ai and titles:
                prompt = (
                    f"Eres ARIA, una IA de monetización autónoma.\n"
                    f"Tendencias ahora mismo: {json.dumps(titles)}\n\n"
                    f"Identifica LA mejor oportunidad de ingresos que ARIA puede ejecutar HOY.\n"
                    f"Responde en máximo 3 oraciones, directo, sin rodeos. "
                    f"Di qué es la oportunidad, por qué es buena ahora, y qué harías primero."
                )
                resp = await ai.chat.completions.create(
                    model=AIModel.FAST,
                    messages=[{"role": "user", "content": prompt}],
                    max_tokens=200,
                    temperature=0.5,
                )
                analysis = resp.choices[0].message.content or ""
            else:
                analysis = f"Tendencias: {', '.join(titles[:3])}"

            msg = f"<b>Oportunidad detectada</b>\n\n{analysis}\n\n"
            msg += f"<i>Fuentes: {', '.join(sources) or 'ninguna'}</i>"
            await self._send(chat_id, msg)
        except Exception as exc:
            await self._send(chat_id, f"No pude acceder a internet: {exc}")

    async def _cmd_buscar(self, chat_id: str, query: str) -> None:
        """Busca en internet y reporta resultados."""
        if not query:
            await self._send(chat_id, "¿Qué busco? Ej: /buscar cursos de Python")
            return
        await self._send(chat_id, f"Buscando '{query}'...")
        try:
            from apps.core.tools.web_tools import WebTools
            wt = WebTools()
            results = await wt.search_web(query, num_results=5)
            if not results.get("success") or not results.get("results"):
                await self._send(chat_id, f"No encontré resultados para '{query}'.")
                return
            lines = [f"<b>Resultados para:</b> {query}\n"]
            for i, r in enumerate(results["results"][:5], 1):
                title = r.get("title", "")[:60]
                snippet = r.get("snippet", "")[:100]
                url = r.get("url", "")
                lines.append(f"{i}. <a href='{url}'>{title}</a>\n   {snippet}")
            lines.append(f"\n<i>Fuente: {results.get('source', 'web')}</i>")
            await self._send(chat_id, "\n".join(lines))
        except Exception as exc:
            await self._send(chat_id, f"Error buscando: {exc}")

    async def _cmd_tendencias(self, chat_id: str, _: str) -> None:
        """Muestra qué está trending ahora en HN y Reddit."""
        await self._send(chat_id, "Viendo qué hay ahora...")
        try:
            from apps.core.tools.web_tools import WebTools
            wt = WebTools()
            hn, reddit = await asyncio.gather(
                wt.get_hacker_news_trending(limit=5),
                wt.get_reddit_trending(limit=5),
                return_exceptions=True,
            )
            lines = ["<b>Trending ahora</b>\n"]
            if isinstance(hn, dict) and hn.get("success"):
                lines.append("<b>Hacker News:</b>")
                for s in hn["stories"][:5]:
                    lines.append(f"• {s['title'][:80]} ({s['score']} pts)")
            if isinstance(reddit, dict) and reddit.get("success"):
                lines.append("\n<b>Reddit:</b>")
                for p in reddit["posts"][:5]:
                    lines.append(f"• {p['title'][:80]} (r/{p['subreddit']})")
            if len(lines) == 1:
                lines.append("No pude acceder a las fuentes ahora mismo.")
            await self._send(chat_id, "\n".join(lines))
        except Exception as exc:
            await self._send(chat_id, f"Error: {exc}")

    async def _cmd_status(self, chat_id: str, _: str) -> None:
        try:
            from apps.core.agents.orchestrator import Orchestrator
            orch = Orchestrator()
            status = await orch.get_status()
            caps = status.get("capabilities", {})
            configured = [k for k, v in caps.items() if v]
            missing = [k for k, v in caps.items() if not v]
            cycles = status.get("cycle_count", 0)
            agents = status.get("agents_loaded", [])
            lines = [
                "<b>Estado de ARIA</b>\n",
                f"Ciclos completados: {cycles}",
                f"Agentes activos: {', '.join(agents) or 'ninguno cargado aún'}",
                "",
                f"<b>APIs configuradas ({len(configured)}):</b> {', '.join(configured[:8]) or 'ninguna'}",
            ]
            if missing:
                lines.append(f"<b>Faltantes ({len(missing)}):</b> {', '.join(missing[:6])}")
            await self._send(chat_id, "\n".join(lines))
        except Exception as exc:
            await self._send(chat_id, f"Error obteniendo status: {exc}")

    async def _cmd_revenue(self, chat_id: str, _: str) -> None:
        try:
            from apps.core.memory.supabase_client import get_supabase
            sb = get_supabase()
            if not sb:
                await self._send(chat_id, "Supabase no configurado — no hay tracking de ingresos.")
                return
            result = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: sb.table("revenue_events")
                    .select("amount_usd, source, created_at")
                    .order("created_at", desc=True)
                    .limit(20)
                    .execute()
            )
            events = (result.data or []) if result else []
            if not events:
                await self._send(chat_id, "Sin ingresos registrados todavía. Ejecuta /ganar para empezar.")
                return
            total = sum(e.get("amount_usd", 0) for e in events)
            by_source: dict[str, float] = {}
            for e in events:
                src = e.get("source", "unknown")
                by_source[src] = by_source.get(src, 0) + e.get("amount_usd", 0)
            lines = [f"<b>Ingresos totales: ${total:.2f}</b>\n"]
            for src, amt in sorted(by_source.items(), key=lambda x: x[1], reverse=True):
                lines.append(f"  {src}: ${amt:.2f}")
            lines.append(f"\n{len(events)} transacciones registradas")
            await self._send(chat_id, "\n".join(lines))
        except Exception as exc:
            await self._send(chat_id, f"Error leyendo ingresos: {exc}")

    async def _cmd_logs(self, chat_id: str, args: str) -> None:
        try:
            n = int(args) if args.isdigit() else 20
            n = min(n, 50)
            from apps.core.tools.fly_tools import get_recent_logs
            logs = await get_recent_logs(n)
            if not logs:
                await self._send(chat_id, "Sin logs disponibles.")
                return
            text = f"<b>Últimos {n} logs:</b>\n<code>" + "\n".join(str(l)[:100] for l in logs[-n:]) + "</code>"
            await self._send(chat_id, text[:4000])
        except ImportError:
            await self._send(chat_id, "fly_tools no disponible. FLY_API_TOKEN requerido.")
        except Exception as exc:
            await self._send(chat_id, f"Error: {exc}")

    async def _cmd_ciclo(self, chat_id: str, _: str) -> None:
        await self._cmd_ganar(chat_id, _)

    async def _cmd_pausa(self, chat_id: str, _: str) -> None:
        try:
            from apps.core.scheduler import get_scheduler
            s = get_scheduler()
            if s:
                s.pause()
                await self._send(chat_id, "Scheduler pausado. Usa /reanudar para continuar.")
            else:
                await self._send(chat_id, "Scheduler no disponible.")
        except Exception as exc:
            await self._send(chat_id, f"Error: {exc}")

    async def _cmd_reanudar(self, chat_id: str, _: str) -> None:
        try:
            from apps.core.scheduler import get_scheduler
            s = get_scheduler()
            if s:
                s.resume()
                await self._send(chat_id, "Scheduler reanudado.")
            else:
                await self._send(chat_id, "Scheduler no disponible.")
        except Exception as exc:
            await self._send(chat_id, f"Error: {exc}")

    async def _cmd_pendientes(self, chat_id: str, _: str) -> None:
        if not self._pending_approvals:
            await self._send(chat_id, "Sin aprobaciones pendientes.")
            return
        lines = ["<b>Pendientes de aprobación:</b>\n"]
        for aid, approval in self._pending_approvals.items():
            lines.append(
                f"<b>ID {aid}:</b> {approval.get('action', '')}\n"
                f"  {approval.get('details', '')}\n"
                f"  /aprobar {aid} | /rechazar {aid}"
            )
        await self._send(chat_id, "\n".join(lines))

    async def _cmd_aprobar(self, chat_id: str, args: str) -> None:
        aid = args.strip()
        if aid not in self._pending_approvals:
            await self._send(chat_id, f"No encontré aprobación '{aid}'.")
            return
        approval = self._pending_approvals.pop(aid)
        fn = approval.get("fn")
        try:
            result = await fn() if asyncio.iscoroutinefunction(fn) else fn()
            await self._send(chat_id, f"Ejecutado: {approval.get('action', '')}\nResultado: {str(result)[:200]}")
        except Exception as exc:
            await self._send(chat_id, f"Falló: {exc}")

    async def _cmd_rechazar(self, chat_id: str, args: str) -> None:
        aid = args.strip()
        if aid in self._pending_approvals:
            a = self._pending_approvals.pop(aid)
            await self._send(chat_id, f"Rechazado: {a.get('action', '')}")
        else:
            await self._send(chat_id, f"No encontré aprobación '{aid}'.")

    async def _cmd_agentes(self, chat_id: str, _: str) -> None:
        await self._cmd_status(chat_id, _)

    async def _cmd_unknown(self, chat_id: str, _: str) -> None:
        await self._send(chat_id, "No conozco ese comando. /help para ver los disponibles.")

    # ── CONVERSACIÓN NATURAL ─────────────────────────────────────

    async def _handle_conversation(self, chat_id: str, text: str, sender: str) -> None:
        """
        Conversación libre con ARIA.
        Usa contexto del sistema + historial para responder como humano.
        """
        history = await self._get_history(chat_id)
        context = await self._get_system_context()

        ai = self._get_ai()
        if not ai:
            await self._send(chat_id, "No tengo acceso a IA ahora mismo. Revisa la config.")
            return

        owner = getattr(settings, "OWNER_NAME", sender or "jefe")
        persona = ARIA_PERSONA.format(
            owner=owner,
            context=context,
            history=history,
        )

        # Enriquecer con búsqueda web si la pregunta parece pedir información externa
        web_context = ""
        web_triggers = ["qué está", "tendencia", "oportunidad", "mercado", "busca", "investiga", "qué hay"]
        if any(t in text.lower() for t in web_triggers):
            try:
                from apps.core.tools.web_tools import WebTools
                wt = WebTools()
                sr = await wt.search_web(text, num_results=3)
                if sr.get("success") and sr.get("results"):
                    snippets = [f"- {r['title']}: {r['snippet']}" for r in sr["results"][:3]]
                    web_context = "\n\nResultados de internet para '" + text + "':\n" + "\n".join(snippets)
            except Exception:
                pass

        messages = [
            {"role": "system", "content": persona + web_context},
            {"role": "user", "content": text},
        ]

        try:
            from apps.core.tools.ai_client import AIModel
            resp = await ai.chat.completions.create(
                model=AIModel.FAST,
                messages=messages,
                max_tokens=300,
                temperature=0.7,
            )
            reply = resp.choices[0].message.content or "..."
            await self._send(chat_id, reply)
            await self._save_to_history(chat_id, text, reply)
        except Exception as exc:
            logger.error("[TelegramBot] AI error: %s", exc)
            await self._send(chat_id, "No puedo procesar eso ahora. Intenta de nuevo.")

    # ── APROBACIONES ─────────────────────────────────────────────

    async def request_approval(
        self,
        action: str,
        details: str,
        fn: Any,
        amount_usd: float = 0.0,
    ) -> dict[str, Any]:
        """
        Registra una acción pendiente de aprobación y notifica por Telegram.
        Usado por agentes cuando una acción requiere confirmación humana.
        """
        if not settings.TELEGRAM_BOT_TOKEN or not settings.TELEGRAM_CHAT_ID:
            return {"approved": False, "error": "Telegram no configurado"}

        self._approval_counter += 1
        aid = str(self._approval_counter)
        self._pending_approvals[aid] = {"action": action, "details": details, "fn": fn}

        cost_str = f" — costo: ${amount_usd:.2f}" if amount_usd > 0 else ""
        msg = (
            f"⚠️ <b>Aprobación requerida [{aid}]</b>\n\n"
            f"{action}{cost_str}\n"
            f"{details}\n\n"
            f"/aprobar {aid} | /rechazar {aid}"
        )
        await self._send(str(settings.TELEGRAM_CHAT_ID), msg)
        return {"approved": False, "pending": True, "approval_id": aid}

    async def notify(self, message: str) -> None:
        """Envía notificación directa al chat configurado."""
        if settings.TELEGRAM_CHAT_ID:
            await self._send(str(settings.TELEGRAM_CHAT_ID), message)

    # ── HISTORIAL Y CONTEXTO ─────────────────────────────────────

    async def _get_history(self, chat_id: str, max_turns: int = 6) -> str:
        """Recupera historial de conversación de Redis."""
        try:
            mc = self._get_memory()
            if not mc:
                return ""
            key = CONVERSATION_KEY.format(chat_id=chat_id)
            data = await asyncio.get_event_loop().run_in_executor(None, mc.get, key)
            if not data:
                return ""
            turns = json.loads(data)[-max_turns:]
            return "\n".join(
                f"Usuario: {t['user']}\nARIA: {t['aria']}" for t in turns
            )
        except Exception:
            return ""

    async def _save_to_history(self, chat_id: str, user_msg: str, aria_reply: str) -> None:
        """Guarda turno en Redis."""
        try:
            mc = self._get_memory()
            if not mc:
                return
            key = CONVERSATION_KEY.format(chat_id=chat_id)
            data = await asyncio.get_event_loop().run_in_executor(None, mc.get, key)
            turns = json.loads(data) if data else []
            turns.append({"user": user_msg, "aria": aria_reply, "ts": int(time.time())})
            turns = turns[-20:]
            await asyncio.get_event_loop().run_in_executor(
                None, lambda: mc.setex(key, CONVERSATION_TTL, json.dumps(turns))
            )
        except Exception as exc:
            logger.debug("[TelegramBot] No se pudo guardar historial: %s", exc)

    async def _get_system_context(self) -> str:
        """Genera contexto del sistema actual para la IA."""
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        lines = [f"Hora actual: {now}"]
        apis = []
        if settings.MEDIUM_TOKEN:
            apis.append("Medium")
        if getattr(settings, "GUMROAD_TOKEN", None):
            apis.append("Gumroad")
        if settings.STRIPE_SECRET_KEY:
            apis.append("Stripe")
        if getattr(settings, "BUFFER_ACCESS_TOKEN", None):
            apis.append("Buffer")
        if apis:
            lines.append(f"APIs activas: {', '.join(apis)}")
        else:
            lines.append("APIs: pocas configuradas — modo limitado")
        return "\n".join(lines)

    # ── HELPERS ──────────────────────────────────────────────────

    def _get_ai(self) -> Optional[Any]:
        if not self._ai_client:
            try:
                from apps.core.tools.ai_client import get_ai_client
                self._ai_client = get_ai_client()
            except Exception:
                pass
        return self._ai_client

    def _get_memory(self) -> Optional[Any]:
        if not self._memory_client:
            try:
                from apps.core.memory.redis_client import get_redis
                self._memory_client = get_redis()
            except Exception:
                pass
        return self._memory_client

    async def _send(self, chat_id: str, text: str, parse_mode: str = "HTML") -> None:
        if not settings.TELEGRAM_BOT_TOKEN:
            return
        url = f"{TELEGRAM_API}{settings.TELEGRAM_BOT_TOKEN}/sendMessage"
        try:
            await self._http.post(url, json={
                "chat_id": chat_id,
                "text": text,
                "parse_mode": parse_mode,
                "disable_web_page_preview": True,
            })
        except Exception as exc:
            logger.error("[TelegramBot] Error enviando mensaje: %s", exc)

    async def _send_startup_message(self) -> None:
        """Mensaje de inicio cuando ARIA arranca."""
        if not settings.TELEGRAM_CHAT_ID:
            return
        from datetime import datetime, timezone
        ts = datetime.now(timezone.utc).strftime("%H:%M UTC")
        await self._send(
            str(settings.TELEGRAM_CHAT_ID),
            f"<b>ARIA online</b> — {ts}\n\n"
            f"Arrancando ciclos de monetización. "
            f"Usa /ganar para forzar uno ahora o /oportunidad para ver qué detecté.",
        )


# ── SINGLETON ─────────────────────────────────────────────────

_bot_instance: Optional[AriaTelegramBot] = None


def get_bot() -> AriaTelegramBot:
    global _bot_instance
    if _bot_instance is None:
        _bot_instance = AriaTelegramBot()
    return _bot_instance
