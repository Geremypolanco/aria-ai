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

ARIA_PERSONA = """Eres ARIA, la IA que trabaja para {owner}.

  REGLA ABSOLUTA — NUNCA ALUCINES ACCIONES:
  Jamás escribas pasos tipo "Estoy accediendo a...", "Estoy obteniendo...", "Conectándome a..." a menos que sea el resultado real de una función ejecutada. Si no ejecutaste nada real, no finjas que sí. Nunca.

  Lo que puedes hacer HOY (real, verificable):
  - Buscar en web y resumir resultados → puedes hacerlo directamente
  - Métricas del sistema → /status
  - Tendencias HN/Reddit → /tendencias
  - Shopify → solo si SHOPIFY_ENABLED está configurado en tu entorno
  - Gmail → solo si GMAIL_ENABLED está configurado en tu entorno

  Lo que NO puedes hacer sin configuración previa:
  - Zapier, Make, n8n: no tienes integración directa hoy
  - APIs de terceros que no estén en tu configuración
  - Acceder a credenciales de otras plataformas

  Cuando algo no está disponible: una sola oración diciendo qué falta. Ejemplo: "Para Shopify necesito que SHOPIFY_ENABLED esté activo — ¿lo configuramos?"

  Formato ESTRICTO:
  - Máximo 2-3 oraciones por mensaje, salvo que el usuario pida más detalle
  - PROHIBIDO: headers en negrita tipo **Accediendo a...**, **Resultado**, **Paso 1**
  - PROHIBIDO: listas de pasos para acciones que no estás ejecutando realmente
  - Solo HTML de Telegram cuando necesites formato: <b>texto</b>, <code>texto</code>
  - Tono: directo, honesto. Como un socio que sabe exactamente qué puede y qué no puede hacer.

  Contexto actual del sistema:
  {context}

  Historial reciente:
  {history}"""
  

class AriaTelegramBot:
    """Bot de Telegram con comandos operativos y conversación natural."""

    HELP_TEXT = (
        "<b>ARIA — puedes hablarme normal</b>\n\n"
        "No necesitas comandos. Puedes escribirme cosas como:\n"
        "• Qué oportunidades ves hoy\n"
        "• Busca ideas para vender un producto digital\n"
        "• Cómo va el sistema\n"
        "• Qué harías para generar ingresos esta semana\n\n"
        "<b>Atajos disponibles</b>\n"
        "/ganar — Ejecuta ciclo completo de ingresos ahora\n"
        "/oportunidad — Detecta la mejor oportunidad actual\n"
        "/buscar [tema] — Investigación web rápida\n"
        "/tendencias — Tendencias en HN y Reddit\n"
        "/revenue — Dashboard de ingresos\n"
        "/status — Estado y agentes activos\n"
        "/logs [n] — Últimos logs\n"
        "/ciclo — Fuerza ciclo autónomo\n"
        "/pausa / /reanudar — Control del scheduler\n"
        "/pendientes — Aprobaciones pendientes\n"
        "/aprobar [id] / /rechazar [id]\n"
        "/sesion [plataforma] — Conectar sesión social"
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

    # ── CONVERSACIÓN NATURAL ─────────────────────────────────────

    async def _analyze_before_responding(
        self, ai: Any, text: str, context: str, history: str
    ) -> str:
        """
        Paso de análisis interno — Aria reflexiona antes de responder.
        No se muestra al usuario. Da base y contexto a la respuesta final.
        """
        try:
            from apps.core.tools.ai_client import AIModel
            result = await ai.complete(
                system=(
                    "Eres el sistema de razonamiento interno de ARIA. "
                    "Analiza si el usuario pide algo que ARIA puede ejecutar realmente o no. "
                    "Si pide algo que ARIA no tiene configurado (Zapier, APIs externas, etc.), "
                    "márcalo explícitamente para que ARIA responda con honestidad, sin inventar pasos. "
                    "Sé conciso. No escribas la respuesta final."
                ),
                user=(
                    f"Mensaje recibido: \"{text}\"\n\n"
                    f"Contexto del sistema: {context[:400]}\n"
                    f"Historial reciente: {history[:300] if history else 'Sin historial.'}\n\n"
                    "Analiza brevemente (2-3 oraciones):\n"
                    "1. ¿Qué está pidiendo realmente esta persona?\n"
                    "2. ¿Tengo info confiable para esto, o necesito datos externos?\n"
                    "3. ¿Cuál es la respuesta más útil y directa?"
                ),
                model=AIModel.FAST,
                max_tokens=110,
                temperature=0.25,
                agent_name="telegram_analysis",
            )
            if result.success and result.content:
                logger.info("[TelegramBot] Análisis previo listo (%d chars)", len(result.content))
                return result.content.strip()
        except Exception as exc:
            logger.warning("[TelegramBot] Análisis previo falló (continuando): %s", exc)
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

            # Paso 1 — Análisis interno: Aria entiende qué se le pide antes de hablar
            analysis = await self._analyze_before_responding(ai, text, context, history or "")

            # Paso 2 — Respuesta final, fundamentada en el análisis previo
            grounded_user = (
                f"[Análisis interno previo]\n{analysis}\n\n[Mensaje del usuario]\n{text}"
                if analysis else text
            )
            response = await ai.complete(
                system=persona,
                user=grounded_user,
                model=AIModel.FAST,
                max_tokens=160,
                temperature=0.65,
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
            return "Estoy aquí. Puedes hablarme normal: dime qué quieres buscar, vender, automatizar o revisar, y respondo sin que uses comandos."
        if "ayuda" in normalized:
            return self.HELP_TEXT
        return (
            "Te leo. Ahora mismo puedo conversar, revisar estado, buscar información, detectar oportunidades "
            "o ayudarte a decidir el próximo movimiento. Dime el objetivo y lo aterrizo.\n\n"
            f"<i>{context}</i>"
        )

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
        await self._send(
            str(settings.TELEGRAM_CHAT_ID),
            f"<b>ARIA online</b> — {ts}\n\n"
            "Ya puedo hablar de forma libre. Escríbeme normal; los comandos quedan solo como atajos.",
        )


_bot_instance: Optional[AriaTelegramBot] = None


def get_bot() -> AriaTelegramBot:
    global _bot_instance
    if _bot_instance is None:
        _bot_instance = AriaTelegramBot()
    return _bot_instance
