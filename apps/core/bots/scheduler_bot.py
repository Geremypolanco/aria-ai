"""
scheduler_bot.py — Bot especializado en planificación inteligente de tareas.
Aria NO planifica la agenda de los bots. Este bot lo hace solo.
"""
from __future__ import annotations
import asyncio, logging, uuid
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional
logger = logging.getLogger("aria.bots.scheduler")
PRIORITY_LEVELS = {"critical": 0, "high": 1, "medium": 2, "low": 3}

class Task:
    def __init__(self, name: str, fn: Callable, priority: str = "medium",
                 description: str = "", tags: Optional[List[str]] = None):
        self.id = str(uuid.uuid4())[:8]
        self.name = name
        self.fn = fn
        self.priority = priority
        self.description = description
        self.tags = tags or []
        self.created_at = datetime.now(timezone.utc).isoformat()
        self.completed_at: Optional[str] = None
        self.status = "pending"
        self.result: Optional[Dict] = None
        self.retries = 0
        self.max_retries = 2

class SchedulerBot:
    def __init__(self):
        self._queue: List[Task] = []
        self._completed: List[Task] = []
        self._running: Dict[str, Task] = {}
        self._max_concurrent = 3
        self._executed_count = 0
        self._failed_count = 0

    def add_task(self, name: str, fn: Callable, priority: str = "medium",
                 description: str = "", tags: Optional[List[str]] = None) -> str:
        task = Task(name=name, fn=fn, priority=priority, description=description, tags=tags)
        self._queue.append(task)
        self._queue.sort(key=lambda t: PRIORITY_LEVELS.get(t.priority, 2))
        logger.info("[SchedulerBot] Tarea añadida: %s [%s]", name, priority)
        return task.id

    def remove_task(self, task_id: str) -> bool:
        before = len(self._queue)
        self._queue = [t for t in self._queue if t.id != task_id]
        return len(self._queue) < before

    async def run_next(self) -> Optional[Dict]:
        if not self._queue:
            return None
        if len(self._running) >= self._max_concurrent:
            return {"skipped": True, "reason": "Max concurrent tasks reached"}
        task = self._queue.pop(0)
        task.status = "running"
        self._running[task.id] = task
        try:
            result = await asyncio.wait_for(task.fn(), timeout=120.0)
            task.result = result if isinstance(result, dict) else {"result": result}
            task.status = "completed"
            task.completed_at = datetime.now(timezone.utc).isoformat()
            self._executed_count += 1
        except asyncio.TimeoutError:
            task.status = "timeout"
            task.result = {"error": "Timeout después de 120s"}
            self._failed_count += 1
        except Exception as e:
            task.status = "failed"
            task.result = {"error": str(e)}
            self._failed_count += 1
            if task.retries < task.max_retries:
                task.retries += 1
                task.status = "pending"
                self._queue.insert(0, task)
            else:
                logger.error("[SchedulerBot] Fallida: %s — %s", task.name, e)
        self._running.pop(task.id, None)
        self._completed.append(task)
        if len(self._completed) > 200:
            self._completed = self._completed[-100:]
        return {"task_id": task.id, "name": task.name, "status": task.status, "result": task.result}

    async def run_all_pending(self) -> Dict:
        results = []
        while self._queue:
            batch = []
            available_slots = self._max_concurrent - len(self._running)
            for _ in range(min(available_slots, len(self._queue))):
                if self._queue:
                    batch.append(self.run_next())
            if batch:
                batch_results = await asyncio.gather(*batch, return_exceptions=True)
                results.extend([r for r in batch_results if isinstance(r, dict)])
            else:
                await asyncio.sleep(0.1)
        return {"success": True, "executed": len(results), "results": results}

    async def plan_day(self) -> Dict:
        try:
            from apps.core.tools.ai_client import AIModel, get_ai_client
            ai = get_ai_client()
            pending_names = [t.name for t in self._queue[:10]]
            hour = datetime.now(timezone.utc).hour - 4
            response = await ai.complete(
                system="Planificador de tareas IA. Sugiere el orden óptimo en 4-6 oraciones, directo.",
                user=f"Hora ET: {hour}:00\nTareas:\n" + "\n".join(f"- {n}" for n in pending_names),
                model=AIModel.FAST, max_tokens=200, agent_name="scheduler_bot_plan",
            )
            return {"success": True, "pending_tasks": len(self._queue),
                    "plan": response.content.strip() if response.success else "Ejecutar en orden de prioridad."}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def status(self) -> Dict:
        return {"bot": "SchedulerBot", "pending": len(self._queue), "running": len(self._running),
                "completed": self._executed_count, "failed": self._failed_count,
                "queue": [{"id": t.id, "name": t.name, "priority": t.priority} for t in self._queue[:5]]}

_instance: Optional[SchedulerBot] = None
def get_scheduler_bot() -> SchedulerBot:
    global _instance
    if _instance is None:
        _instance = SchedulerBot()
    return _instance
