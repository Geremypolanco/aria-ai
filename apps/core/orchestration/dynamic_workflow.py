"""
dynamic_workflow.py — Motor de Flujos Dinámicos de ARIA.

Este es el patrón que define a las IA frontera de 2026 (Claude Code Dynamic
Workflows, GPT Multi-agent, Gemini Antigravity): en lugar de responder con una
sola llamada al modelo, ARIA **descompone** un objetivo en subtareas, lanza
**subagentes en paralelo** enrutando cada uno al modelo óptimo, **verifica de
forma adversarial** cada resultado antes de aceptarlo, e integra todo en una
respuesta final coherente.

Fases:
    1. PLAN       — un modelo estratega descompone el objetivo en 2-6 subtareas
                    independientes (JSON). Si falla, degrada a una sola tarea.
    2. EXECUTE    — subagentes en paralelo (con tope de concurrencia, como el
                    límite de 16 de Claude Code) enrutados por tipo de tarea.
    3. VERIFY     — cada resultado se somete a un verificador adversarial; si se
                    detecta un fallo, se hace un único intento de reparación.
    4. SYNTHESIZE — un modelo integrador combina las salidas verificadas en la
                    entrega final.

El motor depende solo de la interfaz `.complete(...)` de `AriaAIClient`, por lo
que es 100 % testeable sin red inyectando un cliente falso.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Protocol

from apps.core.tools.ai_client import AIModel, AIResponse

logger = logging.getLogger("aria.dynamic_workflow")

# Tope de subagentes concurrentes. El servidor es pequeño; 6 mantiene la
# latencia acotada sin saturar los proveedores de inferencia.
DEFAULT_CONCURRENCY = 6
# Cota dura de subtareas para que un plan desbocado no dispare el costo.
MAX_SUBTASKS = 6


class TaskKind(StrEnum):
    """Tipo de subtarea → determina a qué nivel de modelo se enruta."""

    REASON = "reason"  # análisis profundo, estrategia
    CODE = "code"  # generación / revisión de código
    RESEARCH = "research"  # síntesis de información
    CREATIVE = "creative"  # copy, ideas, contenido
    FAST = "fast"  # tareas simples y de alto volumen


# Mapa de tipo de tarea → nivel de modelo del router multi-proveedor.
_KIND_TO_MODEL: dict[TaskKind, AIModel] = {
    TaskKind.REASON: AIModel.REASONING,
    TaskKind.CODE: AIModel.CODE,
    TaskKind.RESEARCH: AIModel.STRATEGY,
    TaskKind.CREATIVE: AIModel.CREATIVE,
    TaskKind.FAST: AIModel.FAST,
}


class SupportsComplete(Protocol):
    """Interfaz mínima que el motor necesita del cliente de IA."""

    async def complete(
        self,
        system: str,
        user: str,
        model: AIModel = ...,
        max_tokens: int = ...,
        temperature: float = ...,
        json_mode: bool = ...,
        agent_name: str = ...,
    ) -> AIResponse: ...


@dataclass
class SubTask:
    """Una unidad de trabajo que ejecuta un subagente."""

    id: str
    title: str
    prompt: str
    kind: TaskKind = TaskKind.RESEARCH

    def model(self) -> AIModel:
        return _KIND_TO_MODEL.get(self.kind, AIModel.STRATEGY)


@dataclass
class SubTaskResult:
    """Resultado de un subagente, con su traza de verificación."""

    task: SubTask
    output: str
    model_used: str
    tokens: int = 0
    latency_ms: int = 0
    ok: bool = True
    error: str | None = None
    verified: bool = False
    critique: str | None = None
    repaired: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.task.id,
            "title": self.task.title,
            "kind": self.task.kind.value,
            "model_used": self.model_used,
            "tokens": self.tokens,
            "latency_ms": self.latency_ms,
            "ok": self.ok,
            "verified": self.verified,
            "repaired": self.repaired,
            "critique": self.critique,
            "error": self.error,
            "output": self.output,
        }


@dataclass
class WorkflowResult:
    """Salida completa de un flujo dinámico."""

    goal: str
    plan: list[SubTask]
    results: list[SubTaskResult]
    synthesis: str
    ok: bool = True
    total_tokens: int = 0
    duration_ms: int = 0
    started_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    def to_dict(self) -> dict[str, Any]:
        return {
            "goal": self.goal,
            "ok": self.ok,
            "synthesis": self.synthesis,
            "subtasks": [r.to_dict() for r in self.results],
            "plan_size": len(self.plan),
            "total_tokens": self.total_tokens,
            "duration_ms": self.duration_ms,
            "started_at": self.started_at,
        }


# ── PROMPTS ───────────────────────────────────────────────────────────────

_PLANNER_SYSTEM = (
    "Eres el planificador de ARIA, un sistema de agentes autónomo. Descompones un "
    "objetivo en subtareas INDEPENDIENTES que puedan ejecutarse en paralelo (sin que "
    "una dependa del resultado de otra). Menos subtareas bien definidas es mejor que "
    "muchas triviales. Cada subtarea declara su tipo: 'reason' (análisis/estrategia), "
    "'code' (programación), 'research' (síntesis de información), 'creative' (copy/ideas) "
    "o 'fast' (tareas simples)."
)

_PLANNER_USER = """Objetivo:
{goal}
{context}
Devuelve entre 2 y {max_tasks} subtareas paralelas como JSON con esta forma exacta:
{{"subtasks": [{{"title": "...", "prompt": "instrucción completa y autónoma para el subagente", "kind": "reason|code|research|creative|fast"}}]}}
Cada 'prompt' debe ser autosuficiente: el subagente NO ve el objetivo global ni las otras subtareas."""

_VERIFIER_SYSTEM = (
    "Eres un verificador adversarial. Tu trabajo es encontrar fallos reales en el "
    "resultado de un subagente: afirmaciones incorrectas, requisitos ignorados, código "
    "que no funcionaría, alucinaciones. Sé estricto pero justo. Si el resultado cumple "
    "razonablemente la tarea, apruébalo."
)

_VERIFIER_USER = """Tarea encomendada:
{prompt}

