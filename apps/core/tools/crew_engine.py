"""
crew_engine.py — Multi-agent collaboration (CrewAI style) para ARIA AI.

Orquesta equipos de agentes especializados que colaboran secuencialmente.
Cada miembro del equipo recibe el trabajo acumulado de los anteriores como contexto.

Equipos predefinidos:
  - research_crew:  Investigador → Analista → Redactor
  - content_crew:   Investigador → SEO Strategist → Editor
  - dev_crew:       Product Manager → Developer → QA
  - sales_crew:     Analista de Mercado → Sales Strategist → Copywriter
  - launch_crew:    Estratega → Marketing Director → Analista Financiero
"""

from __future__ import annotations

import contextlib
import logging
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable

logger = logging.getLogger("aria.crew")


@dataclass
class CrewMember:
    role: str
    goal: str
    agent_type: str  # Maps to BusinessHub: research|content|marketing|sales|developer|finance|ceo
    output: str | None = None


@dataclass
class CrewRun:
    id: str
    crew_name: str
    mission: str
    members: list[CrewMember]
    final_output: str | None = None
    started_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    completed_at: str | None = None
    success: bool = False
    error: str | None = None

    def summary(self) -> dict:
        return {
            "id": self.id,
            "crew": self.crew_name,
            "mission": self.mission[:120],
            "success": self.success,
            "members": [{"role": m.role, "done": bool(m.output)} for m in self.members],
            "started_at": self.started_at,
            "completed_at": self.completed_at,
        }


CREW_TEMPLATES: dict[str, list[dict]] = {
    "research_crew": [
        {
            "role": "Investigador Senior",
            "goal": "Investiga el tema a fondo: datos, tendencias, fuentes clave, estadísticas relevantes y contexto actual.",
            "agent_type": "research",
        },
        {
            "role": "Analista Estratégico",
            "goal": "Analiza los hallazgos del investigador. Identifica patrones, oportunidades, riesgos y conclusiones accionables.",
            "agent_type": "ceo",
        },
        {
            "role": "Redactor Ejecutivo",
            "goal": "Transforma el análisis en un informe final claro, estructurado y listo para usar. Resumen ejecutivo + puntos clave + próximos pasos.",
            "agent_type": "content",
        },
    ],
    "content_crew": [
        {
            "role": "Investigador de Contenido",
            "goal": "Investiga el tema, encuentra ángulos únicos, datos de soporte y ejemplos reales para enriquecer el contenido.",
            "agent_type": "research",
        },
        {
            "role": "Estratega SEO",
            "goal": "Define estructura, keywords principales, ángulo de marketing y formato óptimo para máxima visibilidad.",
            "agent_type": "marketing",
        },
        {
            "role": "Redactor y Editor",
            "goal": "Crea el contenido final pulido: introducción ganadora, cuerpo estructurado, CTA y optimizado para publicar.",
            "agent_type": "content",
        },
    ],
    "dev_crew": [
        {
            "role": "Product Manager",
            "goal": "Define requisitos técnicos detallados, casos de uso, arquitectura del sistema y criterios de éxito.",
            "agent_type": "ceo",
        },
        {
            "role": "Desarrollador Senior",
            "goal": "Implementa la solución técnica completa basada en los requisitos del PM. Código funcional y documentado.",
            "agent_type": "developer",
        },
        {
            "role": "QA Engineer",
            "goal": "Revisa el código, identifica bugs, casos edge, sugiere mejoras y crea documentación de la solución.",
            "agent_type": "research",
        },
    ],
    "sales_crew": [
        {
            "role": "Analista de Mercado",
            "goal": "Investiga mercado objetivo, segmentos de clientes, competidores, precios y oportunidades de penetración.",
            "agent_type": "research",
        },
        {
            "role": "Estratega de Ventas",
            "goal": "Diseña estrategia de venta completa: propuesta de valor, objeciones, pipeline y proceso de conversión.",
            "agent_type": "sales",
        },
        {
            "role": "Copywriter de Conversión",
            "goal": "Crea el copy de ventas: emails, página de ventas, scripts y materiales de marketing de alta conversión.",
            "agent_type": "marketing",
        },
    ],
    "launch_crew": [
        {
            "role": "Estratega de Producto",
            "goal": "Define posicionamiento, propuesta de valor única, go-to-market strategy y mensajes clave del lanzamiento.",
            "agent_type": "ceo",
        },
        {
            "role": "Director de Marketing",
            "goal": "Crea la campaña de lanzamiento completa: redes sociales, email marketing, content calendar y PR.",
            "agent_type": "marketing",
        },
        {
            "role": "Analista Financiero",
            "goal": "Proyecta métricas de éxito, modelo de pricing, costos de adquisición, break-even y proyecciones de revenue.",
            "agent_type": "finance",
        },
    ],
    "venture_crew": [
        {
            "role": "Analista de Negocio",
            "goal": "Valida el modelo de negocio, analiza viabilidad, TAM, competencia y barreras de entrada.",
            "agent_type": "research",
        },
        {
            "role": "Estratega Financiero",
            "goal": "Proyecta financials: runway, pricing, unidad económica, valoración y escenarios de crecimiento.",
            "agent_type": "finance",
        },
        {
            "role": "Pitch Specialist",
            "goal": "Crea el pitch deck completo y materiales para inversores. Historia convincente con datos sólidos.",
            "agent_type": "content",
        },
    ],
}


