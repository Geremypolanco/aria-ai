"""
AriaTelegramBot — Bot bidireccional completo.

Recibe mensajes/comandos del supervisor via webhook y ejecuta acciones en tiempo real.
Responde con IA de forma fluida si el mensaje no es un comando.
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
CONVERSATION_KEY = "aria:conversation:history"
CONVERSATION_TTL = 86400  # 24h


class AriaTelegramBot:
    """Bot de Telegram bidireccional con comandos + IA conversacional."""

    HELP_TEXT = (
        "🤖 <b>ARIA AI — Comandos disponibles</b>\n\n"
        "<b>📊 SISTEMA</b>\n"
        "/status — Estado completo del sistema\n"
        "/agentes — Estado de cada agente\n"
        "/logs [n] — Últimos N logs (default 10)\n\n"
        "<b>💰 FINANZAS</b>\n"
        "/revenue — Dashboard de ingresos\n\n"
        "<b>⚙️ CONTROL</b>\n"
        "/ciclo — Dispara un ciclo autónomo ahora\n"
        "/pausa — Pausa el scheduler\n"
        "/reanudar — Reanuda el scheduler\n"
        "/evolve — Dispara auto-evolución\n\n"
        "<b>✅ APROBACIONES</b>\n"
        "/pendientes — Lista aprobaciones en espera\n"
        "/aprobar &lt;id&gt; — Aprueba una acción\n"
        "/rechazar &lt;id&gt; — Rechaza una acción\n\n"
        "<b>🚀 AGENTES</b>\n"
        "/pm &lt;tarea&gt; — Ejecuta PMAgent\n"
        "/cfo &lt;tarea&gt; — Ejecuta CFOAgent\n"
        "/dev &lt;tarea&gt; — Ejecuta DevAgent\n"
        "/marketing &lt;tarea&gt; — Ejecuta MarketingAgent\n"
        "/soporte &lt;consulta&gt; — Ejecuta SupportAgent\n\n"
        "<b>💬 CONVERSACIÓN</b>\n"
        "Escribe cualquier cosa — ARIA responderá con IA\n"
        "/ia &lt;pregunta&gt; — Pregunta directa a la IA\n"
        "/limpiar — Borra el historial de conversación\n\n"
        "/ayuda — Muestra este menú"
    )

    def __init__(self) -> None:
        self._token = settings.TELEGRAM_TOKEN
        self._owner_id = settings.TELEGRAM_CHAT_ID
        self._base_url = f"{TELEGRAM_API}{self._token}"
        self._http = httpx.AsyncClient(timeout=15.0)

    # ── ENTRY POINT ───────────────────────────────────────

    async def handle_update(self, update: dict[str, Any]) -> None:
        """Punto de entrada para todos los updates de Telegram."""
        try:
            message = update.get("message") or update.get("edited_message")
            callback = update.get("callback_query")

            if message:
                await self._handle_message(message)
            elif callback:
                await self._handle_callback(callback)
        except Exception as exc:
            logger.error("[TelegramBot] Error procesando update: %s", exc)

    async def _handle_message(self, message: dict[str, Any]) -> None:
        chat_id = str(message.get("chat", {}).get("id", ""))
        text = message.get("text", "").strip()
        from_id = str(message.get("from", {}).get("id", ""))

        if not text or not chat_id:
            return

        # Seguridad: solo responder al propietario
        if from_id != self._owner_id and chat_id != self._owner_id:
            await self.send(chat_id, "⛔ No autorizado.")
            logger.warning("[TelegramBot] Mensaje de usuario no autorizado: %s", from_id)
            return

        logger.info("[TelegramBot] Mensaje de %s: %s", chat_id, text[:80])

        if text.startswith("/"):
            await self._parse_command(text, chat_id)
        else:
            await self._handle_natural_language(text, chat_id)

    async def _handle_callback(self, callback: dict[str, Any]) -> None:
        """Maneja botones inline de Telegram."""
        chat_id = str(callback.get("message", {}).get("chat", {}).get("id", ""))
        data = callback.get("data", "")
        callback_id = callback.get("id", "")

        # Ack the callback
        await self._http.post(
            f"{self._base_url}/answerCallbackQuery",
            json={"callback_query_id": callback_id},
        )

        if data.startswith("aprobar:"):
            approval_id = data.split(":", 1)[1]
            await self._do_approval(chat_id, approval_id, "approved")
        elif data.startswith("rechazar:"):
            approval_id = data.split(":", 1)[1]
            await self._do_approval(chat_id, approval_id, "rejected")

    # ── PARSER DE COMANDOS ────────────────────────────────

    async def _parse_command(self, text: str, chat_id: str) -> None:
        parts = text.split(maxsplit=1)
        cmd = parts[0].lower().split("@")[0]  # elimina @botname si existe
        args = parts[1] if len(parts) > 1 else ""

        handlers = {
            "/start": lambda: self.cmd_start(chat_id),
            "/ayuda": lambda: self.cmd_ayuda(chat_id),
            "/help": lambda: self.cmd_ayuda(chat_id),
            "/status": lambda: self.cmd_status(chat_id),
            "/revenue": lambda: self.cmd_revenue(chat_id),
            "/ingresos": lambda: self.cmd_revenue(chat_id),
            "/ciclo": lambda: self.cmd_ciclo(chat_id),
            "/pausa": lambda: self.cmd_pausa(chat_id),
            "/reanudar": lambda: self.cmd_reanudar(chat_id),
            "/agentes": lambda: self.cmd_agentes(chat_id),
            "/pendientes": lambda: self.cmd_pendientes(chat_id),
            "/evolve": lambda: self.cmd_evolve(chat_id),
            "/limpiar": lambda: self.cmd_limpiar(chat_id),
            "/logs": lambda: self.cmd_logs(chat_id, args),
            "/ia": lambda: self.cmd_ia(chat_id, args),
            "/aprobar": lambda: self.cmd_aprobar(chat_id, args),
            "/rechazar": lambda: self.cmd_rechazar(chat_id, args),
            "/pm": lambda: self.cmd_agent_run(chat_id, "pm", args or "analyze best opportunities now"),
            "/cfo": lambda: self.cmd_agent_run(chat_id, "cfo", args or "create a digital product and publish it"),
            "/dev": lambda: self.cmd_agent_run(chat_id, "dev", args or "build a monetized landing page"),
            "/marketing": lambda: self.cmd_agent_run(chat_id, "marketing", args or "create a content pack for digital products"),
            "/soporte": lambda: self.cmd_agent_run(chat_id, "support", args or "check pending customer inquiries"),
        }

        handler = handlers.get(cmd)
        if handler:
            await handler()
        else:
            await self.send(chat_id, f"❓ Comando desconocido: <code>{cmd}</code>\nUsa /ayuda para ver todos los comandos.")

    # ── LENGUAJE NATURAL ──────────────────────────────────

    async def _handle_natural_language(self, text: str, chat_id: str) -> None:
        """Procesa mensaje libre con IA. ARIA responde de forma fluida."""
        await self._send_typing(chat_id)

        history = await self._get_conversation_history()
        history.append({"role": "user", "content": text})

        try:
            from apps.core.tools.ai_client import AIModel, get_ai_client
            ai = await get_ai_client()
            response = await ai.complete(
                system=(
                    f"Eres ARIA, un sistema de IA autónomo que genera ingresos para {settings.OWNER_NAME}. "
                    "Eres directa, eficiente y proactiva. Hablas en primera persona. "
                    "Puedes consultar tu estado interno, ejecutar agentes y reportar resultados. "
                    "Si el usuario pide ejecutar algo (un agente, un ciclo, ver datos), "
                    "descríbelo y dile que use el comando correspondiente o que tú lo ejecutarás. "
                    "Respuestas cortas y útiles. Máximo 300 palabras. Sin markdown, usa HTML de Telegram."
                ),
                user=self._format_history_for_prompt(history),
                model=AIModel.FAST,
            )

            reply = response.content if response and response.success else "No pude procesar tu mensaje ahora. Intenta de nuevo."

            history.append({"role": "assistant", "content": reply})
            await self._save_conversation_history(history[-20:])  # máximo 20 mensajes

            # Detectar intención de ejecutar acción
            intent = await self._detect_action_intent(text)
            if intent:
                reply += f"\n\n{intent}"

            await self.send(chat_id, reply)

        except Exception as exc:
            logger.error("[TelegramBot] Error en NL: %s", exc)
            await self.send(chat_id, "❌ Error procesando tu mensaje. Usa /ayuda para ver los comandos disponibles.")

    async def _detect_action_intent(self, text: str) -> Optional[str]:
        """Detecta si el usuario quiere ejecutar una acción y sugiere el comando."""
        text_lower = text.lower()
        suggestions = []

        keywords = {
            ("estado", "status", "cómo vas", "qué está pasando"): "💡 <code>/status</code> para ver el estado completo",
            ("ingresos", "dinero", "revenue", "cuánto has ganado"): "💡 <code>/revenue</code> para ver los ingresos",
            ("ciclo", "trabajar", "ejecutar", "analizar", "oportunidad"): "💡 <code>/ciclo</code> para disparar un ciclo ahora",
            ("pausa", "detener", "para"): "💡 <code>/pausa</code> para pausar el scheduler",
            ("pendientes", "aprobar", "aprobaciones"): "💡 <code>/pendientes</code> para ver las aprobaciones",
            ("logs", "errores", "qué pasó"): "💡 <code>/logs</code> para ver los últimos eventos",
        }

        for kw_group, suggestion in keywords.items():
            if any(kw in text_lower for kw in kw_group):
                suggestions.append(suggestion)

        return "\n".join(suggestions[:2]) if suggestions else None

    def _format_history_for_prompt(self, history: list[dict]) -> str:
        lines = []
        for msg in history[-10:]:
            role = "Supervisor" if msg["role"] == "user" else "ARIA"
            lines.append(f"{role}: {msg['content']}")
        return "\n".join(lines)

    # ── COMANDOS ──────────────────────────────────────────

    async def cmd_start(self, chat_id: str) -> None:
        await self.send(
            chat_id,
            f"🤖 <b>ARIA AI — Online</b>\n\n"
            f"Bienvenido, {settings.OWNER_NAME}. Sistema operativo activo.\n\n"
            f"Soy tu sistema de ingresos autónomo. Trabajo 24/7 detectando oportunidades, "
            f"creando productos y generando revenue.\n\n"
            f"Usa /ayuda para ver todo lo que puedo hacer.",
        )

    async def cmd_ayuda(self, chat_id: str) -> None:
        await self.send(chat_id, self.HELP_TEXT)

    async def cmd_status(self, chat_id: str) -> None:
        await self._send_typing(chat_id)
        try:
            from apps.core.memory.supabase_client import get_db
            from apps.core.memory.redis_client import get_cache
            db = get_db()
            cache = get_cache()

            total_revenue = await db.get_total_revenue()
            total_by_platform = await db.get_revenue_by_platform()
            platform_lines = "\n".join([f"  • {k}: ${v:.2f}" for k, v in total_by_platform.items()]) or "  Sin ingresos aún"

            # Verificar agentes vivos
            agent_names = ["orchestrator", "pm_agent", "cfo_agent", "dev_agent", "marketing_agent", "support_agent"]
            agent_lines = []
            for name in agent_names:
                alive = await cache.is_agent_alive(name)
                status = await cache.get_agent_status(name)
                state = status.get("state", "unknown") if status else "unknown"
                icon = "🟢" if alive else "⚫"
                agent_lines.append(f"  {icon} {name}: {state}")

            msg = (
                f"📊 <b>ARIA OS — Estado del Sistema</b>\n\n"
                f"💰 <b>Revenue total:</b> ${total_revenue:.2f} USD\n"
                f"<b>Por plataforma:</b>\n{platform_lines}\n\n"
                f"<b>Agentes:</b>\n" + "\n".join(agent_lines) + "\n\n"
                f"🕐 {_now_str()}"
            )
            await self.send(chat_id, msg)
        except Exception as exc:
            await self.send(chat_id, f"❌ Error obteniendo estado: {exc}")

    async def cmd_revenue(self, chat_id: str) -> None:
        await self._send_typing(chat_id)
        try:
            from apps.core.memory.supabase_client import get_db
            db = get_db()
            total = await db.get_total_revenue()
            by_platform = await db.get_revenue_by_platform()
            recent = db._client.table("revenue").select("*").order("created_at", desc=True).limit(5).execute()

            platform_lines = "\n".join([f"  • {k}: ${v:.2f}" for k, v in by_platform.items()]) or "  Sin ingresos registrados"
            recent_lines = "\n".join([
                f"  • ${r.get('amount', 0):.2f} — {r.get('product_name', 'N/A')} ({r.get('platform', '?')})"
                for r in (recent.data or [])
            ]) or "  Sin transacciones recientes"

            msg = (
                f"💰 <b>ARIA — Dashboard de Ingresos</b>\n\n"
                f"<b>Total generado:</b> ${total:.2f} USD\n\n"
                f"<b>Por plataforma:</b>\n{platform_lines}\n\n"
                f"<b>Últimas 5 transacciones:</b>\n{recent_lines}\n\n"
                f"🕐 {_now_str()}"
            )
            await self.send(chat_id, msg)
        except Exception as exc:
            await self.send(chat_id, f"❌ Error: {exc}")

    async def cmd_ciclo(self, chat_id: str) -> None:
        await self.send(chat_id, "🚀 <b>Disparando ciclo autónomo...</b>\nTe notificaré cuando termine.")
        try:
            from apps.core.memory.redis_client import get_cache
            cache = get_cache()
            locked = await cache.acquire_lock("autonomous_cycle", ttl_seconds=300)
            if not locked:
                await self.send(chat_id, "⚠️ Ya hay un ciclo en ejecución. Espera a que termine.")
                return
            asyncio.create_task(self._run_cycle_task(chat_id, cache))
        except Exception as exc:
            await self.send(chat_id, f"❌ Error iniciando ciclo: {exc}")

    async def _run_cycle_task(self, chat_id: str, cache: Any) -> None:
        try:
            from apps.core.agents.orchestrator import Orchestrator
            orch = Orchestrator()
            await orch.start()
            await orch.run_cycle()
            await self.send(chat_id, "✅ <b>Ciclo completado.</b> Revisa /status para ver los resultados.")
        except Exception as exc:
            await self.send(chat_id, f"❌ Error en ciclo: {exc}")
        finally:
            await cache.release_lock("autonomous_cycle")

    async def cmd_pausa(self, chat_id: str) -> None:
        try:
            from apps.core.main import scheduler
            scheduler.pause()
            await self.send(chat_id, "⏸ <b>Scheduler PAUSADO.</b> ARIA ya no ejecutará ciclos automáticos.\nUsa /reanudar para volver a activarla.")
        except Exception as exc:
            await self.send(chat_id, f"❌ Error: {exc}")

    async def cmd_reanudar(self, chat_id: str) -> None:
        try:
            from apps.core.main import scheduler
            scheduler.resume()
            await self.send(chat_id, "▶️ <b>Scheduler REANUDADO.</b> ARIA vuelve a operar de forma autónoma.")
        except Exception as exc:
            await self.send(chat_id, f"❌ Error: {exc}")

    async def cmd_agentes(self, chat_id: str) -> None:
        await self._send_typing(chat_id)
        try:
            from apps.core.memory.redis_client import get_cache
            cache = get_cache()
            agent_names = ["orchestrator", "pm_agent", "cfo_agent", "dev_agent", "marketing_agent", "support_agent"]
            lines = []
            for name in agent_names:
                alive = await cache.is_agent_alive(name)
                status = await cache.get_agent_status(name)
                state = "unknown"
                success_rate = "N/A"
                if status:
                    state = status.get("state", "unknown")
                    sr = status.get("metrics", {}).get("success_rate", None)
                    if sr is not None:
                        success_rate = f"{sr:.0f}%"
                icon = "🟢" if alive else "⚫"
                lines.append(f"{icon} <b>{name}</b>\n   Estado: {state} | Éxito: {success_rate}")

            await self.send(chat_id, "🤖 <b>Estado de Agentes</b>\n\n" + "\n\n".join(lines))
        except Exception as exc:
            await self.send(chat_id, f"❌ Error: {exc}")

    async def cmd_pendientes(self, chat_id: str) -> None:
        await self._send_typing(chat_id)
        try:
            from apps.core.memory.supabase_client import get_db
            db = get_db()
            approvals = await db.get_pending_approvals()
            if not approvals:
                await self.send(chat_id, "✅ <b>Sin aprobaciones pendientes.</b>")
                return

            lines = []
            for a in approvals[:10]:
                approval_id = a.get("id", "?")[:8]
                action = a.get("action", "?")
                amount = a.get("details", {}).get("amount_usd", 0)
                lines.append(
                    f"🔔 <code>{approval_id}</code> — {action}\n"
                    f"   💵 ${amount:.2f} | /aprobar {approval_id} | /rechazar {approval_id}"
                )

            await self.send(
                chat_id,
                f"⏳ <b>{len(approvals)} aprobaciones pendientes:</b>\n\n" + "\n\n".join(lines),
            )
        except Exception as exc:
            await self.send(chat_id, f"❌ Error: {exc}")

    async def cmd_aprobar(self, chat_id: str, approval_id: str) -> None:
        if not approval_id.strip():
            await self.send(chat_id, "⚠️ Usa: /aprobar &lt;id&gt;")
            return
        await self._do_approval(chat_id, approval_id.strip(), "approved")

    async def cmd_rechazar(self, chat_id: str, approval_id: str) -> None:
        if not approval_id.strip():
            await self.send(chat_id, "⚠️ Usa: /rechazar &lt;id&gt;")
            return
        await self._do_approval(chat_id, approval_id.strip(), "rejected")

    async def _do_approval(self, chat_id: str, approval_id: str, decision: str) -> None:
        try:
            from apps.core.memory.supabase_client import get_db
            db = get_db()
            success = await db.resolve_approval(approval_id, decision, f"Decisión de {settings.OWNER_NAME} via Telegram")
            emoji = "✅" if decision == "approved" else "❌"
            verb = "APROBADA" if decision == "approved" else "RECHAZADA"
            if success:
                await self.send(chat_id, f"{emoji} Aprobación <code>{approval_id}</code> — <b>{verb}</b>")
            else:
                await self.send(chat_id, f"⚠️ No se encontró la aprobación <code>{approval_id}</code>")
        except Exception as exc:
            await self.send(chat_id, f"❌ Error procesando aprobación: {exc}")

    async def cmd_logs(self, chat_id: str, args: str) -> None:
        await self._send_typing(chat_id)
        try:
            limit = int(args.strip()) if args.strip().isdigit() else 10
            limit = min(limit, 25)
            from apps.core.memory.supabase_client import get_db
            db = get_db()
            result = db._client.table("system_logs").select("*").order("created_at", desc=True).limit(limit).execute()
            logs = result.data or []
            if not logs:
                await self.send(chat_id, "📋 Sin logs registrados aún.")
                return

            lines = []
            for log in logs:
                level = log.get("level", "?")
                agent = log.get("agent", "?")
                msg = log.get("message", "")[:100]
                icon = {"ERROR": "❌", "INFO": "ℹ️", "SUCCESS": "✅", "REVENUE": "💰"}.get(level, "📌")
                lines.append(f"{icon} <b>[{agent}]</b> {msg}")

            await self.send(chat_id, f"📋 <b>Últimos {len(logs)} logs:</b>\n\n" + "\n".join(lines))
        except Exception as exc:
            await self.send(chat_id, f"❌ Error: {exc}")

    async def cmd_evolve(self, chat_id: str) -> None:
        await self.send(chat_id, "🧬 <b>Iniciando auto-evolución...</b>")
        try:
            asyncio.create_task(self._run_evolve_task(chat_id))
        except Exception as exc:
            await self.send(chat_id, f"❌ Error: {exc}")

    async def _run_evolve_task(self, chat_id: str) -> None:
        try:
            from apps.core.agents.orchestrator import Orchestrator
            orch = Orchestrator()
            await orch.start()
            await orch.auto_evolve()
            await self.send(chat_id, "✅ <b>Auto-evolución completada.</b>")
        except Exception as exc:
            await self.send(chat_id, f"❌ Error en evolución: {exc}")

    async def cmd_agent_run(self, chat_id: str, agent_key: str, task: str) -> None:
        if not task.strip():
            await self.send(chat_id, f"⚠️ Especifica una tarea: /{agent_key} &lt;descripción&gt;")
            return
        await self.send(chat_id, f"⚡ <b>Ejecutando {agent_key.upper()}Agent...</b>\nTarea: <i>{task[:100]}</i>")
        asyncio.create_task(self._run_agent_task(chat_id, agent_key, task))

    async def _run_agent_task(self, chat_id: str, agent_key: str, task: str) -> None:
        try:
            agent_map = {
                "pm": ("apps.core.agents.pm_agent", "PMAgent"),
                "cfo": ("apps.core.agents.cfo_agent", "CFOAgent"),
                "dev": ("apps.core.agents.dev_agent", "DevAgent"),
                "marketing": ("apps.core.agents.marketing_agent", "MarketingAgent"),
                "support": ("apps.core.agents.support_agent", "SupportAgent"),
            }
            if agent_key not in agent_map:
                await self.send(chat_id, f"❌ Agente desconocido: {agent_key}")
                return

            module_path, class_name = agent_map[agent_key]
            import importlib
            module = importlib.import_module(module_path)
            AgentClass = getattr(module, class_name)
            agent = AgentClass()
            await agent.start()

            result = await agent.run({"task": task, "market_focus": task, "primary_language": "es"})

            if result.get("success"):
                summary = json.dumps(result, ensure_ascii=False, indent=2)[:600]
                await self.send(chat_id, f"✅ <b>{agent_key.upper()}Agent completado:</b>\n<pre>{summary}</pre>")
            else:
                error = result.get("error", "Error desconocido")
                await self.send(chat_id, f"⚠️ <b>{agent_key.upper()}Agent terminó con error:</b>\n{error[:300]}")

            await agent.stop()
        except Exception as exc:
            logger.error("[TelegramBot] Error ejecutando %s: %s", agent_key, exc)
            await self.send(chat_id, f"❌ Error ejecutando {agent_key}: {str(exc)[:200]}")

    async def cmd_ia(self, chat_id: str, question: str) -> None:
        if not question.strip():
            await self.send(chat_id, "⚠️ Usa: /ia &lt;tu pregunta&gt;")
            return
        await self._handle_natural_language(question, chat_id)

    async def cmd_limpiar(self, chat_id: str) -> None:
        await self._save_conversation_history([])
        await self.send(chat_id, "🧹 <b>Historial de conversación borrado.</b>")

    # ── ENVÍO DE MENSAJES ─────────────────────────────────

    async def send(self, chat_id: str, text: str, reply_markup: Optional[dict] = None) -> bool:
        """Envía un mensaje Telegram con HTML parse mode."""
        payload: dict[str, Any] = {
            "chat_id": chat_id,
            "text": text[:4096],
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        }
        if reply_markup:
            payload["reply_markup"] = reply_markup
        try:
            res = await self._http.post(f"{self._base_url}/sendMessage", json=payload)
            if res.status_code != 200:
                logger.warning("[TelegramBot] sendMessage HTTP %d: %s", res.status_code, res.text[:200])
            return res.status_code == 200
        except Exception as exc:
            logger.error("[TelegramBot] Error enviando mensaje: %s", exc)
            return False

    async def _send_typing(self, chat_id: str) -> None:
        """Muestra "escribiendo..." mientras ARIA procesa."""
        try:
            await self._http.post(
                f"{self._base_url}/sendChatAction",
                json={"chat_id": chat_id, "action": "typing"},
            )
        except Exception:
            pass

    # ── WEBHOOK ───────────────────────────────────────────

    async def set_webhook(self, webhook_url: str) -> bool:
        """Registra el webhook con Telegram API."""
        try:
            res = await self._http.post(
                f"{self._base_url}/setWebhook",
                json={
                    "url": webhook_url,
                    "allowed_updates": ["message", "edited_message", "callback_query"],
                    "drop_pending_updates": True,
                },
            )
            data = res.json()
            if data.get("ok"):
                logger.info("[TelegramBot] Webhook registrado: %s", webhook_url)
                return True
            else:
                logger.error("[TelegramBot] Error registrando webhook: %s", data)
                return False
        except Exception as exc:
            logger.error("[TelegramBot] Error en set_webhook: %s", exc)
            return False

    async def get_webhook_info(self) -> dict:
        """Verifica el estado del webhook actual."""
        try:
            res = await self._http.get(f"{self._base_url}/getWebhookInfo")
            return res.json().get("result", {})
        except Exception:
            return {}

    # ── CONVERSACIÓN EN MEMORIA ───────────────────────────

    async def _get_conversation_history(self) -> list[dict]:
        try:
            from apps.core.memory.redis_client import get_cache
            cache = get_cache()
            data = await cache.get(CONVERSATION_KEY)
            if isinstance(data, list):
                return data
        except Exception:
            pass
        return []

    async def _save_conversation_history(self, history: list[dict]) -> None:
        try:
            from apps.core.memory.redis_client import get_cache
            cache = get_cache()
            await cache.set(CONVERSATION_KEY, history, ttl_seconds=CONVERSATION_TTL)
        except Exception:
            pass

    async def close(self) -> None:
        await self._http.aclose()


# ── SINGLETON ─────────────────────────────────────────────
_bot_instance: Optional[AriaTelegramBot] = None


def get_bot() -> AriaTelegramBot:
    global _bot_instance
    if _bot_instance is None:
        _bot_instance = AriaTelegramBot()
    return _bot_instance


# ── HELPERS ───────────────────────────────────────────────

def _now_str() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
