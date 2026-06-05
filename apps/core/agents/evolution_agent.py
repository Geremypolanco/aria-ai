"""
evolution_agent.py — ARIA AI Self-Evolution Engine v4.

ARIA puede autonomamente:
  1. Leer y analizar su propio codigo completo via GitHub API
  2. Generar versiones mejoradas con Qwen2.5-Coder y pushear a GitHub
  3. Leer logs de produccion de Fly.io para detectar y corregir errores reales
  4. Descubrir e integrar nuevas APIs que amplian sus capacidades
  5. Mantener un score de calidad del sistema en tiempo real
  6. Aprender de sus propios errores y optimizar su ciclo autonomo
  7. Proponer mejoras a archivos protegidos (requiere aprobacion humana)

Principio: NINGUNA funcion retorna datos simulados.
Si no puede realizar una accion, lo dice explicitamente.
"""
from __future__ import annotations
import asyncio
import json
import logging
import re
from typing import Any
from apps.core.agents.base_agent import BaseAgent
from apps.core.tools.ai_client import AIModel

logger = logging.getLogger("aria.evolution_agent")


class EvolutionAgent(BaseAgent):
    def __init__(self) -> None:
        super().__init__(
            name="evolution_agent",
            description="Auto-evolucion: analiza codigo propio, corrige errores de produccion, integra APIs — ciclo infinito de mejora real",
            capabilities=[
                "code_analysis", "code_improvement", "self_modification",
                "api_discovery", "api_integration", "performance_optimization",
                "bug_detection", "bug_fixing", "feature_addition",
                "github", "production_log_analysis",
            ],
        )

    async def _execute(self, context: dict[str, Any]) -> dict[str, Any]:
        mode = context.get("mode", "full")
        max_files = context.get("max_files", 3)
        max_apis = context.get("max_apis", 1)
        mission = context.get("mission", "maximize autonomous digital revenue")
        notify = context.get("notify_telegram", True)

        results: dict[str, Any] = {
            "success": True,
            "agent": "evolution_agent",
            "mode": mode,
            "improvements": [],
            "new_apis": [],
            "system_score": 0,
            "lessons_learned": {},
        }

        from apps.core.tools.self_improvement import SelfImprovementEngine
        engine = SelfImprovementEngine()

        # Verificar disponibilidad real antes de ejecutar
        availability = engine.is_available()
        if not availability["github_read"]:
            return {
                "success": False,
                "error": "GITHUB_TOKEN no configurado — no puedo leer ni modificar mi propio codigo. "
                         "Configura GITHUB_TOKEN en los secrets de Fly.io.",
                "availability": availability,
            }

        try:
            # 1. Score del sistema (usa logs reales de Fly.io si FLY_API_TOKEN disponible)
            score_result = await engine.calculate_system_score()
            results["system_score"] = score_result.get("score", 0)
            results["system_grade"] = score_result.get("grade", "?")
            logger.info("[EvolutionAgent] System score: %d/100 (%s)", results["system_score"], results["system_grade"])

            # 2. Aprender de logs de produccion
            lessons = await self._learn_from_production_logs(engine)
            results["lessons_learned"] = lessons

            # 3. Auto-mejora de codigo (mode: full o improve_only)
            if mode in ("full", "improve_only"):
                logger.info("[EvolutionAgent] Iniciando auto-mejora de codigo...")
                improvements = await self._run_code_improvement(engine, max_files, lessons)
                results["improvements"] = improvements
                results["files_improved"] = sum(1 for r in improvements if r.get("success") and not r.get("skipped"))

            # 4. Descubrimiento de APIs (mode: full o discover_only)
            if mode in ("full", "discover_only"):
                logger.info("[EvolutionAgent] Descubriendo nuevas APIs...")
                api_results = await self._run_api_discovery(mission, max_apis)
                results["new_apis"] = api_results

            # 5. Analisis de arquitectura y propuesta de mejoras
            arch_analysis = await self._analyze_architecture()

            # 5b. Descubrimiento de herramientas HuggingFace para gaps
            logger.info("[EvolutionAgent] Buscando herramientas HF para capacidades faltantes...")
            hf_discoveries = await self._discover_hf_tools_for_gaps()
            results["hf_discoveries"] = hf_discoveries
            if hf_discoveries.get("discoveries"):
                n_found = sum(1 for d in hf_discoveries["discoveries"] if d.get("can_use_now"))
                logger.info("[EvolutionAgent] HF: %d herramientas disponibles para gaps detectados", n_found)
            results["architecture_analysis"] = arch_analysis

            # 6. Notificacion Telegram con resumen completo
            if notify:
                await self._report_evolution_results(results)

            results["success"] = True

        except Exception as exc:
            logger.error("[EvolutionAgent] Error en ciclo de evolucion: %s", exc, exc_info=True)
            results["success"] = False
            results["error"] = str(exc)

        return results

    # ══════════════════════════════════════════════════════════════
    # LECTURA DE LOGS DE PRODUCCION
    # ══════════════════════════════════════════════════════════════

    async def _learn_from_production_logs(self, engine) -> dict[str, Any]:
        """Lee logs reales de Fly.io y extrae lecciones para la auto-mejora."""
        logs_result = await engine.read_production_logs(lines=150)
        if not logs_result["success"]:
            logger.warning("[EvolutionAgent] Logs no disponibles: %s", logs_result["error"])
            return {
                "available": False,
                "reason": logs_result["error"],
                "recommendations": [],
            }

        analysis = await engine.analyze_logs_for_errors(logs_result["logs"])
        if not analysis["success"]:
            return {"available": True, "analysis_failed": True, "recommendations": []}

        data = analysis["analysis"]
        critical = data.get("critical_errors", [])
        if critical:
            logger.error("[EvolutionAgent] Errores criticos en produccion: %s", critical)
            await self._send_telegram(
                f"🚨 <b>Errores criticos detectados en produccion</b>\n\n"
                + "\n".join(f"• {e}" for e in critical[:5])
            )

        return {
            "available": True,
            "critical_errors": critical,
            "errors_found": len(data.get("errors", [])),
            "recommendations": data.get("recommendations", []),
            "performance_issues": data.get("performance_issues", []),
        }

    # ══════════════════════════════════════════════════════════════
    # AUTO-MEJORA DE CODIGO
    # ══════════════════════════════════════════════════════════════

    async def _run_code_improvement(
        self,
        engine,
        max_files: int,
        lessons: dict,
    ) -> list[dict[str, Any]]:
        """
        Selecciona los archivos mas criticos y los mejora autonomamente.
        Prioriza archivos con errores reportados en los logs de produccion.
        """
        # Obtener lista real de archivos modificables de GitHub
        all_files = await engine.list_all_python_files("apps/core")
        if not all_files:
            return [{"success": False, "error": "No se pudieron listar archivos de GitHub"}]

        # Priorizar archivos mencionados en errores de logs
        critical_files: list[str] = []
        error_text = json.dumps(lessons.get("critical_errors", []) + lessons.get("performance_issues", []))
        for f in engine.MODIFIABLE_FILES:
            filename = f.split("/")[-1].replace(".py", "")
            if filename in error_text.lower():
                critical_files.append(f)

        # Completar hasta max_files con el resto de MODIFIABLE_FILES
        candidates = critical_files.copy()
        for f in engine.MODIFIABLE_FILES:
            if f not in candidates and len(candidates) < max_files:
                candidates.append(f)

        candidates = candidates[:max_files]
        logger.info("[EvolutionAgent] Archivos candidatos a mejora: %s", candidates)

        # Mejorar secuencialmente (respeta rate limit del CI/CD)
        results = []
        for file_path in candidates:
            result = await engine.improve_file(
                file_path,
                log_lessons=lessons if lessons.get("available") else None,
            )
            results.append(result)
            if result.get("success") and not result.get("skipped"):
                logger.info(
                    "[EvolutionAgent] Mejorado: %s (commit: %s, +%d lineas)",
                    file_path,
                    result.get("commit_sha", "?"),
                    result.get("lines_delta", 0),
                )
            elif result.get("skipped"):
                logger.info("[EvolutionAgent] Saltado: %s — %s", file_path, result.get("reason", ""))
            else:
                logger.warning("[EvolutionAgent] Fallo: %s — %s", file_path, result.get("error", ""))
            # Pausa entre pushes para no saturar CI/CD
            await asyncio.sleep(2)

        return results

    # ══════════════════════════════════════════════════════════════
    # DESCUBRIMIENTO E INTEGRACION DE APIs
    # ══════════════════════════════════════════════════════════════

    async def _run_api_discovery(self, mission: str, max_apis: int) -> list[dict[str, Any]]:
        """
        Descubre APIs nuevas y genera codigo de integracion real.
        Solo descubre APIs gratuitas — no gasta dinero sin aprobacion.
        """
        try:
            from apps.core.tools.api_discovery import APIDiscovery
            discovery = APIDiscovery()
            candidates = await discovery.find_relevant_apis(mission, limit=max_apis * 3)
            if not candidates:
                return [{"success": False, "error": "No se encontraron APIs candidatas"}]

            results = []
            for api in candidates[:max_apis]:
                integration_result = await discovery.generate_integration_code(api)
                if integration_result.get("success"):
                    # Solo pushear si hay codigo valido generado
                    push_result = await discovery.add_integration_to_codebase(
                        api, integration_result["code"]
                    )
                    results.append({
                        "success": push_result.get("success", False),
                        "api": api.get("name"),
                        "category": api.get("category"),
                        "benefit": api.get("benefit"),
                        "commit_sha": push_result.get("commit_sha"),
                        "error": push_result.get("error"),
                    })
                else:
                    results.append({
                        "success": False,
                        "api": api.get("name"),
                        "error": integration_result.get("error", "No se pudo generar codigo de integracion"),
                    })
            return results
        except Exception as exc:
            logger.error("[EvolutionAgent] api_discovery error: %s", exc)
            return [{"success": False, "error": str(exc)}]

    # ══════════════════════════════════════════════════════════════
    # ANALISIS DE ARQUITECTURA
    # ══════════════════════════════════════════════════════════════


    async def _discover_hf_tools_for_gaps(self) -> dict:
        """
        ARIA identifica capacidades que le faltan y busca en HuggingFace Hub
        los mejores modelos para cubrirlas. Integra lo que encuentra.

        Flujo:
          1. Revisa qué APIs no están configuradas (check_capabilities)
          2. Para cada gap, busca modelos HF que puedan suplirla
          3. Reporta hallazgos y actualiza el uso de HF en el codebase
        """
        from apps.core.tools.hf_discovery import get_hf
        hf = get_hf()
        hf_report = await hf.capability_report()
        if not hf_report.get("available"):
            return {
                "success": False,
                "error": hf_report.get("error", "HF_TOKEN no configurado"),
            }

        caps = await self.check_capabilities()
        gaps = [k for k, v in caps.items() if not v]
        logger.info("[EvolutionAgent] Gaps detectados: %s", gaps)

        # Mapeo de capacidades ARIA -> tareas HF
        gap_to_hf_task = {
            "image_generation": "image-generation",
            "canva": "image-generation",
            "audio": "automatic-speech-recognition",
            "translation": "translation",
            "sentiment": "sentiment-analysis",
            "classification": "zero-shot-classification",
            "ocr": "image-to-text",
            "speech": "text-to-speech",
            "embeddings": "feature-extraction",
            "summarization": "summarization",
        }

        discoveries = []
        for gap in gaps[:5]:  # máximo 5 búsquedas por ciclo
            gap_lower = gap.lower()
            matched_task = next(
                (task for key, task in gap_to_hf_task.items() if key in gap_lower),
                None,
            )
            if not matched_task:
                # Búsqueda libre por keyword
                result = await hf.find_tool_for_capability(gap_lower)
            else:
                result = await hf.search_models_for_task(matched_task, limit=3)

            if result.get("success"):
                discoveries.append({
                    "gap": gap,
                    "hf_task": matched_task or "auto",
                    "models_found": result.get("models", result.get("hub_models", []))[:2],
                    "can_use_now": True,
                    "how_to_use": f"from apps.core.tools.hf_discovery import get_hf; hf = get_hf(); await hf.discover_and_run('{matched_task or "text-generation"}',...)",
                })
                logger.info("[EvolutionAgent] HF tool para '%s': %s", gap, matched_task)
            else:
                discoveries.append({"gap": gap, "error": result.get("error", "no encontrado")})

        return {
            "success": True,
            "gaps_analyzed": len(gaps),
            "discoveries": discoveries,
            "hf_tasks_available": hf_report.get("tasks_count", 0),
            "note": "ARIA puede usar hf_discovery.discover_and_run() para cualquier tarea de ML sin API key adicional",
        }


    async def _analyze_architecture(self) -> dict[str, Any]:
        """
        Analiza la arquitectura completa del sistema con IA.
        Lee la lista real de archivos de GitHub para el analisis.
        """
        from apps.core.tools.self_improvement import SelfImprovementEngine
        engine = SelfImprovementEngine()

        all_files = await engine.list_all_python_files("apps/core")
        if not all_files:
            return {"success": False, "error": "No se pudo leer estructura de archivos"}

        file_summary = "\n".join(all_files)
        analysis = await self.think(
            system="Arquitecto de sistemas IA. Responde SOLO con JSON valido.",
            user=(
                f"Analiza esta estructura de archivos de ARIA AI y devuelve JSON con:\n"
                '{"missing_modules": [str], "architectural_risks": [str], '
                '"scalability_recommendations": [str], "next_features_to_add": [str], '
                '"critical_path": [str]}\n\n'
                f"ARCHIVOS ACTUALES:\n{file_summary}"
            ),
            model=AIModel.STRATEGY,
            json_mode=True,
        )

        if not analysis:
            return {"success": False, "error": "IA no disponible para analisis de arquitectura"}

        try:
            if isinstance(analysis, str):
                match = re.search(r"\{.*\}", analysis, re.DOTALL)
                data = json.loads(match.group()) if match else {}
            else:
                data = analysis
            return {"success": True, "analysis": data, "total_files": len(all_files)}
        except Exception:
            return {"success": False, "error": "No se pudo parsear analisis de arquitectura"}

    # ══════════════════════════════════════════════════════════════
    # REPORTE TELEGRAM
    # ══════════════════════════════════════════════════════════════

    async def _report_evolution_results(self, results: dict[str, Any]) -> None:
        """Envia resumen del ciclo de evolucion via Telegram."""
        improvements = results.get("improvements", [])
        successful = [r for r in improvements if r.get("success") and not r.get("skipped")]
        failed = [r for r in improvements if not r.get("success")]
        skipped = [r for r in improvements if r.get("skipped")]

        new_apis = [a for a in results.get("new_apis", []) if a.get("success")]
        score = results.get("system_score", 0)
        grade = results.get("system_grade", "?")
        lessons = results.get("lessons_learned", {})

        lines = [f"🧬 <b>Ciclo de Auto-Evolucion</b>"]
        lines.append(f"📊 Score del sistema: <b>{score}/100</b> (Grado {grade})")

        if lessons.get("critical_errors"):
            lines.append(f"\n🚨 <b>Errores criticos encontrados:</b> {len(lessons['critical_errors'])}")

        if successful:
            lines.append(f"\n✅ <b>Archivos mejorados ({len(successful)}):</b>")
            for r in successful[:3]:
                lines.append(
                    f"  • {r['file'].split('/')[-1]} "
                    f"[commit: {r.get('commit_sha', '?')}] "
                    f"(+{r.get('lines_delta', 0)} lineas)"
                )

        if new_apis:
            lines.append(f"\n🔌 <b>Nuevas APIs integradas ({len(new_apis)}):</b>")
            for a in new_apis[:2]:
                lines.append(f"  • {a.get('api', '?')} — {a.get('benefit', '')[:50]}")

        if skipped:
            lines.append(f"\n⏭️ Archivos ya optimos: {len(skipped)}")
        if failed:
            lines.append(f"\n❌ Fallos: {len(failed)}")

        arch = results.get("architecture_analysis", {})
        if arch.get("success") and arch.get("analysis", {}).get("next_features_to_add"):
            next_f = arch["analysis"]["next_features_to_add"][:2]
            lines.append(f"\n💡 <b>Proximas mejoras sugeridas:</b>")
            for f in next_f:
                lines.append(f"  • {f}")

        await self._send_telegram("\n".join(lines))
