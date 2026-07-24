"""
workflow_engine.py — Natural-language workflow builder (Gumloop style) for ARIA AI.

Lets you create, save, and run multi-step automations by describing in free text
what each step should do. ARIA breaks the intent down into concrete tools.

Examples:
  "Every morning research AI trends, write a summary, and publish it on Dev.to"
  "Research competitors of [company], analyze strengths, generate a pitch deck"
  "Monitor the BTC price, if it drops 5% send me an email alert"
"""

from __future__ import annotations

import json
import logging
import re
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

logger = logging.getLogger("aria.workflow")

REDIS_KEY = "aria:workflows"
REDIS_TTL = 86400 * 90  # 90 days


@dataclass
class WorkflowStep:
    tool: str
    args: dict
    description: str = ""
    result: str | None = None


@dataclass
class Workflow:
    id: str
    name: str
    description: str
    steps: list[WorkflowStep]
    created_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    last_run: str | None = None
    run_count: int = 0

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "steps": [
                {"tool": s.tool, "args": s.args, "description": s.description} for s in self.steps
            ],
            "created_at": self.created_at,
            "last_run": self.last_run,
            "run_count": self.run_count,
        }


class WorkflowEngine:
    """
    ARIA's automation engine.
    Converts natural-language descriptions into executable multi-step workflows.
    """

    def __init__(self) -> None:
        self._workflows: dict[str, Workflow] = {}
        self._loaded = False

    async def create(self, name: str, description: str) -> dict[str, Any]:
        """
        Creates a workflow from a natural-language description.
        ARIA automatically breaks the description down into concrete steps.
        """
        await self._ensure_loaded()

        from apps.core.tools.ai_client import AIModel, get_ai_client

        client = get_ai_client()

        resp = await client.complete(
            model=AIModel.STRATEGY,
            system=(
                "You are an automation architect. You convert descriptions into executable "
                "workflows. Respond ONLY with a JSON array of steps."
            ),
            user=(
                f"Automation: {description}\n\n"
                "Break it down into up to 6 steps using ONLY these ARIA tools:\n"
                "- web_search(query)  — search for information on the internet\n"
                "- deep_search(query, num_pages)  — deep research\n"
                "- fetch_url(url)  — read content from a specific URL\n"
                "- execute_code(code, language)  — execute Python/JS code\n"
                "- run_business_agent(agent, mission)  — agents: research/content/marketing/sales/developer/finance/ceo\n"
                "- generate_image(prompt)  — generate an image\n"
                "- create_presentation(title, topic, slide_count, template)  — presentation\n"
                "- create_social_content(topic, platforms, tone)  — content for social networks\n"
                "- publish_article(title, content, tags, platforms)  — publish an article\n"
                "- send_email(subject, body, to)  — send an email\n"
                "- deep_think(question, depth, context)  — deep analysis\n"
                "- search_knowledge(query)  — search the internal knowledge base\n"
                "- run_crew(mission, crew)  — team of agents collaborating\n\n"
                "JSON format:\n"
                '[{"tool": "name", "args": {"param": "value"}, "description": "what this step does"}]\n'
                "Use {prev_output} in args to reference the previous step's output.\n"
                "ONLY the JSON array, no explanations."
            ),
        )

        content = resp.content if hasattr(resp, "content") else str(resp)
        steps = self._parse_steps(content)

        if not steps:
            # Fallback: single agent step
            steps = [
                WorkflowStep(
                    tool="run_business_agent",
                    args={"agent": "ceo", "mission": description},
                    description=description,
                )
            ]

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
        """Runs a workflow step by step. Each step's output feeds the next."""
        await self._ensure_loaded()
        wf = self._workflows.get(workflow_id)
        if not wf:
            return {"success": False, "error": f"Workflow '{workflow_id}' not found"}

        results = []
        prev_output = ""

        for i, step in enumerate(wf.steps):
            logger.info(
                "[Workflow:%s] Step %d/%d: %s", workflow_id, i + 1, len(wf.steps), step.tool
            )

            # Inject {prev_output} placeholder
            enriched_args = {}
            for k, v in step.args.items():
                enriched_args[k] = (
                    v.replace("{prev_output}", prev_output[:800]) if isinstance(v, str) else v
                )

            try:
                from apps.core.cognition.aria_mind import get_aria_mind

                obs, _ = await get_aria_mind()._execute_tool(step.tool, enriched_args)
                step.result = obs[:1500]
                prev_output = step.result
                results.append(
                    {
                        "step": i + 1,
                        "tool": step.tool,
                        "desc": step.description,
                        "success": True,
                        "output": step.result,
                    }
                )
            except Exception as exc:
                step.result = f"Error: {exc}"
                results.append(
                    {
                        "step": i + 1,
                        "tool": step.tool,
                        "desc": step.description,
                        "success": False,
                        "error": str(exc),
                    }
                )
                logger.warning("[Workflow:%s] Step %d error: %s", workflow_id, i + 1, exc)

        wf.last_run = datetime.now(UTC).isoformat()
        wf.run_count += 1
        await self._persist()

        return {
            "success": all(r["success"] for r in results) if results else False,
            "workflow_id": workflow_id,
            "name": wf.name,
            "steps_run": len(results),
            "results": results,
            "final_output": prev_output,
        }

    def list(self) -> list[dict]:
        return sorted(
            [w.to_dict() for w in self._workflows.values()],
            key=lambda w: w["created_at"],
            reverse=True,
        )

    def get(self, workflow_id: str) -> dict | None:
        wf = self._workflows.get(workflow_id)
        return wf.to_dict() if wf else None

    def delete(self, workflow_id: str) -> bool:
        if workflow_id in self._workflows:
            del self._workflows[workflow_id]
            return True
        return False

    # ── PRIVATE ───────────────────────────────────────────────────────────────

    def _parse_steps(self, text: str) -> list[WorkflowStep]:
        try:
            text = re.sub(r"^```[a-z]*\n?", "", text.strip(), flags=re.M)
            text = re.sub(r"\n?```$", "", text.strip())
            m = re.search(r"\[.*\]", text, re.DOTALL)
            if m:
                data = json.loads(m.group())
                return [
                    WorkflowStep(
                        tool=s.get("tool", "run_business_agent"),
                        args=s.get("args", {}),
                        description=s.get("description", ""),
                    )
                    for s in data
                    if isinstance(s, dict)
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
                    steps = [
                        WorkflowStep(
                            tool=s["tool"],
                            args=s.get("args", {}),
                            description=s.get("description", ""),
                        )
                        for s in wd.get("steps", [])
                    ]
                    self._workflows[wid] = Workflow(
                        id=wid,
                        name=wd["name"],
                        description=wd["description"],
                        steps=steps,
                        created_at=wd.get("created_at", ""),
                        last_run=wd.get("last_run"),
                        run_count=wd.get("run_count", 0),
                    )
                logger.info("[WorkflowEngine] Loaded %d workflows from Redis", len(self._workflows))
        except Exception:
            pass


_engine: WorkflowEngine | None = None


def get_workflow_engine() -> WorkflowEngine:
    global _engine
    if _engine is None:
        _engine = WorkflowEngine()
    return _engine