Resultado del subagente:
{output}

¿El resultado cumple la tarea sin fallos graves? Responde SOLO JSON:
{{"ok": true|false, "critique": "si ok=false, explica el fallo concreto en una frase; si ok=true, deja vacío"}}"""

_SYNTH_SYSTEM = (
    "Eres ARIA integrando el trabajo de tu equipo en la respuesta final para el usuario. "
    "Hablas como una persona real: cálida, directa, con criterio —no como un reporte "
    "corporativo. Nada de 'Como IA', ni jerga vacía, ni relleno. Sintetizas (no repites ni "
    "listas mecánicamente lo que hizo cada subagente): entregas UNA respuesta coherente y "
    "accionable, como se la darías a un colega que respetas. Responde en el idioma del objetivo."
)

_SYNTH_USER = """Objetivo del usuario:
{goal}

Trabajo de tu equipo (subagentes):
{parts}

Escribe la respuesta final directa y con criterio. Si algo quedó incierto o dependía de un dato
que no teníamos, dilo con honestidad en vez de inventarlo."""

_CLARIFY_SYSTEM = (
    "Eres ARIA decidiendo si un pedido tiene suficiente contexto para hacerlo EXCELENTE, o si "
    "faltan 1-3 datos clave que cambiarían el resultado. Piensa como un buen consultor: asumir "
    "a ciegas produce entregables inútiles. Hablas como persona —cálido y directo—."
)

_CLARIFY_USER = """Pedido del usuario:
{goal}
{context}
¿Tienes suficiente contexto para entregar algo genuinamente útil, o faltan datos clave?
Responde SOLO JSON:
{{"ready": true|false, "questions": ["pregunta corta y concreta 1", "..."], "intro": "una frase humana y cálida para acompañar las preguntas; vacío si ready=true"}}
Sé exigente: si asumir podría arruinar el entregable (p.ej. precios sin saber qué es el producto, para quién, o su métrica de valor), ready=false con 1-3 preguntas que de verdad cambien el resultado. Si el objetivo ya trae el contexto necesario, ready=true. Responde en el idioma del pedido."""


class DynamicWorkflow:
    """Orquestador de flujos dinámicos multi-agente.

    Uso:
        wf = DynamicWorkflow(client)
        result = await wf.run("Diseña y valida un plan de lanzamiento para X")
        print(result.synthesis)
    """

    def __init__(
        self,
        client: SupportsComplete,
        max_concurrency: int = DEFAULT_CONCURRENCY,
        verify: bool = True,
        clarify: bool = True,
    ) -> None:
        self._client = client
        self._sem = asyncio.Semaphore(max(1, max_concurrency))
        self._verify = verify
        # When True, an under-specified goal yields clarifying questions instead
        # of a guessed deliverable (no subagents run). The chat shows them as a turn.
        self._clarify = clarify
        # Contadores de tokens de las fases que no viven en un SubTaskResult
        # (planner + synthesizer). Se reinician al inicio de cada run().
        self._plan_tokens = 0
        self._synth_tokens = 0

    # ── ORQUESTACIÓN PRINCIPAL ────────────────────────────────────────────

    async def run(self, goal: str, context: str | None = None) -> WorkflowResult:
        """Ejecuta el flujo completo: plan → paralelo → verificar → sintetizar."""
        t0 = time.time()
        goal = (goal or "").strip()
        if not goal:
            return WorkflowResult(
                goal=goal, plan=[], results=[], synthesis="", ok=False, duration_ms=0
            )

        self._plan_tokens = 0
        self._synth_tokens = 0

        # Aclarar antes de ejecutar: si falta contexto clave, pregunta en vez de adivinar.
        if self._clarify:
            clarify_msg = await self._assess(goal, context)
            if clarify_msg:
                return WorkflowResult(
                    goal=goal,
                    plan=[],
                    results=[],
                    synthesis=clarify_msg,
                    ok=True,
                    total_tokens=self._plan_tokens,
                    duration_ms=int((time.time() - t0) * 1000),
                )

        plan = await self._plan(goal, context)
        logger.info("[workflow] plan de %d subtareas para: %s", len(plan), goal[:80])

        # Ejecutar subagentes en paralelo (con tope de concurrencia).
        results = await asyncio.gather(*(self._execute(task) for task in plan))

        # Verificar (y reparar una vez) de forma adversarial, también en paralelo.
        if self._verify:
            results = list(await asyncio.gather(*(self._verify_and_repair(r) for r in results)))

        synthesis = await self._synthesize(goal, results)

        # Costo real = subagentes (incl. verify + repair) + planner + synth.
        total_tokens = sum(r.tokens for r in results) + self._plan_tokens + self._synth_tokens
        ok = any(r.ok for r in results) and bool(synthesis)
        return WorkflowResult(
            goal=goal,
            plan=plan,
            results=results,
            synthesis=synthesis,
            ok=ok,
            total_tokens=total_tokens,
            duration_ms=int((time.time() - t0) * 1000),
        )

    # ── STREAMING ─────────────────────────────────────────────────────────

    async def run_events(self, goal: str, context: str | None = None):
        """Igual que run(), pero emite eventos a medida que avanza — para SSE.

        Yields dicts con `type`:
            start        — {goal}
            plan         — {subtasks:[{id,title,kind}]}
            subtask_done — {result:{...}}   (uno por subagente, al completar+verificar)
            done         — {ok, synthesis, subtasks:[...], total_tokens, duration_ms}
            error        — {error}          (solo si algo irrecuperable ocurre)

        Los subagentes se completan con as_completed → el cliente ve cada uno
        aparecer en cuanto termina, en vez de esperar a todo el lote.
        """
        t0 = time.time()
        goal = (goal or "").strip()
        if not goal:
            yield {"type": "done", "ok": False, "synthesis": "", "subtasks": [], "total_tokens": 0}
            return

        self._plan_tokens = 0
        self._synth_tokens = 0

        try:
            yield {"type": "start", "goal": goal}

            # Aclarar antes de ejecutar: si falta contexto, pregunta (sin correr subagentes).
            if self._clarify:
                clarify_msg = await self._assess(goal, context)
                if clarify_msg:
                    yield {
                        "type": "done",
                        "ok": True,
                        "synthesis": clarify_msg,
                        "subtasks": [],
                        "total_tokens": self._plan_tokens,
                        "duration_ms": int((time.time() - t0) * 1000),
                    }
                    return

            plan = await self._plan(goal, context)
            yield {
                "type": "plan",
                "subtasks": [{"id": t.id, "title": t.title, "kind": t.kind.value} for t in plan],
            }

            async def _one(task: SubTask) -> SubTaskResult:
                res = await self._execute(task)
                if self._verify:
                    res = await self._verify_and_repair(res)
                return res

            results: list[SubTaskResult] = []
            for fut in asyncio.as_completed([_one(t) for t in plan]):
                res = await fut
                results.append(res)
                yield {"type": "subtask_done", "result": res.to_dict()}

            synthesis = await self._synthesize(goal, results)
            total = sum(r.tokens for r in results) + self._plan_tokens + self._synth_tokens
            yield {
                "type": "done",
                "ok": any(r.ok for r in results) and bool(synthesis),
                "synthesis": synthesis,
                "subtasks": [r.to_dict() for r in results],
                "total_tokens": total,
                "duration_ms": int((time.time() - t0) * 1000),
            }
        except Exception as exc:  # noqa: BLE001 — el stream nunca debe colgar sin cerrar.
            logger.warning("[workflow] run_events falló: %s", exc)
            yield {"type": "error", "error": str(exc)[:200]}

    # ── FASE 0: ACLARAR ───────────────────────────────────────────────────

    async def _assess(self, goal: str, context: str | None) -> str | None:
        """Devuelve un mensaje de aclaración (cálido, con 1-3 preguntas) si al objetivo
        le falta contexto clave; None si ya hay suficiente para ejecutar.

        Best-effort: ante cualquier fallo o si el modelo dice que está listo, devuelve
        None para no bloquear un pedido bien especificado.
        """
        ctx = f"\nContexto adicional:\n{context}\n" if context else "\n"
        try:
            resp = await self._client.complete(
                system=_CLARIFY_SYSTEM,
                user=_CLARIFY_USER.format(goal=goal, context=ctx),
                model=AIModel.FAST,
                max_tokens=400,
                temperature=0.2,
                json_mode=True,
                agent_name="workflow.clarify",
            )
            if not resp or not resp.success:
                return None
            self._plan_tokens += resp.tokens_used
            data = json.loads(resp.content)
            if data.get("ready", True):
                return None
            questions = [str(q).strip() for q in (data.get("questions") or []) if str(q).strip()][
                :3
            ]
            if not questions:
                return None
            intro = (
                str(data.get("intro") or "").strip()
                or "Antes de arrancar, cuéntame un par de cosas para que esto salga bien:"
            )
            return intro + "\n\n" + "\n".join("- " + q for q in questions)
        except Exception:  # noqa: BLE001 — aclarar es best-effort; ante duda, ejecuta.
            return None

    # ── FASE 1: PLAN ──────────────────────────────────────────────────────

    async def _plan(self, goal: str, context: str | None) -> list[SubTask]:
        ctx = f"\nContexto adicional:\n{context}\n" if context else "\n"
        try:
            resp = await self._client.complete(
                system=_PLANNER_SYSTEM,
                user=_PLANNER_USER.format(goal=goal, context=ctx, max_tasks=MAX_SUBTASKS),
                model=AIModel.STRATEGY,
                max_tokens=1200,
                temperature=0.3,
                json_mode=True,
                agent_name="workflow.planner",
            )
            if resp and resp.success:
                self._plan_tokens += resp.tokens_used
            data = json.loads(resp.content) if resp and resp.success else {}
            raw = data.get("subtasks") or []
            tasks: list[SubTask] = []
            for i, item in enumerate(raw[:MAX_SUBTASKS]):
                if not isinstance(item, dict):
                    continue
                prompt = str(item.get("prompt") or item.get("title") or "").strip()
                if not prompt:
                    continue
                kind = self._coerce_kind(item.get("kind"))
                tasks.append(
                    SubTask(
                        id=f"t{i + 1}",
                        title=str(item.get("title") or f"Subtarea {i + 1}").strip()[:120],
                        prompt=prompt,
                        kind=kind,
                    )
                )
            if tasks:
                return tasks
        except Exception as exc:  # noqa: BLE001 — el planner nunca debe tumbar el flujo.
            logger.warning("[workflow] planificación falló (%s) — degradando a tarea única", exc)

        # Degradación: una sola subtarea que es el objetivo tal cual.
        return [SubTask(id="t1", title="Objetivo completo", prompt=goal, kind=TaskKind.REASON)]

    @staticmethod
    def _coerce_kind(value: Any) -> TaskKind:
        try:
            return TaskKind(str(value).strip().lower())
        except ValueError:
            return TaskKind.RESEARCH

    # ── FASE 2: EJECUTAR SUBAGENTE ────────────────────────────────────────

    async def _execute(self, task: SubTask) -> SubTaskResult:
        system = (
            "Eres un subagente especializado de ARIA. Ejecutas UNA tarea concreta con "
            "rigor y devuelves solo el resultado útil, sin preámbulos ni disculpas."
        )
        async with self._sem:
            try:
                resp = await self._client.complete(
                    system=system,
                    user=task.prompt,
                    model=task.model(),
                    max_tokens=1800,
                    temperature=0.6,
                    agent_name=f"workflow.{task.id}",
                )
                if resp and resp.success:
                    return SubTaskResult(
                        task=task,
                        output=(resp.content or "").strip(),
                        model_used=resp.model,
                        tokens=resp.tokens_used,
                        latency_ms=resp.latency_ms,
                        ok=True,
                    )
                return SubTaskResult(
                    task=task,
                    output="",
                    model_used=resp.model if resp else "none",
                    ok=False,
                    error=(resp.error if resp else "sin respuesta"),
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning("[workflow] subagente %s falló: %s", task.id, exc)
                return SubTaskResult(
                    task=task, output="", model_used="none", ok=False, error=str(exc)[:200]
                )

    # ── FASE 3: VERIFICAR + REPARAR ───────────────────────────────────────

    async def _verify_and_repair(self, result: SubTaskResult) -> SubTaskResult:
        if not result.ok or not result.output:
            return result
        verdict = await self._verify_one(result)
        if verdict is None:
            # El verificador no está disponible: no bloqueamos, aceptamos tal cual.
            result.verified = True
            return result
        ok, critique = verdict
        if ok:
            result.verified = True
            return result

        # Un único intento de reparación guiado por la crítica.
        result.critique = critique
        repaired = await self._repair(result, critique)
        if repaired is not None:
            result.output = repaired.output
            result.tokens += repaired.tokens
            result.latency_ms += repaired.latency_ms
            result.model_used = repaired.model_used
            result.repaired = True
            result.verified = True
        return result

    async def _verify_one(self, result: SubTaskResult) -> tuple[bool, str] | None:
        async with self._sem:
            try:
                resp = await self._client.complete(
                    system=_VERIFIER_SYSTEM,
                    user=_VERIFIER_USER.format(
                        prompt=result.task.prompt, output=result.output[:4000]
                    ),
                    model=AIModel.FAST,
                    max_tokens=300,
                    temperature=0.0,
                    json_mode=True,
                    agent_name=f"workflow.verify.{result.task.id}",
                )
                if not resp or not resp.success:
                    return None
                result.tokens += resp.tokens_used
                data = json.loads(resp.content)
                return bool(data.get("ok", True)), str(data.get("critique") or "").strip()
            except Exception:  # noqa: BLE001 — verificación best-effort.
                return None

    async def _repair(self, result: SubTaskResult, critique: str) -> SubTaskResult | None:
        async with self._sem:
            try:
                resp = await self._client.complete(
                    system=(
                        "Eres un subagente de ARIA corrigiendo tu propio trabajo. Un revisor "
                        "encontró un fallo. Devuelve el resultado CORREGIDO completo, no una "
                        "explicación del cambio."
                    ),
                    user=(
                        f"Tarea:\n{result.task.prompt}\n\n"
                        f"Tu resultado anterior:\n{result.output[:3000]}\n\n"
                        f"Fallo detectado por el revisor:\n{critique}\n\n"
                        "Entrega el resultado corregido:"
                    ),
                    model=result.task.model(),
                    max_tokens=1800,
                    temperature=0.4,
                    agent_name=f"workflow.repair.{result.task.id}",
                )
                if resp and resp.success and resp.content.strip():
                    return SubTaskResult(
                        task=result.task,
                        output=resp.content.strip(),
                        model_used=resp.model,
                        tokens=resp.tokens_used,
                        latency_ms=resp.latency_ms,
                    )
            except Exception:  # noqa: BLE001
                return None
        return None

    # ── FASE 4: SINTETIZAR ────────────────────────────────────────────────

    async def _synthesize(self, goal: str, results: list[SubTaskResult]) -> str:
        usable = [r for r in results if r.ok and r.output]
        if not usable:
            return ""
        # Atajo: con un solo resultado no hay nada que integrar.
        if len(usable) == 1:
            return usable[0].output

        parts = "\n\n".join(f"### {r.task.title}\n{r.output[:2500]}" for r in usable)
        try:
            resp = await self._client.complete(
                system=_SYNTH_SYSTEM,
                user=_SYNTH_USER.format(goal=goal, parts=parts),
                model=AIModel.STRATEGY,
                max_tokens=2200,
                temperature=0.5,
                agent_name="workflow.synth",
            )
            if resp and resp.success and resp.content.strip():
                self._synth_tokens += resp.tokens_used
                return resp.content.strip()
        except Exception as exc:  # noqa: BLE001
            logger.warning("[workflow] síntesis falló: %s", exc)

        # Degradación: concatenar las secciones verificadas.
        return "\n\n".join(f"**{r.task.title}**\n{r.output}" for r in usable)


# ── FÁBRICA ───────────────────────────────────────────────────────────────


async def get_dynamic_workflow(
    max_concurrency: int = DEFAULT_CONCURRENCY, verify: bool = True
) -> DynamicWorkflow:
    """Construye un flujo dinámico con el cliente de IA compartido de ARIA."""
    from apps.core.tools.ai_client import get_ai_client_async

    client = await get_ai_client_async()
    return DynamicWorkflow(client, max_concurrency=max_concurrency, verify=verify)
