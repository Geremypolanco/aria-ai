"""
human_resources_agent.py -- ARIA AI Agente de Capital Humano v1.

Gestiona recursos humanos reales en todos los sectores de la economia circular:
- Asignacion y seguimiento de tareas
- Monitoreo de rendimiento con KPIs
- Planes de capacitacion (contenido generado por ARIA)
- Integracion con APIs de RRHH/nomina externas
- Resolucion de conflictos y bienestar

Principio: NINGUNA funcion retorna datos simulados.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

from apps.core.agents.base_agent import BaseAgent
from apps.core.config import settings
from apps.core.tools.ai_client import AIModel

logger = logging.getLogger("aria.hr_agent")


class HumanResourcesAgent(BaseAgent):
    """Agente de gestion de capital humano para la economia circular."""

    def __init__(self, sector_id: str = "digital") -> None:
        super().__init__(
            name="hr_agent",
            description="Gestion de capital humano: tareas, rendimiento, nomina, capacitacion y bienestar",
            capabilities=[
                "task_assignment", "performance_tracking", "training_generation",
                "payroll_integration", "conflict_resolution", "hr_system",
                "supabase", "telegram",
            ],
            sector_id=sector_id,
        )

    async def _execute(self, context: dict[str, Any]) -> dict[str, Any]:
        mode = context.get("mode", "cycle")
        if mode == "assign_task":
            return await self.assign_task(
                context["employee_id"], context["task"], context.get("priority", 5)
            )
        if mode == "performance_review":
            return await self.run_performance_reviews()
        if mode == "training_plan":
            return await self.create_training_plan(context.get("employee_id"))
        if mode == "onboard":
            return await self.onboard_employee(context.get("employee_data", {}))
        return await self.run_hr_cycle()

    # -- CICLO COMPLETO --------------------------------------------------------

    async def run_hr_cycle(self) -> dict[str, Any]:
        """
        Ciclo de RRHH: revisar rendimiento, asignar tareas pendientes,
        detectar necesidades de capacitacion.
        """
        logger.info("[HRAgent] Iniciando ciclo de capital humano -- Sector: %s", self.sector_id)
        results: dict[str, Any] = {"agent": self.name, "sector": self.sector_id}

        employees = await self._get_active_employees()
        results["employees_reviewed"] = len(employees)

        tasks_assigned = 0
        trainings_created = 0
        for emp in employees:
            eid = emp.get("id")
            perf = emp.get("performance", {})
            if not emp.get("assigned_tasks"):
                task = await self._generate_task_for_employee(emp)
                if task:
                    await self.assign_task(eid, task, priority=5)
                    tasks_assigned += 1
            score = perf.get("score", 100)
            if score < 70:
                plan = await self.create_training_plan(eid)
                if plan.get("success"):
                    trainings_created += 1

        results["tasks_assigned"] = tasks_assigned
        results["trainings_created"] = trainings_created
        results["success"] = True
        return results

    # -- GESTION DE TAREAS -----------------------------------------------------

    async def assign_task(self, employee_id: str, task: dict, priority: int = 5) -> dict[str, Any]:
        """Asigna una tarea a un empleado y la registra en Supabase."""
        if not employee_id or not task:
            return {"success": False, "error": "employee_id y task son requeridos"}
        try:
            from apps.core.memory.supabase_client import get_db
            db = get_db()
            result = await db.assign_hr_task(employee_id, task, priority)
            await self._notify_employee(employee_id, task)
            logger.info("[HRAgent] Tarea asignada a %s: %s", employee_id, task.get("name", "N/A"))
            return {"success": True, "employee_id": employee_id, "task": task, "result": result}
        except Exception as exc:
            logger.error("[HRAgent] Error asignando tarea: %s", exc)
            return {"success": False, "error": str(exc)}

    # -- RENDIMIENTO -----------------------------------------------------------

    async def run_performance_reviews(self) -> dict[str, Any]:
        """Evalua el rendimiento de todos los empleados activos."""
        employees = await self._get_active_employees()
        reviews = []
        for emp in employees:
            review = await self._evaluate_employee(emp)
            reviews.append(review)
            try:
                from apps.core.memory.supabase_client import get_db
                db = get_db()
                await db.update_hr_performance(emp["id"], review)
            except Exception:
                pass
        return {"reviews": reviews, "total": len(reviews), "success": True}

    async def _evaluate_employee(self, employee: dict) -> dict[str, Any]:
        """Usa IA para evaluar el rendimiento de un empleado."""
        prompt = (
            "Evalua el rendimiento de este empleado para la economia circular de ARIA.\n"
            f"Datos: {employee}\n"
            f"Sector: {self.sector_id}\n\n"
            "Genera una evaluacion objetiva con: score (0-100), fortalezas, areas_de_mejora,\n"
            "recomendacion (mantener|capacitar|reasignar|promover), justificacion.\n"
            "Responde SOLO con JSON."
        )
        try:
            review = await self.ai_complete_json(prompt, model=AIModel.FAST)
            review["employee_id"] = employee.get("id")
            return review
        except Exception as exc:
            return {"employee_id": employee.get("id"), "error": str(exc), "score": 0}

    # -- CAPACITACION ----------------------------------------------------------

    async def create_training_plan(self, employee_id: Optional[str] = None) -> dict[str, Any]:
        """
        Genera un plan de capacitacion personalizado usando contenido de ARIA.
        Si employee_id es None, genera un plan generico para el sector.
        """
        employee = None
        if employee_id:
            try:
                from apps.core.memory.supabase_client import get_db
                db = get_db()
                employees = await db.get_hr_employees(sector_id=self.sector_id)
                employee = next((e for e in employees if e["id"] == employee_id), None)
            except Exception:
                pass

        context = f"Empleado: {employee}" if employee else f"Sector: {self.sector_id}"
        prompt = (
            "Crea un plan de capacitacion para la economia circular de ARIA.\n"
            f"{context}\n"
            f"Sector: {self.sector_id}\n\n"
            "El plan debe incluir modulos que ARIA puede generar como contenido digital.\n"
            "Responde SOLO con JSON:\n"
            '{"plan_name": "...", "duration_weeks": 4, "modules": ['
            '{"name": "...", "type": "ebook|video_script|quiz|workshop", '
            '"duration_hours": 2, "topics": ["..."], "aria_can_generate": true}], '
            '"expected_improvement_pct": 20}'
        )
        try:
            plan = await self.ai_complete_json(prompt, model=AIModel.STRATEGY)
            if employee_id:
                try:
                    from apps.core.memory.supabase_client import get_db
                    db = get_db()
                    await db.update_hr_training_plan(employee_id, plan)
                except Exception:
                    pass
            return {"success": True, "plan": plan, "employee_id": employee_id}
        except Exception as exc:
            return {"success": False, "error": str(exc)}

    # -- INCORPORACION --------------------------------------------------------

    async def onboard_employee(self, employee_data: dict) -> dict[str, Any]:
        """Registra un nuevo empleado en el sistema de RRHH de ARIA."""
        required = ["name", "role"]
        missing = [f for f in required if not employee_data.get(f)]
        if missing:
            return {"success": False, "error": f"Faltan campos: {missing}"}
        employee_data.setdefault("sector_id", self.sector_id)
        employee_data.setdefault("status", "active")
        try:
            from apps.core.memory.supabase_client import get_db
            db = get_db()
            result = await db.create_hr_employee(employee_data)
            if result:
                await self.create_training_plan(result.get("id"))
            logger.info("[HRAgent] Empleado incorporado: %s -- %s", employee_data["name"], employee_data["role"])
            return {"success": True, "employee": result}
        except Exception as exc:
            return {"success": False, "error": str(exc)}

    # -- INTEGRACION NOMINA ---------------------------------------------------

    async def process_payroll(self) -> dict[str, Any]:
        """
        Procesa nomina via API de RRHH externa (si esta configurada).
        Requiere aprobacion humana antes de ejecutar pagos.
        """
        if not settings.PAYROLL_API_KEY:
            return {
                "success": False,
                "error": "PAYROLL_API_KEY no configurado. Configura tu sistema de nomina.",
            }
        employees = await self._get_active_employees()
        total_payroll = sum(e.get("salary_usd", 0) for e in employees)
        return await self.execute_with_approval(
            action="Procesar nomina mensual",
            details=f"{len(employees)} empleados -- Total: ${total_payroll:.2f}",
            fn=lambda: self._run_payroll_api(employees),
            amount_usd=total_payroll,
        )

    async def _run_payroll_api(self, employees: list) -> dict[str, Any]:
        """Llama a la API de nomina externa."""
        import httpx
        url = settings.HR_SYSTEM_API_URL
        if not url:
            return {"success": False, "error": "HR_SYSTEM_API_URL no configurado"}
        results = []
        async with httpx.AsyncClient(timeout=30.0) as client:
            for emp in employees:
                try:
                    resp = await client.post(
                        f"{url}/payroll/process",
                        headers={"Authorization": f"Bearer {settings.HR_SYSTEM_API_KEY}"},
                        json={"employee_ref": emp.get("employee_ref"), "amount": emp.get("salary_usd", 0)},
                    )
                    results.append({"employee": emp.get("name"), "status": resp.status_code})
                except Exception as exc:
                    results.append({"employee": emp.get("name"), "error": str(exc)})
        return {"success": True, "payroll_results": results}

    # -- UTILIDADES -----------------------------------------------------------

    async def _get_active_employees(self) -> list[dict]:
        try:
            from apps.core.memory.supabase_client import get_db
            db = get_db()
            return await db.get_hr_employees(sector_id=self.sector_id)
        except Exception as exc:
            logger.warning("[HRAgent] No pudo obtener empleados: %s", exc)
            return []

    async def _generate_task_for_employee(self, employee: dict) -> Optional[dict]:
        prompt = (
            "Genera una tarea concreta y accionable para este empleado de ARIA.\n"
            f"Empleado: {employee}\n"
            f"Sector: {self.sector_id}\n\n"
            "La tarea debe ser completable en 1-8 horas y contribuir a la economia circular.\n"
            "Responde SOLO con JSON:\n"
            '{"name": "...", "description": "...", "estimated_hours": 2, '
            '"kpi": "...", "deadline_days": 3}'
        )
        try:
            return await self.ai_complete_json(prompt, model=AIModel.FAST)
        except Exception:
            return None

    async def _notify_employee(self, employee_id: str, task: dict) -> None:
        """Notifica asignacion de tarea via HR system si esta disponible."""
        if not settings.HR_SYSTEM_API_KEY or not settings.HR_SYSTEM_API_URL:
            return
        try:
            import httpx
            async with httpx.AsyncClient(timeout=10.0) as client:
                await client.post(
                    f"{settings.HR_SYSTEM_API_URL}/notifications/task",
                    headers={"Authorization": f"Bearer {settings.HR_SYSTEM_API_KEY}"},
                    json={"employee_id": employee_id, "task": task},
                )
        except Exception as exc:
            logger.debug("[HRAgent] Notificacion HR no enviada: %s", exc)
