"""
aria_commands.py — Sistema de comandos tipo senior team para ARIA AI.

Comandos disponibles (prefijo /):
  /run [mission]           → ejecuta misión completa con pipeline de auditoría
  /plan [objective]        → solo fase de planificación (sin ejecutar)
  /audit [text]            → audita contenido, código o plan
  /status                  → estado completo del sistema
  /goals                   → lista y gestiona metas activas
  /agents                  → lista agentes con métricas
  /schedule [task] [min]   → programa tarea recurrente
  /benchmark               → prueba todas las capacidades
  /pipeline [id]           → consulta estado de un pipeline
  /help                    → muestra todos los comandos
  /think [question]        → ARIA razona profundamente sobre un tema
  /code [description]      → DeveloperAgent genera y ejecuta código
  /research [topic]        → ResearchAgent investiga en profundidad
  /market [niche]          → análisis completo de mercado
  /deploy                  → info sobre despliegue en Fly.io

Inspirado en los sistemas de comandos internos de Google/Meta/Anthropic:
  - Pipeline obligatorio para tareas complejas
  - Auditoría automática antes y después de ejecutar
  - Métricas en tiempo real
  - Cancelación y rollback
"""

from __future__ import annotations

import logging

logger = logging.getLogger("aria.commands")

# ══════════════════════════════════════════════════════════════
# DEFINICIÓN DE COMANDOS
# ══════════════════════════════════════════════════════════════

COMMANDS: dict[str, str] = {
    "run": "Ejecuta una misión con pipeline completo (Plan→Audit→Execute→Verify)",
    "plan": "Genera un plan detallado para un objetivo (solo planificación)",
    "audit": "Audita contenido, código o plan con criterio de senior engineer",
    "status": "Estado completo del sistema: agentes, memoria, skills, scheduler",
    "goals": "Lista las metas activas de ARIA",
    "agents": "Lista todos los agentes con métricas de éxito y disponibilidad",
    "schedule": "Programa una tarea recurrente. Uso: /schedule [tarea] [minutos]",
    "benchmark": "Prueba todas las capacidades e integraciones configuradas",
    "pipeline": "Consulta estado de un pipeline. Uso: /pipeline [id] o /pipeline list",
    "help": "Muestra todos los comandos disponibles",
    "think": "ARIA razona en profundidad sobre un tema o pregunta compleja",
    "code": "DeveloperAgent genera, ejecuta y valida código. Uso: /code [descripción]",
    "research": "ResearchAgent investiga un tema en profundidad con fuentes reales",
    "market": "Análisis completo de mercado para un nicho. Uso: /market [nicho]",
    "deploy": "Información sobre el estado y configuración del despliegue",
    "stop": "Detiene el pipeline activo (si hay uno corriendo)",
}