class CrewEngine:
    """
    Orquesta equipos de agentes especializados en pipelines secuenciales.
    El output de cada agente enriquece el contexto del siguiente.
    """

    def __init__(self) -> None:
        self._runs: dict[str, CrewRun] = {}

    async def run(
        self,
        mission: str,
        crew_name: str = "research_crew",
        context: str = "",
        on_progress: Callable | None = None,
    ) -> CrewRun:
        """
        Ejecuta un equipo predefinido secuencialmente.
        on_progress(step_num, total, member_role) → called after each step.
        """
        template = CREW_TEMPLATES.get(crew_name, CREW_TEMPLATES["research_crew"])
        members = [CrewMember(**m) for m in template]
        run = CrewRun(
            id=str(uuid.uuid4())[:8], crew_name=crew_name, mission=mission, members=members
        )
        self._runs[run.id] = run

        accumulated = context
        all_outputs: list[str] = []
        any_success = False
        last_error: str | None = None

        from apps.core.agents.business_hub import BusinessHub

        hub = BusinessHub()

        for i, member in enumerate(members):
            if on_progress:
                with contextlib.suppress(Exception):
                    await on_progress(i + 1, len(members), member.role)

            agent_prompt = (
                f"MISIÓN DEL EQUIPO: {mission}\n\n"
                f"TU ROL: {member.role}\n"
                f"TU OBJETIVO: {member.goal}\n"
            )
            if accumulated:
                agent_prompt += f"\nTRABAJO PREVIO DEL EQUIPO:\n{accumulated[:3500]}"

            try:
                result = await hub.dispatch(member.agent_type, agent_prompt, {})
                output = (
                    result.get("output")
                    or result.get("result")
                    or result.get("plan")
                    or str(result)
                )
                member.output = str(output)[:3000]
                any_success = True
            except Exception as exc:
                member.output = f"[Error: {exc}]"
                last_error = str(exc)
                logger.warning("[Crew:%s] member '%s' failed: %s", run.id, member.role, exc)

            all_outputs.append(f"### {member.role}\n{member.output}")
            accumulated = "\n\n".join(all_outputs)

        run.final_output = await self._synthesize(mission, members)
        run.completed_at = datetime.now(UTC).isoformat()
        run.success = any_success
        run.error = None if any_success else (last_error or "todos los miembros del equipo fallaron")
        return run

    async def run_custom(
        self,
        mission: str,
        roles: list[str],
        context: str = "",
    ) -> CrewRun:
        """
        Crea y ejecuta un equipo personalizado desde una lista de roles en texto libre.
        Mapea automáticamente cada rol al agente de negocio más adecuado.
        """
        role_to_agent = [
            (["invest", "research", "analiz"], "research"),
            (["market", "seo", "social", "campañ"], "marketing"),
            (["venta", "sales", "negoci"], "sales"),
            (["develop", "código", "program", "tech"], "developer"),
            (["content", "redact", "escrib", "copy"], "content"),
            (["finanz", "cfo", "contab", "presupuest"], "finance"),
            (["ceo", "director", "estrateg", "product"], "ceo"),
        ]

        def map_role(role: str) -> str:
            r = role.lower()
            for keywords, agent in role_to_agent:
                if any(k in r for k in keywords):
                    return agent
            return "ceo"

        members = [
            CrewMember(
                role=r, goal=f"Ejecutar tu parte de la misión como {r}", agent_type=map_role(r)
            )
            for r in roles[:5]
        ]
        run = CrewRun(
            id=str(uuid.uuid4())[:8], crew_name="custom", mission=mission, members=members
        )
        self._runs[run.id] = run

        from apps.core.agents.business_hub import BusinessHub

        hub = BusinessHub()
        accumulated = context
        all_outputs: list[str] = []
        any_success = False
        last_error: str | None = None

        for member in members:
            prompt = f"Misión: {mission}\nRol: {member.role}\n" + (
                f"\nContexto previo:\n{accumulated[:2500]}" if accumulated else ""
            )
            try:
                result = await hub.dispatch(member.agent_type, prompt, {})
                member.output = str(result.get("output") or result)[:2500]
                any_success = True
            except Exception as exc:
                member.output = f"[Error: {exc}]"
                last_error = str(exc)
            all_outputs.append(f"### {member.role}\n{member.output}")
            accumulated = "\n\n".join(all_outputs)

        run.final_output = await self._synthesize(mission, members)
        run.completed_at = datetime.now(UTC).isoformat()
        run.success = any_success
        run.error = None if any_success else (last_error or "todos los miembros del equipo fallaron")
        return run

    def list_crews(self) -> list[str]:
        return list(CREW_TEMPLATES.keys())

    def list_runs(self, limit: int = 10) -> list[dict]:
        return [
            r.summary()
            for r in sorted(self._runs.values(), key=lambda r: r.started_at, reverse=True)[:limit]
        ]

    # ── PRIVADO ───────────────────────────────────────────────────────────────

    async def _synthesize(self, mission: str, members: list[CrewMember]) -> str:
        from apps.core.tools.ai_client import AIModel, get_ai_client

        client = get_ai_client()
        contributions = "\n\n".join(f"**{m.role}:**\n{m.output or 'N/A'}" for m in members)
        resp = await client.complete(
            model=AIModel.STRATEGY,
            system=(
                "Eres el director ejecutivo del equipo. Sintetiza el trabajo en un output final "
                "cohesivo, sin redundancias, profesional y listo para usar."
            ),
            user=(
                f"Misión: {mission}\n\n"
                f"Aportes del equipo:\n{contributions[:5000]}\n\n"
                "Output final sintetizado:"
            ),
            max_tokens=2500,
        )
        return resp.content if hasattr(resp, "content") else str(resp)


_engine: CrewEngine | None = None


def get_crew_engine() -> CrewEngine:
    global _engine
    if _engine is None:
        _engine = CrewEngine()
    return _engine
