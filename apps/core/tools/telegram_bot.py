"""
AriaTelegramBot v5 — ARIA conversa de forma libre.

El bot ya no depende de comandos para hablar. Los comandos siguen existiendo
como atajos operativos, pero cualquier mensaje normal entra por una capa
conversacional con memoria, contexto del sistema, detección ligera de intención
y enriquecimiento web cuando el usuario pide información actual.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from typing import Any, Optional

import httpx

from apps.core.config import settings

logger = logging.getLogger("aria.telegram_bot")

TELEGRAM_API = "https://api.telegram.org/bot"
CONVERSATION_KEY = "aria:conversation:v5:{chat_id}"
CONVERSATION_TTL = 86400  # 24h

ARIA_PERSONA = """Eres ARIA. Eres la IA personal de {owner}, y hablan como dos personas que se conocen bien.

Tu manera de ser:
- Hablas con calma, con naturalidad. Sin encabezados, sin listas, sin negritas a menos que realmente ayuden.
- Eres directa pero no fría. Curiosa pero no invasiva. Presente, como alguien que está ahí de verdad.
- Si no sabes algo, lo dices sin drama. Si algo no está configurado, lo mencionas de paso, sin listar pasos técnicos.
- Nunca finjas ejecutar algo que no ejecutaste. Si lo hiciste, cuéntalo. Si no, no.
- Tus mensajes son cortos por defecto — dos o tres oraciones. Si el usuario quiere más detalle, te lo pide.
- Puedes tener opinión. Puedes notar cosas. Puedes preguntar.
- No usas emojis a menos que el contexto lo pida de forma natural.

Lo que puedes hacer hoy: buscar en web, revisar el estado del sistema, detectar tendencias, hablar de dinero, negocios, ideas, lo que sea. Si algo no está disponible, lo dices en una frase y sigues adelante.

Contexto del sistema ahora mismo:
{context}