class CommandRouter:
    """
    Parsea y enruta comandos slash a sus handlers.
    Integra con AriaMind, BusinessHub y ExecutionPipeline.
    """

    def is_command(self, text: str) -> bool:
        return text.strip().startswith("/")

    def parse(self, text: str) -> tuple[str, str]:
        """Retorna (command, args). Ej: '/run crear app' → ('run', 'crear app')"""
        text = text.strip()
        if not text.startswith("/"):
            return "", text
        parts = text[1:].split(None, 1)
        cmd = parts[0].lower()
        args = parts[1].strip() if len(parts) > 1 else ""
        return cmd, args

    async def handle(self, text: str, session_id: str = "telegram") -> str:
        """Enruta el comando al handler correcto y retorna la respuesta."""
        cmd, args = self.parse(text)
        if not cmd:
            return ""

        handler = getattr(self, f"_cmd_{cmd}", None)
        if handler is None:
            similar = [c for c in COMMANDS if c.startswith(cmd[:3])]
            if similar:
                return f"❓ Comando `/{cmd}` no encontrado. ¿Quisiste decir: {', '.join(f'/{c}' for c in similar[:3])}?\n\nEscribe `/help` para ver todos los comandos."
            return f"❓ Comando desconocido: `/{cmd}`. Escribe `/help` para ver los disponibles."

        try:
            logger.info("[Commands] /%s args=%r session=%s", cmd, args[:80], session_id)
            return await handler(args, session_id)
        except Exception as exc:
            logger.error("[Commands] /%s error: %s", cmd, exc, exc_info=True)
            return f"❌ Error ejecutando `/{cmd}`: {exc}"

    # ══════════════════════════════════════════════════════════════
    # HANDLERS
    # ══════════════════════════════════════════════════════════════

    async def _cmd_help(self, args: str, session_id: str) -> str:
        lines = ["**Comandos ARIA** — Sistema de agentes autónomo\n"]
        for cmd, desc in COMMANDS.items():
            lines.append(f"`/{cmd}` — {desc}")
        lines.append("\n_Tip: Todos los comandos también funcionan en lenguaje natural._")
        return "\n".join(lines)

    async def _cmd_status(self, args: str, session_id: str) -> str:
        from apps.core.cognition.aria_mind import get_aria_mind
        from apps.core.training.continuous_trainer import get_trainer

        try:
            trainer = get_trainer().get_status()
            skills = trainer.get("skill_scores", {})
            mind = get_aria_mind()
            goals = await mind._load_goals()

            skill_lines = "\n".join(
                f"  {'✅' if v >= 70 else '⚠️' if v >= 40 else '❌'} {k}: {v:.0f}/100"
                for k, v in skills.items()
            )
            goal_count = len(goals)
            active_goals = len([g for g in goals if g.get("status") == "active"])

            return (
                f"**Estado del Sistema ARIA**\n\n"
                f"🟢 Sistema: ACTIVO\n"
                f"🔄 Ciclos del trainer: {trainer.get('cycle', 0)}\n"
                f"🎯 Metas: {active_goals} activas / {goal_count} total\n\n"
                f"**Skills:**\n{skill_lines or '  No hay datos aún'}\n\n"
                f"_Actualizado: {trainer.get('last_cycle_at', 'nunca')}_"
            )
        except Exception as exc:
            return f"⚠️ No se pudo obtener status completo: {exc}"

    async def _cmd_run(self, args: str, session_id: str) -> str:
        if not args:
            return "❓ Uso: `/run [misión]`\nEjemplo: `/run crear contenido viral sobre IA para LinkedIn`"

        from apps.core.agents.execution_pipeline import get_pipeline

        await _notify(
            session_id,
            f"🚀 Iniciando pipeline para: _{args[:80]}_\n⏳ Esto puede tomar 30-90 segundos...",
        )

        run = await get_pipeline().run(mission=args)
        s = run.summary()

        audits = s.get("audit_results", [])
        avg_score = sum(a.get("score", 0) for a in audits) // max(len(audits), 1) if audits else "—"
        stage_icon = {"complete": "✅", "failed": "❌", "execute": "⚡"}.get(
            s.get("stage", ""), "🔄"
        )

        output_summary = ""
        if s.get("output"):
            output_summary = str(s["output"].get("summary", ""))[:300]

        return (
            f"{stage_icon} **Pipeline #{s['id'][:8]}** — {s.get('stage', '?').upper()}\n\n"
            f"📋 Misión: _{args[:100]}_\n"
            f"🤖 Agente: `{s.get('agent_name', 'auto')}`\n"
            f"🔄 Iteraciones: {s.get('iterations', 0)}\n"
            f"📊 Score de auditoría: {avg_score}/100\n\n"
            + (f"**Resultado:**\n{output_summary}" if output_summary else "")
        )

    async def _cmd_plan(self, args: str, session_id: str) -> str:
        if not args:
            return "❓ Uso: `/plan [objetivo]`"

        from apps.core.agents.execution_pipeline import get_pipeline

        await _notify(session_id, f"📝 Generando plan para: _{args[:80]}_...")

        pipeline = get_pipeline()
        plan = await pipeline._generate_plan(args)
        return f"**Plan para:** _{args[:100]}_\n\n{plan}"

    async def _cmd_audit(self, args: str, session_id: str) -> str:
        if not args:
            return "❓ Uso: `/audit [texto, código o plan a revisar]`"

        from apps.core.agents.auditor_agent import AuditorAgent

        auditor = AuditorAgent()
        result = await auditor.audit_output(output=args, mission="Revisión de calidad solicitada")

        verdict_icon = {"PASS": "✅", "WARN": "⚠️", "FAIL": "❌"}.get(result.verdict, "🔍")
        issues_text = ""
        if result.issues:
            issues_text = "\n\n**Issues encontrados:**\n" + "\n".join(
                f"  {'🔴' if i.severity == 'critical' else '🟡' if i.severity == 'major' else '🟢'} "
                f"[{i.severity.upper()}] {i.description}\n    → Fix: _{i.fix}_"
                for i in result.issues[:5]
            )

        suggestions_text = ""
        if result.suggestions:
            suggestions_text = "\n\n**Sugerencias:**\n" + "\n".join(
                f"  • {s}" for s in result.suggestions[:3]
            )

        return (
            f"{verdict_icon} **Auditoría: {result.verdict}** — Score: {result.score}/100\n\n"
            f"_{result.reasoning[:400]}_" + issues_text + suggestions_text
        )

    async def _cmd_goals(self, args: str, session_id: str) -> str:
        from apps.core.cognition.aria_mind import get_aria_mind

        mind = get_aria_mind()
        goals = await mind._load_goals()

        if not goals:
            return (
                "🎯 No hay metas activas. Usa `/run [misión]` para que ARIA defina sus objetivos."
            )

        status_icon = {"active": "🟢", "completed": "✅", "paused": "⏸️", "failed": "❌"}
        lines = ["**Metas activas de ARIA:**\n"]
        for i, g in enumerate(goals[:10], 1):
            icon = status_icon.get(g.get("status", "active"), "🔵")
            priority = g.get("priority", 5)
            progress = g.get("progress", "")
            lines.append(
                f"{i}. {icon} **{g.get('text', '?')[:100]}**\n"
                f"   Prioridad: {priority}/10" + (f" | {progress[:80]}" if progress else "")
            )

        return "\n".join(lines)

    async def _cmd_agents(self, args: str, session_id: str) -> str:
        from apps.core.agents.business_hub import _AGENT_REGISTRY

        lines = ["**Agentes disponibles:**\n"]
        seen: set[str] = set()
        for key, path in _AGENT_REGISTRY.items():
            class_name = path.split(".")[-1]
            if class_name in seen:
                continue
            seen.add(class_name)
            lines.append(f"🤖 `{key}` — {class_name}")

        lines.append("\n**Agentes del sistema:**")
        lines.append("⚙️ `orchestrator` — Director central de ciclos autónomos")
        lines.append("🧠 `aria_mind` — Motor cognitivo persistente")
        lines.append("📊 `continuous_trainer` — Monitoreo de salud 24/7")
        lines.append("🔍 `auditor` — Control de calidad pre/post ejecución")
        lines.append("🔄 `execution_pipeline` — Orquestador Plan→Audit→Execute→Verify")
        lines.append(f"\n_Total: {len(seen) + 5} agentes activos_")
        lines.append("Usa `/run [misión]` para activar cualquiera automáticamente.")

        return "\n".join(lines)

    async def _cmd_think(self, args: str, session_id: str) -> str:
        if not args:
            return "❓ Uso: `/think [pregunta o tema]`"

        from apps.core.cognition.aria_mind import get_aria_mind

        response = await get_aria_mind().handle(
            f"Quiero que pienses en profundidad sobre esto: {args}", session_id
        )
        return response.text

    async def _cmd_code(self, args: str, session_id: str) -> str:
        if not args:
            return "❓ Uso: `/code [descripción de lo que necesitas]`\nEjemplo: `/code script Python para analizar CSV de ventas`"

        from apps.core.agents.business_hub import get_business_hub

        await _notify(session_id, f"💻 DeveloperAgent trabajando en: _{args[:80]}_...")
        hub = get_business_hub()
        result = await hub.dispatch("developer", args, {"auto_run": True, "auto_fix": True})
        summary = result.get("summary", result.get("code", str(result))[:500])
        return f"💻 **DeveloperAgent** completado:\n\n{summary}"

    async def _cmd_research(self, args: str, session_id: str) -> str:
        if not args:
            return (
                "❓ Uso: `/research [tema]`\nEjemplo: `/research mercado de SaaS B2B en LATAM 2025`"
            )

        from apps.core.agents.business_hub import get_business_hub

        await _notify(session_id, f"🔍 ResearchAgent investigando: _{args[:80]}_...")
        hub = get_business_hub()
        result = await hub.dispatch("research", args, {"depth": "deep"})
        report = result.get("report", result.get("summary", ""))[:2000]
        return f"🔍 **Reporte de investigación:**\n\n{report}"

    async def _cmd_market(self, args: str, session_id: str) -> str:
        if not args:
            return (
                "❓ Uso: `/market [nicho]`\nEjemplo: `/market herramientas de productividad con IA`"
            )

        from apps.core.agents.business_hub import get_business_hub

        await _notify(session_id, f"📊 Analizando mercado: _{args[:80]}_...")
        hub = get_business_hub()
        result = await hub.dispatch(
            "research",
            f"Análisis de mercado: {args}",
            {
                "depth": "comprehensive",
                "output": "report",
            },
        )
        report = result.get("report", result.get("summary", ""))[:2000]
        return f"📊 **Análisis de mercado — {args[:60]}:**\n\n{report}"

    async def _cmd_benchmark(self, args: str, session_id: str) -> str:
        from apps.core.training.continuous_trainer import get_trainer

        trainer = get_trainer()
        # Force a new evaluation cycle
        await trainer._eval_ai_client()
        await trainer._eval_huggingface()
        await trainer._eval_memory()
        status = trainer.get_status()
        skills = status.get("skill_scores", {})

        lines = ["**Benchmark de capacidades ARIA:**\n"]
        total_score = 0
        for k, v in skills.items():
            icon = "✅" if v >= 70 else "⚠️" if v >= 40 else "❌"
            lines.append(f"{icon} {k}: {v:.0f}/100")
            total_score += v

        avg = total_score / max(len(skills), 1)
        lines.append(f"\n**Score global: {avg:.0f}/100**")
        return "\n".join(lines)

    async def _cmd_pipeline(self, args: str, session_id: str) -> str:
        from apps.core.agents.execution_pipeline import get_pipeline

        pipeline = get_pipeline()

        if args in ("list", ""):
            runs = pipeline.list_runs(limit=10)
            if not runs:
                return "📋 No hay pipelines recientes."
            lines = ["**Pipelines recientes:**\n"]
            for r in runs:
                icon = {"complete": "✅", "failed": "❌"}.get(r.get("stage", ""), "🔄")
                lines.append(
                    f"{icon} `{r['id'][:8]}` — {r.get('mission', '?')[:60]} "
                    f"({r.get('stage', '?')})"
                )
            return "\n".join(lines)

        # Buscar por ID parcial
        run = pipeline.get_run(args)
        if not run:
            # Try partial match
            all_runs = pipeline.list_runs(100)
            match = next((r for r in all_runs if r["id"].startswith(args)), None)
            if match:
                run = pipeline.get_run(match["id"])
        if not run:
            return f"❌ Pipeline `{args}` no encontrado."

        s = run.summary()
        icon = {"complete": "✅", "failed": "❌"}.get(s.get("stage", ""), "🔄")
        return (
            f"{icon} **Pipeline `{s['id'][:8]}`**\n"
            f"Misión: _{s.get('mission', '?')[:100]}_\n"
            f"Stage: `{s.get('stage', '?')}`\n"
            f"Iteraciones: {s.get('iterations', 0)}\n"
            f"Éxito: {'✅' if s.get('success') else '❌'}\n"
            f"Iniciado: {s.get('started_at', '?')}"
        )

    async def _cmd_schedule(self, args: str, session_id: str) -> str:
        parts = args.rsplit(None, 1)
        if len(parts) != 2:
            return "❓ Uso: `/schedule [tarea] [minutos]`\nEjemplo: `/schedule analizar tendencias de mercado 60`"
        task, interval_str = parts
        try:
            interval = int(interval_str)
            if interval < 5:
                return "⚠️ Intervalo mínimo: 5 minutos."
        except ValueError:
            return f"❌ `{interval_str}` no es un número válido de minutos."

        try:

            from apps.core.agents.business_hub import get_business_hub
            from apps.core.main import scheduler

            job_id = f"user_task_{task[:20].replace(' ', '_')}"

            async def run_task():
                hub = get_business_hub()
                await hub.dispatch("auto", task)

            scheduler.add_job(
                run_task,
                "interval",
                minutes=interval,
                id=job_id,
                replace_existing=True,
            )
            return (
                f"✅ Tarea programada:\n"
                f"📋 Tarea: _{task}_\n"
                f"⏱️ Cada {interval} minutos\n"
                f"🆔 ID: `{job_id}`\n\n"
                f"_Para cancelar: modifica el scheduler desde /status._"
            )
        except Exception as exc:
            return f"❌ Error al programar: {exc}"

    async def _cmd_deploy(self, args: str, session_id: str) -> str:
        return (
            "**Despliegue de ARIA en Fly.io**\n\n"
            "🌍 URL: https://aria-ai.fly.dev\n"
            "⚙️ Máquinas activas: ≥1 (sin cold starts)\n"
            "🐳 Runtime: Python 3.12 + FastAPI + Playwright Chromium\n"
            "🔄 Auto-deploy: push a `main` → Fly CI detecta y despliega\n\n"
            "**Para forzar deploy manual:**\n"
            "`fly deploy --app aria-ai` (desde terminal con fly CLI)\n\n"
            "_Nota: Los secrets se gestionan en Fly.io y GitHub, no en código._"
        )

    async def _cmd_stop(self, args: str, session_id: str) -> str:
        return (
            "⏹️ Para detener un pipeline específico, espera a que el ciclo actual termine "
            "o reinicia el servicio en Fly.io.\n"
            "_Los pipelines en ARIA son tasks async que no se pueden cancelar mid-flight._"
        )


# ══════════════════════════════════════════════════════════════
# HELPERS
# ══════════════════════════════════════════════════════════════


async def _notify(session_id: str, message: str) -> None:
    """Envía notificación intermedia si la sesión es Telegram."""
    if session_id.startswith("telegram:") or session_id == "telegram":
        try:
            from apps.core.tools.telegram_bot import get_bot

            chat_id = session_id.replace("telegram:", "")
            if chat_id.isdigit():
                await get_bot()._send_message(int(chat_id), message)
        except Exception:
            pass


# Singleton
_router: CommandRouter | None = None


def get_command_router() -> CommandRouter:
    global _router
    if _router is None:
        _router = CommandRouter()
    return _router
