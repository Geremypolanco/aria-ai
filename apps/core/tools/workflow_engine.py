"""
workflow_engine.py — Workflow builder con lenguaje natural (Gumloop style) para ARIA AI.

Permite crear, guardar y ejecutar automatizaciones multi-paso describiendo en texto libre
qué debe hacer cada paso. ARIA descompone la intención en herramientas concretas.

Ejemplos:
  "Cada mañana investiga tendencias de IA, escribe un resumen y publícalo en Dev.to"
  "Investiga competidores de [empresa], analiza fortalezas, genera pitch deck"
  "Monitorea el precio de BTC, si baja 5% envíame alerta por email"
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

logger = logging.getLogger("aria.workflow")

REDIS_KEY    = "aria:workflows"
REDIS_TTL    = 86400 * 90  # 90 days


@dataclass
class WorkflowStep:
    tool: str
    args: dict
    description: str = ""
    result: Optional[str] = None


@dataclass
class Workflow:
    id: str
    name: str
    description: str
    steps: list[WorkflowStep]
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    last_run: Optional[str] = None
    run_count: int = 0

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "steps": [{"tool": s.tool, "args": s.args, "description": s.description} for s in self.steps],
            "created_at": self.created_at,
            "last_run": self.last_run,
            "run_count": self.run_count,
        }


class WorkflowEngine:
    """
    Motor de automatización de ARIA.
    Convierte descripciones en lenguaje natural en workflows ejecutables de múltiples pasos.
    """

    def __init__(self) -> None:
        self._workflows: dict[str, Workflow] = {}
        self._loaded = False

    async def create(self, name: str, description: str) -> dict[str, Any]:
        """
        Crea un workflow desde una descripción en lenguaje natural.
        ARIA descompone la descripción en pasos concretos automáticamente.
        """
        await self._ensure_loaded()

        from apps.core.tools.ai_client import get_ai_client, AIModel
        client = get_ai_client()

        resp = await client.complete(
            model=AIModel.STRATEGY,
            system=(
                "Eres un arquitecto de automatizaciones. Conviertes descripciones en workflows "
                "ejecutables. Responde SOLO con un JSON array de pasos."
            ),
            user=(
                f"Automatización: {description}\n\n"
                "Descompón en hasta 6 pasos usando SOLO estas herramientas de ARIA:\n"
                "- web_search(query)  — buscar información en internet\n"
                "- deep_search(query, num_pages)  — investigación profunda\n"
                "- fetch_url(url)  — leer contenido de una URL específica\n"
                "- execute_code(code, language)  — ejecutar código Python/JS\n"
                "- run_business_agent(agent, mission)  — agentes: research/content/marketing/sales/developer/finance/ceo\n"
                "- generate_image(prompt)  — generar imagen\n"
                "- create_presentation(title, topic, slide_count, template)  — presentación\n"
                "- create_social_content(topic, platforms, tone)  — contenido para redes\n"
                "- publish_article(title, content, tags, platforms)  — publicar artículo\n"
                "- send_email(subject, body, to)  — enviar email\n"
                "- deep_think(question, depth, context)  — análisis profundo\n"
                "- search_knowledge(query)  — buscar en base de conocimiento interna\n"
                "- run_crew(mission, crew)  — equipo de agentes colaborando\n\n"
                "Formato JSON:\n"
                '[{"tool": "nombre", "args": {"param": "valor"}, "description": "qué hace este paso"}]\n'
                "Usa {prev_output} en args para referenciar el output del paso anterior.\n"
                "SOLO el JSON array, sin explicaciones."
            ),
        )

        content = resp.content if hasattr(resp, "content") else str(resp)
        steps   = self._parse_steps(content)

        if not steps:
            # Fallback: single agent step
            steps = [WorkflowStep(
                tool="run_business_agent",
                args={"agent": "ceo", "mission": description},
                description=description,
            )]

        wf = Workflow(id=str(uuid.uuid4())[:8], name=name, description=description, steps=steps)
        self._workflows[wf.id] = wf
        await self._persist()

        return {
            "success": True,
            "workflow_id": wf.id,
            "name": name,
            "steps": len(steps),
            "steps_preview": [s.description or s.tool for s in steps],
        }

    async def run(self, workflow_id: str) -> dict[str, Any]:
        """Ejecuta un workflow paso a paso. El output de cada paso alimenta al siguiente."""
        await self._ensure_loaded()
        wf = self._workflows.get(workflow_id)
        if not wf:
            return {"success": False, "error": f"Workflow '{workflow_id}' no encontrado"}

        results = []
        prev_output = ""

        for i, step in enumerate(wf.steps):
            logger.info("[Workflow:%s] Step %d/%d: %s", workflow_id, i + 1, len(wf.steps), step.tool)

            # Inject {prev_output} placeholder
            enriched_args = {}
            for k, v in step.args.items():
                enriched_args[k] = v.replace("{prev_output}", prev_output[:800]) if isinstance(v, str) else v

            try:
                from apps.core.cognition.aria_mind import get_aria_mind
                obs, _ = await get_aria_mind()._execute_tool(step.tool, enriched_args)
                step.result = obs[:1500]
                prev_output = step.result
                results.append({"step": i + 1, "tool": step.tool, "desc": step.description,
                                 "success": True, "output": step.result})
            except Exception as exc:
                step.result = f"Error: {exc}"
                results.append({"step": i + 1, "tool": step.tool, "desc": step.description,
                                 "success": False, "error": str(exc)})
                logger.warning("[Workflow:%s] Step %d error: %s", workflow_id, i + 1, exc)

        wf.last_run   = datetime.now(timezone.utc).isoformat()
        wf.run_count += 1
        await self._persist()

        return {
            "success": True,
            "workflow_id": workflow_id,
            "name": wf.name,
            "steps_run": len(results),
            "results": results,
            "final_output": prev_output,
        }

    def list(self) -> list[dict]:
        return sorted([w.to_dict() for w in self._workflows.values()],
                      key=lambda w: w["created_at"], reverse=True)

    def get(self, workflow_id: str) -> Optional[dict]:
        wf = self._workflows.get(workflow_id)
        return wf.to_dict() if wf else None

    def delete(self, workflow_id: str) -> bool:
        if workflow_id in self._workflows:
            del self._workflows[workflow_id]
            return True
        return False

    # ── PRIVADO ───────────────────────────────────────────────────────────────

    def _parse_steps(self, text: str) -> list[WorkflowStep]:
        try:
            text = re.sub(r"^```[a-z]*\n?", "", text.strip(), flags=re.M)
            text = re.sub(r"\n?```$", "", text.strip())
            m    = re.search(r"\[.*\]", text, re.DOTALL)
            if m:
                data = json.loads(m.group())
                return [
                    WorkflowStep(
                        tool=s.get("tool", "run_business_agent"),
                        args=s.get("args", {}),
                        description=s.get("description", ""),
                    )
                    for s in data if isinstance(s, dict)
                ]
        except Exception:
            pass
        return []

    async def _persist(self) -> None:
        try:
            from apps.core.memory.redis_client import get_cache
            payload = json.dumps({k: v.to_dict() for k, v in self._workflows.items()})
            await get_cache().set(REDIS_KEY, payload, ttl_seconds=REDIS_TTL)
        except Exception:
            pass

    async def _ensure_loaded(self) -> None:
        if self._loaded:
            return
        self._loaded = True
        try:
            from apps.core.memory.redis_client import get_cache
            raw = await get_cache().get(REDIS_KEY)
            if raw:
                data = json.loads(raw) if isinstance(raw, str) else raw
                for wid, wd in data.items():
                    steps = [WorkflowStep(tool=s["tool"], args=s.get("args", {}),
                                          description=s.get("description", ""))
                             for s in wd.get("steps", [])]
                    self._workflows[wid] = Workflow(
                        id=wid, name=wd["name"], description=wd["description"],
                        steps=steps, created_at=wd.get("created_at", ""),
                        last_run=wd.get("last_run"), run_count=wd.get("run_count", 0),
                    )
                logger.info("[WorkflowEngine] Loaded %d workflows from Redis", len(self._workflows))
        except Exception:
            pass


_engine: Optional[WorkflowEngine] = None


def get_workflow_engine() -> WorkflowEngine:
    global _engine
    if _engine is None:
        _engine = WorkflowEngine()
    return _engine