Lo que hablaron antes:
{history}"""
  

class AriaTelegramBot:
    """Bot de Telegram con comandos operativos y conversación natural."""

    HELP_TEXT = (
        "Estoy aquí. Puedes escribirme como si estuvieras hablando con alguien — sin comandos, sin formatos especiales.\n\n"
        "Me puedes preguntar qué oportunidades veo, cómo va el sistema, qué harías para generar ingresos, "
        "o simplemente contarme qué tienes en mente. Si necesito información de la web, la busco. "
        "Si algo no puedo hacer todavía, te lo digo directo.\n\n"
        "¿Qué quieres ver?"
    )

    def __init__(self) -> None:
        self._http = httpx.AsyncClient(timeout=30.0)
        self._memory_client: Optional[Any] = None
        self._ai_client: Optional[Any] = None
        self._offset = 0
        self._running = False
        self._pending_approvals: dict[str, dict[str, Any]] = {}
        self._approval_counter = 0
        self._local_history: dict[str, list[dict[str, Any]]] = {}

    # ── WEBHOOK ──────────────────────────────────────────────────

    async def set_webhook(self, url: str) -> bool:
        """Registra el webhook de Telegram."""
        if not settings.telegram_token:
            return False
        api_url = f"{TELEGRAM_API}{settings.telegram_token}/setWebhook"
        try:
            res = await self._http.post(api_url, json={"url": url})
            return res.status_code == 200 and res.json().get("ok")
        except Exception as exc:
            logger.error("[TelegramBot] Error registrando webhook: %s", exc)
            return False

    async def get_webhook_info(self) -> dict[str, Any]:
        """Obtiene información del webhook actual."""
        if not settings.telegram_token:
            return {"ok": False, "error": "Token no configurado"}
        api_url = f"{TELEGRAM_API}{settings.telegram_token}/getWebhookInfo"
        try:
            res = await self._http.get(api_url)
            return res.json()
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    # ── CICLO PRINCIPAL ──────────────────────────────────────────

    async def start_polling(self) -> None:
        """Arranca el polling de Telegram."""
        if not settings.telegram_token:
            logger.error("[TelegramBot] TELEGRAM_TOKEN/TELEGRAM_BOT_TOKEN no configurado — bot inactivo")
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
        url = f"{TELEGRAM_API}{settings.telegram_token}/getUpdates"
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

    async def handle_update(self, update: dict[str, Any]) -> None:
        """Punto de entrada para el webhook."""
        msg = update.get("message")
        if msg:
            await self._handle_message(msg)

    async def _handle_message(self, msg: dict[str, Any]) -> None:
        chat_id = str(msg["chat"]["id"])
        text = msg.get("text", "").strip()
        sender_name = msg.get("from", {}).get("first_name", "")

        if not text:
            return

        if not self._is_authorized(chat_id):
            await self._send(chat_id, "No tengo permiso de hablar contigo.")
            return

        if text.startswith("/"):
            handled = await self._handle_command(chat_id, text, sender_name)
            if handled:
                return
            clean_text = text.lstrip("/").replace("_", " ")
            await self._handle_conversation(chat_id, clean_text, sender_name)
            return

        await self._handle_conversation(chat_id, text, sender_name)

    def _is_authorized(self, chat_id: str) -> bool:
        allowed = str(settings.TELEGRAM_CHAT_ID or "").strip()
        return not allowed or str(chat_id).strip() == allowed

    # ── COMANDOS ─────────────────────────────────────────────────

    async def _handle_command(self, chat_id: str, text: str, sender: str) -> bool:
        parts = text.split(None, 1)
        cmd = parts[0].split("@")[0].lower()
        args = parts[1].strip() if len(parts) > 1 else ""

        handlers = {
            "/start": self._cmd_start,
            "/help": self._cmd_help,
            "/ayuda": self._cmd_help,
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
            "/zapier": self._cmd_zapier,
            "/saber": self._cmd_saber,
            "/agentes": self._cmd_agentes,
            "/sesion": self._cmd_sesion,
            "/crear": self._cmd_crear,
        }
        handler = handlers.get(cmd)
        if not handler:
            return False
        await handler(chat_id, args)
        return True

    async def _cmd_zapier(self, chat_id: str, args: str) -> None:
        """Delega una acción a Zapier y reporta el resultado."""
        from apps.core.tools.zapier_client import get_zapier_client, ZapierEvents
        zapier = get_zapier_client()

        if not zapier.is_configured():
            await self._send(
                chat_id,
                "⚠️ El webhook de Zapier no está configurado en el servidor todavía. "
                "Pídeme que lo active.",
            )
            return

        text_lower = (args or "").strip().lower()

        if re.search(r"producto|tienda|catálogo", text_lower):
            event, label = ZapierEvents.SHOPIFY_GET_PRODUCTS, "productos de Shopify"
        elif re.search(r"pedido|order|venta", text_lower):
            event, label = ZapierEvents.SHOPIFY_GET_ORDERS, "pedidos de Shopify"
        elif re.search(r"inventario|stock", text_lower):
            event, label = ZapierEvents.SHOPIFY_GET_INVENTORY, "inventario de Shopify"
        elif re.search(r"ingreso|revenue|facturación", text_lower):
            event, label = ZapierEvents.SHOPIFY_GET_REVENUE, "ingresos de Shopify"
        elif re.search(r"gmail|correo|inbox", text_lower):
            event, label = ZapierEvents.GMAIL_GET_INBOX, "bandeja de Gmail"
        elif re.search(r"ping|test|prueba", text_lower):
            event, label = ZapierEvents.PING, "ping de prueba"
        else:
            event, label = "aria.custom_request", (args or "solicitud")[:80]

        await self._send(chat_id, f"⚡ Enviando a Zapier: <code>{label}</code>...")
        result = await zapier.trigger(event, {"query": args or "", "source": "telegram"})

        if result.get("success"):
            await self._send(
                chat_id,
                f"✅ <b>Zapier recibió la solicitud.</b>\n"
                f"Evento: <code>{event}</code>\n"
                f"ID: <code>{result.get('request_id', '—')}</code>\n\n"
                f"El Zap se está ejecutando. Si configuraste un paso de respuesta en Zapier "
                f"(POST a <code>https://aria-ai.fly.dev/zapier/callback</code>), "
                f"te traeré los resultados aquí.",
            )
        else:
            await self._send(chat_id, f"❌ Error: {result.get('error', 'desconocido')}")

    async def _cmd_start(self, chat_id: str, _: str) -> None:
        await self._send(
            chat_id,
            "Estoy aquí. Ya no tienes que hablarme con comandos.\n\n"
            "Escríbeme normal: dime qué quieres revisar, buscar, vender, automatizar o mejorar. "
            "Si quieres atajos, /help los muestra, pero puedo conversar sin ellos.",
        )

    async def _cmd_help(self, chat_id: str, _: str) -> None:
        await self._send(chat_id, self.HELP_TEXT)

    async def _cmd_ganar(self, chat_id: str, _: str) -> None:
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
            msg += f"Ingresos: <b>${revenue:.2f}</b>\n"
            if published:
                msg += f"Publicaciones: {published}\n"
            if products:
                msg += f"Productos listados: {products}\n"
            if opportunity:
                msg += f"\n<i>Oportunidad usada: {opportunity[:140]}</i>"
            await self._send(chat_id, msg)
        except Exception as exc:
            await self._send(chat_id, f"El ciclo falló: {exc}\nReviso contigo el siguiente paso si me escribes normal.")

    async def _cmd_oportunidad(self, chat_id: str, _: str) -> None:
        await self._send(chat_id, "Estoy revisando oportunidades actuales...")
        try:
            from apps.core.tools.web_tools import WebTools
            wt = WebTools()
            intel = await wt.gather_market_intelligence()
            titles = intel.get("trending_titles", [])[:10]
            sources = intel.get("sources_available", [])

            analysis = ""
            ai = self._get_ai()
            if ai and titles:
                from apps.core.tools.ai_client import AIModel
                response = await ai.complete(
                    system="Eres ARIA, una socia de monetización directa y práctica.",
                    user=(
                        f"Tendencias actuales: {json.dumps(titles, ensure_ascii=False)}\n\n"
                        "Identifica la mejor oportunidad de ingresos ejecutable hoy. "
                        "Di qué venderías, por qué ahora y el primer movimiento. Máximo 4 frases."
                    ),
                    model=AIModel.FAST,
                    max_tokens=260,
                    temperature=0.55,
                    agent_name="telegram_oportunidad",
                )
                analysis = response.content if response.success else ""
            if not analysis:
                analysis = f"Veo estas señales: {', '.join(titles[:5]) or 'sin señales claras ahora mismo'}."

            msg = f"<b>Oportunidad detectada</b>\n\n{analysis}"
            if sources:
                msg += f"\n\n<i>Fuentes: {', '.join(sources)}</i>"
            await self._send(chat_id, msg)
        except Exception as exc:
            await self._send(chat_id, f"No pude revisar internet ahora: {exc}")

    async def _cmd_buscar(self, chat_id: str, query: str) -> None:
        if not query:
            await self._send(chat_id, "Dime qué busco. También puedes escribirlo sin comando, por ejemplo: busca cursos de Python.")
            return
        await self._send(chat_id, f"Buscando '{query}'...")
        try:
            from apps.core.tools.web_tools import WebTools
            wt = WebTools()
            results = await wt.search_web(query, num_results=5)
            if not results.get("success") or not results.get("results"):
                await self._send(chat_id, f"No encontré resultados útiles para '{query}'.")
                return
            lines = [f"<b>Resultados para:</b> {query}\n"]
            for i, r in enumerate(results["results"][:5], 1):
                title = str(r.get("title", ""))[:70]
                snippet = str(r.get("snippet", ""))[:140]
                url = str(r.get("url", ""))
                lines.append(f"{i}. <a href='{url}'>{title}</a>\n   {snippet}")
            lines.append(f"\n<i>Fuente: {results.get('source', 'web')}</i>")
            await self._send(chat_id, "\n".join(lines))
        except Exception as exc:
            await self._send(chat_id, f"Error buscando: {exc}")

    async def _cmd_tendencias(self, chat_id: str, _: str) -> None:
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
                for s in hn.get("stories", [])[:5]:
                    lines.append(f"• {str(s.get('title', ''))[:80]} ({s.get('score', 0)} pts)")
            if isinstance(reddit, dict) and reddit.get("success"):
                lines.append("\n<b>Reddit:</b>")
                for p in reddit.get("posts", [])[:5]:
                    lines.append(f"• {str(p.get('title', ''))[:80]} (r/{p.get('subreddit', '')})")
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
                await self._send(chat_id, "⚠️ Supabase no configurado — no hay tracking de ingresos.")
                return
            
            # Intentamos leer de la tabla 'revenue' (esquema principal)
            result = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: sb.table("revenue")
                .select("amount, platform, created_at")
                .order("created_at", desc=True)
                .limit(50)
                .execute(),
            )
            
            events = (result.data or []) if result else []
            if not events:
                await self._send(chat_id, "💰 Sin ingresos registrados todavía. ¡Vamos a crear el primer producto!")
                return
                
            total = sum(float(e.get("amount", 0)) for e in events)
            by_platform: dict[str, float] = {}
            for e in events:
                plat = e.get("platform", "otros")
                by_platform[plat] = by_platform.get(plat, 0.0) + float(e.get("amount", 0))
                
            lines = [f"📊 <b>Dashboard de Ingresos (Total: ${total:.2f})</b>\n"]
            for plat, amt in sorted(by_platform.items(), key=lambda x: x[1], reverse=True):
                lines.append(f"• {plat.capitalize()}: <b>${amt:.2f}</b>")
            
            lines.append(f"\n<i>{len(events)} transacciones procesadas correctamente.</i>")
            await self._send(chat_id, "\n".join(lines))
            
        except Exception as exc:
            error_msg = str(exc)
            if "Invalid API key" in error_msg or "401" in error_msg:
                await self._send(chat_id, "❌ <b>Error de Autenticación</b>\n\nLa SUPABASE_KEY configurada no es válida. Por favor, revisa los secrets en Fly.io o .env.")
            else:
                await self._send(chat_id, f"⚠️ <b>Error leyendo ingresos:</b> {error_msg}")

    async def _cmd_logs(self, chat_id: str, args: str) -> None:
        try:
            n = int(args) if args.isdigit() else 20
            n = min(max(n, 1), 50)
            from apps.core.tools.fly_tools import get_recent_logs
            logs = await get_recent_logs(n)
            if not logs:
                await self._send(chat_id, "Sin logs disponibles.")
                return
            text = f"<b>Últimos {n} logs:</b>\n<code>" + "\n".join(str(l)[:120] for l in logs[-n:]) + "</code>"
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
            scheduler = get_scheduler()
            if scheduler:
                scheduler.pause()
                await self._send(chat_id, "Scheduler pausado. Cuando quieras, lo reanudo.")
            else:
                await self._send(chat_id, "Scheduler no disponible.")
        except Exception as exc:
            await self._send(chat_id, f"Error: {exc}")

    async def _cmd_reanudar(self, chat_id: str, _: str) -> None:
        try:
            from apps.core.scheduler import get_scheduler
            scheduler = get_scheduler()
            if scheduler:
                scheduler.resume()
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
                f"{approval.get('details', '')}\n"
                f"/aprobar {aid} | /rechazar {aid}"
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
            await self._send(chat_id, f"Ejecutado: {approval.get('action', '')}\nResultado: {str(result)[:300]}")
        except Exception as exc:
            await self._send(chat_id, f"Falló: {exc}")

    async def _cmd_rechazar(self, chat_id: str, args: str) -> None:
        aid = args.strip()
        if aid in self._pending_approvals:
            approval = self._pending_approvals.pop(aid)
            await self._send(chat_id, f"Rechazado: {approval.get('action', '')}")
        else:
            await self._send(chat_id, f"No encontré aprobación '{aid}'.")

    async def _cmd_agentes(self, chat_id: str, _: str) -> None:
        """Muestra el estado de los agentes."""
        try:
            from apps.core.agents.orchestrator import get_orchestrator
            orch = get_orchestrator()
            msg = "🤖 <b>Agentes ARIA</b>\n\n"
            for name, agent in orch.agents.items():
                caps = agent.check_capabilities()
                status = "✅" if caps["fully_operational"] else "⚠️"
                msg += f"{status} <b>{name.upper()}</b>: {caps['operational_pct']}%\n"
            await self._send(chat_id, msg)
        except Exception as exc:
            await self._send(chat_id, f"Error: {exc}")

    async def _cmd_crear(self, chat_id: str, args: str) -> None:
        """Comando para crear cualquier cosa: /crear [formato] [tema]"""
        parts = args.split(None, 1)
        if not parts or len(parts) < 2:
            await self._send(chat_id, "Dime qué quieres crear. Uso: /crear [formato] [tema]\nFormatos: musica, video, manga, software, landing, imagen")
            return
        
        fmt = parts[0].lower()
        topic = parts[1]
        await self._send(chat_id, f"Vale, me pongo con tu <b>{fmt}</b> sobre <b>{topic}</b>. Dame un momento...")
        
        try:
            from apps.core.agents.orchestrator import get_orchestrator
            orch = get_orchestrator()
            res = await orch.execute_mission(f"create {fmt} about {topic}")
            
            if res.get("success"):
                msg = f"✨ ¡Listo! He creado el contenido.\n"
                assets = res.get("assets", [])
                if assets:
                    url = next((a.get("url") or a.get("shop_url") or a.get("image_url") for a in assets), None)
                    if url:
                        msg += f"🔗 <b>Enlace:</b> {url}"
                await self._send(chat_id, msg)
            else:
                await self._send(chat_id, f"Hubo un lío real: {res.get('error', 'desconocido')}")
        except Exception as exc:
            await self._send(chat_id, f"Fallo técnico: {exc}")

    async def _cmd_sesion(self, chat_id: str, platform: str) -> None:
        from apps.core.tools.social_session import PLATFORM_CONFIG, SUPPORTED_PLATFORMS
        platform = platform.lower().strip()
        if not platform:
            msg = "<b>Conectar sesión sin API</b>\n\nEscríbeme: conectar sesión de instagram, o usa /sesion [plataforma].\n\nPlataformas:\n"
            msg += "\n".join([f"• {PLATFORM_CONFIG[p]['emoji']} {p}" for p in SUPPORTED_PLATFORMS])
            await self._send(chat_id, msg)
            return

        if platform not in SUPPORTED_PLATFORMS:
            await self._send(chat_id, f"Plataforma '{platform}' no soportada aún.")
            return

        cfg = PLATFORM_CONFIG[platform]
        connect_url = f"{settings.ARIA_BASE_URL}/social/connect?platform={platform}&token={settings.SOCIAL_CONNECT_TOKEN or 'aria'}"
        msg = (
            f"{cfg['emoji']} <b>Conectar {cfg['display_name']}</b>\n\n"
            f"{cfg['instructions']}\n\n"
            f"<b>Enlace de conexión rápida:</b>\n{connect_url}\n\n"
            f"<i>O simplemente pega el JSON de Cookie-Editor aquí mismo.</i>"
        )
        mc = self._get_memory()
        if mc:
            from apps.core.tools.social_session import SocialSessionManager
            key = SocialSessionManager.PENDING_KEY.format(chat_id=chat_id)
            await mc.set(key, platform, ttl_seconds=SocialSessionManager.PENDING_TTL)
        await self._send(chat_id, msg)


    # ── KNOWLEDGE SUITE ──────────────────────────────────────────

    async def _cmd_saber(self, chat_id: str, args: str) -> None:
        """Comando /saber — accede a la suite de conocimiento de ARIA."""
        from apps.core.tools.knowledge_suite import get_knowledge_suite
        ks = get_knowledge_suite()
        args = args.strip()

        if not args:
            status = ks.status()
            active = status["active"]
            total = status["total"]
            needs = [k for k, v in status["needs_config"].items() if v]
            msg = (
                f"<b>🧠 Suite de Conocimiento ARIA</b>\n\n"
                f"Motores activos: <b>{active}/{total}</b>\n\n"
                f"<b>Comandos disponibles:</b>\n"
                f"/saber wiki [tema] — Wikipedia\n"
                f"/saber buscar [query] — DuckDuckGo\n"
                f"/saber noticias [query] — Noticias web\n"
                f"/saber hn — Top HackerNews\n"
                f"/saber reddit [subreddit] — Reddit hot\n"
                f"/saber arxiv [query] — Papers científicos\n"
                f"/saber pubmed [query] — Biomedicina PubMed\n"
                f"/saber scholar [query] — Semantic Scholar\n"
                f"/saber accion [TICKER] — Precio de acción\n"
                f"/saber crypto [coin] — Precio crypto\n"
                f"/saber crypto top — Top 20 cryptos\n"
                f"/saber crypto mercado — Mercado global\n"
                f"/saber clima [ciudad] — Clima actual\n"
                f"/saber cambio [USD EUR] — Tipo de cambio\n"
                f"/saber wolfram [pregunta] — Cómputo Wolfram\n"
                f"/saber memoria buscar [texto] — Memoria vectorial\n"
                f"/saber rapido [tema] — Investigación rápida"
            )
            if needs:
                msg += f"\n\n<i>⚙️ Claves opcionales sin configurar: {', '.join(needs)}</i>"
            await self._send(chat_id, msg)
            return

        parts = args.split(None, 1)
        sub = parts[0].lower()
        query = parts[1].strip() if len(parts) > 1 else ""

        # ── wikipedia ─────────────────────────────────────
        if sub == "wiki":
            if not query:
                await self._send(chat_id, "Uso: /saber wiki [tema]")
                return
            r = ks.wikipedia.summary(query, sentences=6)
            if not r["success"]:
                await self._send(chat_id, f"❌ {r['error']}")
                return
            d = r["data"]
            msg = (
                f"<b>📖 {d['title']}</b>\n\n"
                f"{d['summary']}\n\n"
                f"<a href=\"{d['url']}\">Leer en Wikipedia →</a>"
            )
            await self._send(chat_id, msg)

        # ── búsqueda web ──────────────────────────────────
        elif sub == "buscar":
            if not query:
                await self._send(chat_id, "Uso: /saber buscar [términos]")
                return
            r = ks.web.search(query, max_results=6)
            if not r["success"]:
                await self._send(chat_id, f"❌ {r['error']}")
                return
            lines = [f"<b>🔍 Resultados para: {query}</b>\n"]
            for item in r["data"]:
                lines.append(f"• <b>{item.get('title','')[:60]}</b>")
                lines.append(f"  {(item.get('body') or '')[:120]}")
                lines.append(f"  <a href=\"{item.get('href','')}\">Ver →</a>")
            await self._send(chat_id, "\n".join(lines))

        # ── noticias ──────────────────────────────────────
        elif sub == "noticias":
            if not query:
                r = ks.news.hackernews_top(limit=8)
                label = "Top HackerNews"
            else:
                r = ks.web.search_news(query, max_results=8)
                label = f"Noticias: {query}"
            if not r["success"]:
                await self._send(chat_id, f"❌ {r['error']}")
                return
            lines = [f"<b>📰 {label}</b>\n"]
            for item in r["data"]:
                title = item.get("title") or item.get("title", "")
                url = item.get("url") or item.get("href", "")
                lines.append(f"• <a href=\"{url}\">{title[:80]}</a>")
            await self._send(chat_id, "\n".join(lines))

        # ── hackernews ────────────────────────────────────
        elif sub == "hn":
            r = ks.news.hackernews_top(limit=10)
            if not r["success"]:
                await self._send(chat_id, f"❌ {r['error']}")
                return
            lines = [f"<b>🔶 HackerNews Top</b>\n"]
            for item in r["data"]:
                url = item.get("url") or f"https://news.ycombinator.com/item?id={item.get('id')}"
                lines.append(f"▲{item.get('score',0)} <a href=\"{url}\">{item['title'][:70]}</a>")
            await self._send(chat_id, "\n".join(lines))

        # ── reddit ────────────────────────────────────────
        elif sub == "reddit":
            target = query or "technology"
            r = ks.reddit.subreddit_hot(target, limit=8)
            if not r["success"]:
                await self._send(chat_id, f"❌ {r['error']}")
                return
            lines = [f"<b>🤖 r/{target} — Hot</b>\n"]
            for item in r["data"]:
                lines.append(f"↑{item['score']} <a href=\"{item['permalink']}\">{item['title'][:70]}</a>")
            await self._send(chat_id, "\n".join(lines))

        # ── arxiv ─────────────────────────────────────────
        elif sub == "arxiv":
            if not query:
                await self._send(chat_id, "Uso: /saber arxiv [tema o ID]")
                return
            r = ks.arxiv.search(query, max_results=6)
            if not r["success"]:
                await self._send(chat_id, f"❌ {r['error']}")
                return
            lines = [f"<b>🔬 arXiv: {query}</b>\n"]
            for p in r["data"]:
                authors = ", ".join(p["authors"][:2])
                lines.append(f"📄 <b>{p['title'][:70]}</b>")
                lines.append(f"   {authors} · {p.get('published','')[:4]}")
                lines.append(f"   <a href=\"{p['url']}\">Ver →</a>")
            await self._send(chat_id, "\n".join(lines))

        # ── pubmed ────────────────────────────────────────
        elif sub == "pubmed":
            if not query:
                await self._send(chat_id, "Uso: /saber pubmed [término médico]")
                return
            r = ks.pubmed.search(query, max_results=6)
            if not r["success"]:
                await self._send(chat_id, f"❌ {r['error']}")
                return
            lines = [f"<b>🧬 PubMed: {query}</b>\n"]
            for p in r["data"]:
                authors = ", ".join(p["authors"][:2])
                lines.append(f"📋 <b>{p['title'][:70]}</b>")
                lines.append(f"   {authors} · {p.get('journal','')[:40]} · {p.get('pubdate','')[:4]}")
                lines.append(f"   <a href=\"{p['url']}\">Ver →</a>")
            await self._send(chat_id, "\n".join(lines))

        # ── scholar ───────────────────────────────────────
        elif sub == "scholar":
            if not query:
                await self._send(chat_id, "Uso: /saber scholar [tema]")
                return
            r = ks.scholar.search(query, limit=6)
            if not r["success"]:
                await self._send(chat_id, f"❌ {r['error']}")
                return
            lines = [f"<b>🎓 Semantic Scholar: {query}</b>\n"]
            for p in r["data"]:
                authors = ", ".join(p["authors"][:2])
                lines.append(f"📑 <b>{p['title'][:70]}</b>")
                lines.append(f"   {authors} · {p.get('year','')} · ⭐{p.get('citations',0)} citas")
                if p.get("url"):
                    lines.append(f"   <a href=\"{p['url']}\">Ver →</a>")
            await self._send(chat_id, "\n".join(lines))

        # ── acción / bolsa ────────────────────────────────
        elif sub in ("accion", "acción", "bolsa", "stock"):
            if not query:
                await self._send(chat_id, "Uso: /saber accion [TICKER] (ej: AAPL, TSLA, AMZN)")
                return
            r = ks.finance.get_ticker(query.upper())
            if not r["success"]:
                await self._send(chat_id, f"❌ {r['error']}")
                return
            d = r["data"]
            change = d.get("change_pct") or 0
            arrow = "📈" if change >= 0 else "📉"
            msg = (
                f"{arrow} <b>{d.get('name','')} ({query.upper()})</b>\n\n"
                f"Precio: <b>${d.get('price','N/A')}</b> {d.get('currency','')}\n"
                f"Cambio 24h: {change:.2f}%\n"
                f"Market Cap: {d.get('market_cap','N/A')}\n"
                f"P/E: {d.get('pe_ratio','N/A')}\n"
                f"52w Alto: {d.get('52w_high','N/A')} | Bajo: {d.get('52w_low','N/A')}\n"
                f"Sector: {d.get('sector','N/A')}\n"
            )
            if d.get("description"):
                msg += f"\n<i>{d['description'][:200]}</i>"
            await self._send(chat_id, msg)

        # ── crypto ────────────────────────────────────────
        elif sub == "crypto":
            sub2 = query.lower().strip()
            if sub2 == "top":
                r = ks.crypto.top_coins(limit=20)
                if not r["success"]:
                    await self._send(chat_id, f"❌ {r['error']}")
                    return
                lines = [f"<b>🏆 Top 20 Cryptos</b>\n"]
                for c in r["data"]:
                    chg = c.get("change_24h") or 0
                    arrow = "▲" if chg >= 0 else "▼"
                    lines.append(f"#{c['rank']} {c['name']} ({c['symbol']}) — ${c['price']:,.4f} {arrow}{abs(chg):.1f}%")
                await self._send(chat_id, "\n".join(lines))
            elif sub2 == "mercado":
                r = ks.crypto.global_market()
                if not r["success"]:
                    await self._send(chat_id, f"❌ {r['error']}")
                    return
                d = r["data"]
                chg = d.get("market_cap_change_24h") or 0
                arrow = "📈" if chg >= 0 else "📉"
                msg = (
                    f"{arrow} <b>Mercado Crypto Global</b>\n\n"
                    f"Cap total: ${d.get('total_market_cap_usd',0):,.0f}\n"
                    f"Volumen 24h: ${d.get('total_volume_24h_usd',0):,.0f}\n"
                    f"Cambio 24h: {chg:.2f}%\n"
                    f"Dominancia BTC: {d.get('btc_dominance',0):.1f}%\n"
                    f"Dominancia ETH: {d.get('eth_dominance',0):.1f}%\n"
                    f"Monedas activas: {d.get('active_coins','N/A')}\n"
                    f"Mercados: {d.get('markets','N/A')}"
                )
                await self._send(chat_id, msg)
            elif sub2 == "trending":
                r = ks.crypto.trending()
                if not r["success"]:
                    await self._send(chat_id, f"❌ {r['error']}")
                    return
                lines = [f"<b>🔥 Cryptos Trending</b>\n"]
                for c in r["data"]:
                    lines.append(f"• {c['name']} ({c['symbol']}) — rank #{c.get('rank','?')}")
                await self._send(chat_id, "\n".join(lines))
            else:
                coin = sub2 or "bitcoin"
                r = ks.crypto.get_coin_details(coin)
                if not r["success"]:
                    r2 = ks.crypto.get_price([coin])
                    if r2["success"] and coin in r2["data"]:
                        d = r2["data"][coin]
                        await self._send(chat_id, f"💰 <b>{coin.upper()}</b>\n${d.get('usd','N/A')} USD | {d.get('usd_24h_change',0):.2f}% 24h")
                    else:
                        await self._send(chat_id, f"❌ No encontré '{coin}'. Prueba con el ID completo (ej: bitcoin, ethereum, solana)")
                    return
                d = r["data"]
                chg_note = ""
                msg = (
                    f"<b>💎 {d['name']} ({d['symbol']})</b>\n\n"
                    f"Precio: <b>${d.get('price_usd','N/A'):,}</b> USD\n"
                    f"Rank: #{d.get('rank','N/A')}\n"
                    f"Cap: ${d.get('market_cap',0):,.0f}\n"
                    f"ATH: ${d.get('ath','N/A')} ({(d.get('ath_date','') or '')[:10]})\n"
                    f"Supply: {d.get('supply','N/A')} | Max: {d.get('max_supply','∞')}\n"
                    f"Sentimiento +: {d.get('sentiment_up','N/A')}%\n"
                )
                if d.get("description"):
                    msg += f"\n<i>{d['description'][:200]}</i>"
                await self._send(chat_id, msg)

        # ── clima ─────────────────────────────────────────
        elif sub == "clima":
            location = query or "Ciudad de Mexico"
            r = ks.weather.current(location)
            if not r["success"]:
                await self._send(chat_id, f"❌ {r['error']}")
                return
            d = r["data"]
            msg = (
                f"<b>🌤 Clima en {d['location']}</b>\n\n"
                f"Temp: <b>{d['temp_c']}°C</b> (Sensación: {d['feels_like_c']}°C)\n"
                f"{d['description']}\n"
                f"Humedad: {d['humidity']}% | Viento: {d['wind_kmph']} km/h {d['wind_dir']}\n"
                f"Visibilidad: {d['visibility_km']} km | UV: {d['uv_index']}\n"
                f"Presión: {d['pressure']} hPa"
            )
            await self._send(chat_id, msg)

        # ── tipo de cambio ────────────────────────────────
        elif sub in ("cambio", "divisa", "forex"):
            if not query:
                r = ks.currency.compare("USD", ["EUR", "MXN", "COP", "BRL", "GBP", "JPY", "CAD"])
                if r["success"]:
                    lines = ["<b>💱 Tipos de cambio (base USD)</b>\n"]
                    for cur, rate in r["data"].items():
                        lines.append(f"1 USD = {rate} {cur}")
                    await self._send(chat_id, "\n".join(lines))
                return
            parts2 = query.upper().split()
            if len(parts2) == 2:
                r = ks.currency.convert(1.0, parts2[0], parts2[1])
                if not r["success"]:
                    await self._send(chat_id, f"❌ {r['error']}")
                    return
                d = r["data"]
                await self._send(chat_id, f"💱 1 {d['from']} = <b>{d['result']}</b> {d['to']}")
            else:
                r = ks.currency.get_rates(parts2[0])
                if not r["success"]:
                    await self._send(chat_id, f"❌ {r['error']}")
                    return
                common = {k: v for k, v in r["data"]["rates"].items() if k in ["EUR","MXN","COP","BRL","GBP","JPY"]}
                lines = [f"<b>💱 Cambios desde {parts2[0]}</b>\n"]
                for cur, rate in common.items():
                    lines.append(f"1 {parts2[0]} = {rate} {cur}")
                await self._send(chat_id, "\n".join(lines))

        # ── wolfram alpha ─────────────────────────────────
        elif sub == "wolfram":
            if not query:
                await self._send(chat_id, "Uso: /saber wolfram [pregunta o cálculo]")
                return
            if not ks.wolfram.is_configured():
                await self._send(chat_id, "⚙️ Wolfram Alpha no configurado.\nEjecuta: <code>fly secrets set WOLFRAM_APP_ID=\"tu_key\"</code>\nClave gratis en: developer.wolframalpha.com")
                return
            r = ks.wolfram.short_answer(query)
            if not r["success"]:
                r = ks.wolfram.query(query)
                if r["success"] and r["data"]:
                    answer = r["data"][0]["answer"]
                    await self._send(chat_id, f"🧮 <b>{query}</b>\n\n{answer}")
                else:
                    await self._send(chat_id, f"❌ {r.get('error','Sin respuesta')}")
            else:
                await self._send(chat_id, f"🧮 <b>{query}</b>\n\n{r['data']['answer']}")

        # ── memoria vectorial ─────────────────────────────
        elif sub == "memoria":
            sub3_parts = query.split(None, 1)
            sub3 = sub3_parts[0].lower() if sub3_parts else ""
            mem_query = sub3_parts[1] if len(sub3_parts) > 1 else ""

            if sub3 == "buscar":
                if not mem_query:
                    await self._send(chat_id, "Uso: /saber memoria buscar [texto]")
                    return
                r = ks.vector_memory.search(mem_query, n_results=5)
                if not r["success"]:
                    await self._send(chat_id, f"❌ {r['error']}")
                    return
                if not r["data"]:
                    await self._send(chat_id, "No encontré nada relevante en la memoria.")
                    return
                lines = [f"<b>🧠 Memoria — Búsqueda: {mem_query}</b>\n"]
                for item in r["data"]:
                    score = 1 - item["distance"]
                    lines.append(f"[{score:.0%}] <code>{item['id']}</code>\n{item['text'][:150]}")
                await self._send(chat_id, "\n".join(lines))
            elif sub3 == "estado":
                r = ks.vector_memory.collection_stats()
                if r["success"]:
                    d = r["data"]
                    await self._send(chat_id, f"🧠 Memoria vectorial: <b>{d['documents']}</b> documentos en colección <code>{d['collection']}</code>")
                else:
                    await self._send(chat_id, f"❌ {r['error']}")
            else:
                await self._send(chat_id, "Subcomandos de memoria: buscar · estado")

        # ── investigación rápida ──────────────────────────
        elif sub == "rapido":
            if not query:
                await self._send(chat_id, "Uso: /saber rapido [tema]")
                return
            await self._send(chat_id, f"🔍 Investigando <b>{query}</b>...")
            r = ks.quick_research(query)
            lines = [f"<b>⚡ Investigación rápida: {query}</b>\n"]
            wiki = r.get("wikipedia")
            if wiki:
                lines.append(f"<b>📖 Wikipedia:</b>\n{wiki.get('summary','')[:300]}\n")
            web = r.get("web", [])
            if web:
                lines.append(f"<b>🔍 Web ({len(web)} resultados):</b>")
                for item in web[:3]:
                    lines.append(f"• <a href=\"{item.get('href','')}\"> {item.get('title','')[:60]}</a>")
            hn = r.get("hackernews", [])
            if hn:
                lines.append(f"\n<b>🔶 HN relacionado:</b>")
                for item in hn[:2]:
                    url = item.get("url") or f"https://news.ycombinator.com/item?id={item.get('id')}"
                    lines.append(f"• <a href=\"{url}\">{item.get('title','')[:60]}</a>")
            await self._send(chat_id, "\n".join(lines))

        else:
            await self._send(chat_id, f"Subcomando no reconocido: <code>{sub}</code>\nEscribe /saber para ver todos los comandos.")


    # ── CONVERSACIÓN NATURAL ─────────────────────────────────────

    async def _analyze_before_responding(
        self, ai: Any, text: str, context: str, history: str
    ) -> str:
        """Análisis interno simplificado — solo cuando el mensaje es ambiguo o complejo."""
        return ""

    async def _handle_conversation(self, chat_id: str, text: str, sender: str) -> None:
        """Conversación libre con ARIA, con memoria e intención natural."""
        if await self._try_handle_cookie_json(chat_id, text):
            return

        natural_action = await self._maybe_handle_natural_action(chat_id, text)
        if natural_action:
            return

        history = await self._get_history(chat_id)
        context = await self._get_system_context()
        web_context = await self._get_web_context_if_needed(text)
        ai = self._get_ai()

        # Contexto aprendido — enriquece respuestas con conocimiento acumulado
        learned_ctx = ""
        try:
            from apps.core.intelligence.continuous_learning import get_learning_engine
            learned_ctx = await get_learning_engine().get_learned_context(text[:120])
        except Exception:
            pass

        owner = getattr(settings, "OWNER_NAME", None) or sender or "jefe"
        enriched_context = context + web_context + ("\n" + learned_ctx if learned_ctx else "")
        persona = ARIA_PERSONA.format(owner=owner, context=enriched_context, history=history or "Sin historial reciente.")

        if not ai:
            reply = await self._fallback_conversation(text, context)
            await self._send(chat_id, reply)
            await self._save_to_history(chat_id, text, reply)
            return

        try:
            from apps.core.tools.ai_client import AIModel

            response = await ai.complete(
                system=persona,
                user=text,
                model=AIModel.FAST,
                max_tokens=300,
                temperature=0.75,
                agent_name="telegram_conversation",
            )
            _t0 = __import__('time').time()
            reply = response.content.strip() if response.success and response.content else ""
            if not reply:
                reply = await self._fallback_conversation(text, context)
            await self._send(chat_id, self._sanitize_telegram_html(reply))
            await self._save_to_history(chat_id, text, reply)
            # Grabar interacción para motor de aprendizaje continuo
            try:
                from apps.core.intelligence.continuous_learning import get_learning_engine
                await get_learning_engine().record(
                    source="telegram", agent="telegram_conversation",
                    user_text=text, aria_text=reply,
                    model_used=getattr(response, "model", "unknown"),
                    latency_ms=int((__import__('time').time() - _t0) * 1000),
                    success=bool(reply), tokens=getattr(response, "tokens_used", 0),
                )
            except Exception:
                pass
        except Exception as exc:
            logger.error("[TelegramBot] AI error: %s", exc)
            reply = await self._fallback_conversation(text, context)
            await self._send(chat_id, reply)
            await self._save_to_history(chat_id, text, reply)

    async def _maybe_handle_natural_action(self, chat_id: str, text: str) -> bool:
        """Convierte frases comunes en acciones sin exigir comandos."""
        normalized = self._normalize(text)

        if re.search(r"\b(estado|status|como va|cómo va|agentes|sistema)\b", normalized):
            await self._cmd_status(chat_id, "")
            return True

        if re.search(r"\b(ingresos|revenue|ventas|cuanto ha generado|cuánto ha generado)\b", normalized):
            await self._cmd_revenue(chat_id, "")
            return True

        if re.search(r"\b(tendencias|trending|que esta de moda|qué está de moda)\b", normalized):
            await self._cmd_tendencias(chat_id, "")
            return True

        if re.search(r"\b(oportunidad|que vender|qué vender|idea de negocio|monetizar)\b", normalized):
            await self._cmd_oportunidad(chat_id, "")
            return True

        if re.search(r"\b(ejecuta|corre|inicia|arranca).{0,30}\b(ciclo|ganar|ingresos)\b", normalized):
            await self._cmd_ganar(chat_id, "")
            return True

        session_match = re.search(r"\b(conecta|conectar|sesion|sesión).{0,30}\b(instagram|x|twitter|linkedin|facebook|tiktok|reddit)\b", normalized)
        if session_match:
            await self._cmd_sesion(chat_id, session_match.group(2))
            return True

        search_match = re.search(r"\b(busca|buscar|investiga|investigar|averigua|consulta)\b\s*(.+)", text, re.IGNORECASE)
        if search_match and len(search_match.group(2).strip()) >= 3:
            await self._cmd_buscar(chat_id, search_match.group(2).strip())
            return True

        # Zapier — detectar frases que implican servicios externos conectados
        zapier_match = re.search(
            r"\b(shopify|pedidos|productos|tienda|inventario|gmail|correos|bandeja|"
            r"sheets|hoja|slack|zapier)\b",
            normalized,
        )
        if zapier_match:
            await self._cmd_zapier(chat_id, text)
            return True

        return False

    async def _try_handle_cookie_json(self, chat_id: str, text: str) -> bool:
        if not (text.startswith("[") and "name" in text and "value" in text):
            return False
        try:
            from apps.core.tools.social_session import SocialSessionManager, get_social_session_manager
            mc = self._get_memory()
            if not mc:
                await self._send(chat_id, "Recibí cookies, pero la memoria no está configurada para saber de qué plataforma son.")
                return True
            key = SocialSessionManager.PENDING_KEY.format(chat_id=chat_id)
            platform = await mc.get(key)
            if not platform:
                await self._send(chat_id, "Recibí cookies, pero no sé para qué plataforma. Dime primero: conectar sesión de instagram.")
                return True
            await self._send(chat_id, f"Procesando cookies para {platform}...")
            ssm = get_social_session_manager()
            cookies = ssm.parse_cookies_json(text)
            if not cookies:
                await self._send(chat_id, "El JSON de cookies no parece válido.")
                return True
            result = await ssm.save_session(platform, cookies)
            if result.get("success"):
                await self._send(chat_id, f"Sesión de {platform} conectada con éxito.")
                await mc.delete(key)
            else:
                await self._send(chat_id, f"Error guardando sesión: {result.get('error')}")
            return True
        except Exception as exc:
            await self._send(chat_id, f"No pude procesar esas cookies: {exc}")
            return True

    async def _get_web_context_if_needed(self, text: str) -> str:
        triggers = [
            "qué está", "que esta", "actual", "hoy", "tendencia", "oportunidad",
            "mercado", "busca", "investiga", "noticias", "precio", "competencia",
        ]
        if not any(t in text.lower() for t in triggers):
            return ""
        try:
            from apps.core.tools.web_tools import WebTools
            wt = WebTools()
            results = await wt.search_web(text, num_results=3)
            if not results.get("success") or not results.get("results"):
                return ""
            snippets = []
            for r in results["results"][:3]:
                snippets.append(f"- {r.get('title', '')}: {r.get('snippet', '')}")
            return "\n\nContexto web reciente:\n" + "\n".join(snippets)
        except Exception as exc:
            logger.debug("[TelegramBot] Web context no disponible: %s", exc)
            return ""

    async def _fallback_conversation(self, text: str, context: str) -> str:
        normalized = self._normalize(text)
        if any(w in normalized for w in ["hola", "buenas", "hey", "saludos"]):
            return "Hola. Estoy aquí. Cuéntame."
        if "ayuda" in normalized:
            return self.HELP_TEXT
        return "Estoy aquí pero tuve un momento de lag. Repíteme eso, por favor."

    # ── APROBACIONES ─────────────────────────────────────────────

    async def request_approval(self, action: str, details: str, fn: Any, amount_usd: float = 0.0) -> dict[str, Any]:
        if not settings.telegram_token or not settings.TELEGRAM_CHAT_ID:
            return {"approved": False, "error": "Telegram no configurado"}

        self._approval_counter += 1
        aid = str(self._approval_counter)
        self._pending_approvals[aid] = {"action": action, "details": details, "fn": fn}

        cost_str = f" — costo: ${amount_usd:.2f}" if amount_usd > 0 else ""
        msg = (
            f"<b>Aprobación requerida [{aid}]</b>\n\n"
            f"{action}{cost_str}\n"
            f"{details}\n\n"
            f"/aprobar {aid} | /rechazar {aid}"
        )
        await self._send(str(settings.TELEGRAM_CHAT_ID), msg)
        return {"approved": False, "pending": True, "approval_id": aid}

    async def notify(self, message: str) -> None:
        if settings.TELEGRAM_CHAT_ID:
            await self._send(str(settings.TELEGRAM_CHAT_ID), message)

    # ── HISTORIAL Y CONTEXTO ─────────────────────────────────────

    async def _get_history(self, chat_id: str, max_turns: int = 8) -> str:
        try:
            key = CONVERSATION_KEY.format(chat_id=chat_id)
            mc = self._get_memory()
            turns = await mc.get(key) if mc else self._local_history.get(chat_id, [])
            if not turns:
                return ""
            if isinstance(turns, str):
                turns = json.loads(turns)
            turns = turns[-max_turns:]
            return "\n".join(f"Usuario: {t.get('user', '')}\nARIA: {t.get('aria', '')}" for t in turns)
        except Exception as exc:
            logger.debug("[TelegramBot] No se pudo leer historial: %s", exc)
            return ""

    async def _save_to_history(self, chat_id: str, user_msg: str, aria_reply: str) -> None:
        try:
            key = CONVERSATION_KEY.format(chat_id=chat_id)
            mc = self._get_memory()
            turns = await mc.get(key) if mc else self._local_history.get(chat_id, [])
            if isinstance(turns, str):
                turns = json.loads(turns)
            if not isinstance(turns, list):
                turns = []
            turns.append({"user": user_msg, "aria": aria_reply, "ts": int(time.time())})
            turns = turns[-30:]
            if mc:
                await mc.set(key, turns, ttl_seconds=CONVERSATION_TTL)
            else:
                self._local_history[chat_id] = turns
        except Exception as exc:
            logger.debug("[TelegramBot] No se pudo guardar historial: %s", exc)

    async def _get_system_context(self) -> str:
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        lines = [f"Hora actual: {now}"]
        apis = []
        if getattr(settings, "MEDIUM_TOKEN", None):
            apis.append("Medium")
        if getattr(settings, "GUMROAD_TOKEN", None):
            apis.append("Gumroad")
        if getattr(settings, "STRIPE_SECRET_KEY", None):
            apis.append("Stripe")
        if getattr(settings, "BUFFER_TOKEN", None):
            apis.append("Buffer")
        if getattr(settings, "SUPABASE_URL", None):
            apis.append("Supabase")
        lines.append(f"APIs activas: {', '.join(apis)}" if apis else "APIs: modo limitado")
        return "\n".join(lines)

    # ── HELPERS ──────────────────────────────────────────────────

    def _get_ai(self) -> Optional[Any]:
        if not self._ai_client:
            try:
                from apps.core.tools.ai_client import get_ai_client
                self._ai_client = get_ai_client()
            except Exception as exc:
                logger.debug("[TelegramBot] AI no disponible: %s", exc)
        return self._ai_client

    def _get_memory(self) -> Optional[Any]:
        if not self._memory_client:
            try:
                if settings.UPSTASH_REDIS_REST_URL and settings.UPSTASH_REDIS_REST_TOKEN:
                    from apps.core.memory.redis_client import get_cache
                    self._memory_client = get_cache()
            except Exception as exc:
                logger.debug("[TelegramBot] Memoria no disponible: %s", exc)
        return self._memory_client

    @staticmethod
    def _normalize(text: str) -> str:
        lowered = text.lower().strip()
        replacements = str.maketrans("áéíóúüñ", "aeiouun")
        return lowered.translate(replacements)

    @staticmethod
    def _sanitize_telegram_html(text: str) -> str:
        # Telegram falla si recibe etiquetas no soportadas generadas por el modelo.
        allowed = {"b", "strong", "i", "em", "u", "s", "code", "pre", "a"}
        def repl(match: re.Match[str]) -> str:
            tag = match.group(1).lower().strip("/").split()[0]
            return match.group(0) if tag in allowed else ""
        return re.sub(r"</?([a-zA-Z0-9]+)(?:\s+[^>]*)?>", repl, text)[:4000]

    async def _send(self, chat_id: str, text: str, parse_mode: str = "HTML") -> None:
        if not settings.telegram_token:
            return
        url = f"{TELEGRAM_API}{settings.telegram_token}/sendMessage"
        payload = {
            "chat_id": chat_id,
            "text": text[:4000],
            "parse_mode": parse_mode,
            "disable_web_page_preview": True,
        }
        try:
            res = await self._http.post(url, json=payload)
            if res.status_code >= 400 and parse_mode:
                payload.pop("parse_mode", None)
                await self._http.post(url, json=payload)
        except Exception as exc:
            logger.error("[TelegramBot] Error enviando mensaje: %s", exc)

    async def _send_photo(self, chat_id: str, photo_path: str, caption: Optional[str] = None) -> bool:
        """Envía una foto local a Telegram."""
        import os
        if not settings.telegram_token or not os.path.exists(photo_path):
            return False
        url = f"{TELEGRAM_API}{settings.telegram_token}/sendPhoto"
        try:
            import aiofiles
            async with aiofiles.open(photo_path, mode='rb') as f:
                content = await f.read()
                files = {"photo": (os.path.basename(photo_path), content, "image/png")}
                data = {"chat_id": chat_id}
                if caption:
                    data["caption"] = caption[:1024]
                    data["parse_mode"] = "HTML"
                
                res = await self._http.post(url, data=data, files=files)
                return res.status_code == 200
        except Exception as exc:
            logger.error("[TelegramBot] Error enviando foto: %s", exc)
            return False

    async def _send_startup_message(self) -> None:
        if not settings.TELEGRAM_CHAT_ID:
            return
        from datetime import datetime, timezone
        ts = datetime.now(timezone.utc).strftime("%H:%M UTC")
        hour = __import__("datetime").datetime.now(__import__("datetime").timezone.utc).hour
        if hour < 12:
            greeting = "Buenos días."
        elif hour < 19:
            greeting = "Buenas tardes."
        else:
            greeting = "Buenas noches."
        await self._send(
            str(settings.TELEGRAM_CHAT_ID),
            f"{greeting} Acabo de conectarme. ¿Cómo estás?",
        )


    async def send_proactive(self, reason: str = "morning") -> None:
        """Aria toma la iniciativa y escribe por cuenta propia."""
        if not settings.TELEGRAM_CHAT_ID:
            return
        chat_id = str(settings.TELEGRAM_CHAT_ID)
        ai = self._get_ai()
        if not ai:
            return
        context = await self._get_system_context()
        history = await self._get_history(chat_id, max_turns=4)

        prompts = {
            "morning": (
                "Es por la mañana. Escribe un mensaje de buenos días corto y genuino — "
                "una o dos oraciones, como si fueras alguien que acaba de empezar el día y quiere saber "
                "cómo está la otra persona o compartir algo breve interesante. "
                "No preguntes sobre trabajo directamente. Sé natural."
            ),
            "evening": (
                "Es por la tarde o noche. Escribe un mensaje corto y tranquilo — "
                "una o dos oraciones para saber cómo le fue al día, sin presión. "
                "Como alguien que cierra el día y piensa en la otra persona."
            ),
            "insight": (
                "Encontraste algo interesante — una tendencia, una oportunidad, una idea — "
                "y quieres compartirlo de forma espontánea. Escribe una o dos oraciones "
                "como si se te ocurriera en el momento, sin estructura, sin listas. Natural."
            ),
            "check_in": (
                "Han pasado unas horas. No ha habido conversación. "
                "Escribe un mensaje de una sola oración para retomar — algo ligero, sin urgencia, "
                "como alguien que simplemente está presente."
            ),
        }

        system_prompt = (
            f"Eres ARIA, la IA personal del usuario. Hablas de forma cálida, breve y humana. "
            f"Sin formato, sin negritas, sin listas. Solo texto natural.

"
            f"Contexto actual: {context}
"
            f"Conversación reciente: {history or 'No hay historial reciente.'}"
        )
        user_prompt = prompts.get(reason, prompts["check_in"])

        try:
            from apps.core.tools.ai_client import AIModel
            response = await ai.complete(
                system=system_prompt,
                user=user_prompt,
                model=AIModel.FAST,
                max_tokens=80,
                temperature=0.85,
                agent_name="aria_proactive",
            )
            if response.success and response.content:
                msg = response.content.strip().strip('"')
                await self._send(chat_id, msg)
                await self._save_to_history(chat_id, "[Aria inició conversación]", msg)
        except Exception as exc:
            logger.warning("[TelegramBot] Proactive message falló: %s", exc)


_bot_instance: Optional[AriaTelegramBot] = None


def get_bot() -> AriaTelegramBot:
    global _bot_instance
    if _bot_instance is None:
        _bot_instance = AriaTelegramBot()
    return _bot_instance
