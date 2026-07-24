"""
evolution_agent.py — ARIA AI Self-Evolution Engine v4.

ARIA can autonomously:
  1. Read and analyze its own complete codebase via the GitHub API
  2. Generate improved versions with Qwen2.5-Coder and push them to GitHub
  3. Read Fly.io production logs to detect and fix real errors
  4. Discover and integrate new APIs that expand its capabilities
  5. Maintain a real-time system quality score
  6. Learn from its own mistakes and optimize its autonomous cycle
  7. Propose improvements to protected files (requires human approval)

Principle: NO function returns simulated data.
If it can't perform an action, it says so explicitly.
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
            name="evolution",
            description="Self-evolution: analyzes its own code, fixes production errors, integrates APIs — an infinite cycle of real improvement",
            capabilities=[
                "code_analysis",
                "code_improvement",
                "self_modification",
                "api_discovery",
                "api_integration",
                "performance_optimization",
                "bug_detection",
                "bug_fixing",
                "feature_addition",
                "github",
                "production_log_analysis",
            ],
        )

    async def _execute(self, context: dict[str, Any]) -> dict[str, Any]:
        mode = context.get("mode", "full")
        max_files = context.get("max_files", 3)
        max_apis = context.get("max_apis", 1)
        mission = context.get("mission", "maximize autonomous digital revenue")
        notify = context.get("notify_telegram", True)

        # Feature-creation mode — proactively generates new capabilities
        if mode == "create_feature":
            return await self._create_new_feature(mission=mission, context=context, notify=notify)

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

        # Verify real availability before running
        availability = engine.is_available()
        if not availability["github_read"]:
            return {
                "success": False,
                "error": "GITHUB_TOKEN not configured — I can't read or modify my own code. "
                "Set GITHUB_TOKEN in Fly.io secrets.",
                "availability": availability,
            }

        try:
            # 1. System score (uses real Fly.io logs if FLY_API_TOKEN is available)
            score_result = await engine.calculate_system_score()
            results["system_score"] = score_result.get("score", 0)
            results["system_grade"] = score_result.get("grade", "?")
            logger.info(
                "[EvolutionAgent] System score: %d/100 (%s)",
                results["system_score"],
                results["system_grade"],
            )

            # 2. Learn from production logs
            lessons = await self._learn_from_production_logs(engine)
            results["lessons_learned"] = lessons

            # 3. Self-improve code (mode: full or improve_only)
            if mode in ("full", "improve_only"):
                logger.info("[EvolutionAgent] Starting code self-improvement...")
                improvements = await self._run_code_improvement(engine, max_files, lessons)
                results["improvements"] = improvements
                results["files_improved"] = sum(
                    1 for r in improvements if r.get("success") and not r.get("skipped")
                )

            # 4. API discovery (mode: full or discover_only)
            if mode in ("full", "discover_only"):
                logger.info("[EvolutionAgent] Discovering new APIs...")
                api_results = await self._run_api_discovery(mission, max_apis)
                results["new_apis"] = api_results

            # 5. Architecture analysis and improvement proposals
            arch_analysis = await self._analyze_architecture()

            # 5b. Discover HuggingFace tools for gaps
            logger.info("[EvolutionAgent] Looking for HF tools for missing capabilities...")
            hf_discoveries = await self._discover_hf_tools_for_gaps()
            results["hf_discoveries"] = hf_discoveries
            if hf_discoveries.get("discoveries"):
                n_found = sum(1 for d in hf_discoveries["discoveries"] if d.get("can_use_now"))
                logger.info("[EvolutionAgent] HF: %d tools available for detected gaps", n_found)
            results["architecture_analysis"] = arch_analysis

            # 6. Telegram notification with the full summary
            if notify:
                await self._report_evolution_results(results)

            results["success"] = True

        except Exception as exc:
            logger.error("[EvolutionAgent] Error in evolution cycle: %s", exc, exc_info=True)
            results["success"] = False
            results["error"] = str(exc)

        return results

    # ══════════════════════════════════════════════════════════════
    # PROACTIVE CREATION OF NEW FEATURES
    # ══════════════════════════════════════════════════════════════

    async def _create_new_feature(self, mission: str, context: dict, notify: bool = True) -> dict:
        """
        Generates and pushes new features based on gap and market analysis.
        Trigger with mode='create_feature' from the scheduler or the orchestrator.
        """
        from apps.core.tools.self_improvement import SelfImprovementEngine

        engine = SelfImprovementEngine()
        results: dict = {
            "success": False,
            "agent": "evolution_agent",
            "mode": "create_feature",
            "features_created": [],
            "features_proposed": [],
        }
        caps = await self.check_capabilities()
        gaps = [k for k, v in caps.items() if not v]
        logger.info("[EvolutionAgent] Gaps for feature creation: %s", gaps)
        proposals = await self._propose_features_with_ai(gaps=gaps, mission=mission)
        results["features_proposed"] = proposals
        if not proposals:
            results["error"] = "No feature proposals were generated"
            return results
        top = proposals[0]
        logger.info("[EvolutionAgent] Implementing feature: %s", top.get("name"))
        impl = await self._implement_feature_code(engine, top)
        results["features_created"].append(impl)
        results["success"] = impl.get("success", False)
        if notify:
            await self._notify_feature_result(results, top)
        return results

    async def _propose_features_with_ai(self, gaps: list, mission: str) -> list:
        """Proposes high economic-impact features using strategic AI."""
        try:
            gaps_text = ", ".join(gaps[:8]) or "no critical gaps"
            analysis = await self.think(
                system=(
                    "Architect of an autonomous monetization AI. "
                    "You propose real, implementable Python features. "
                    "Respond ONLY with a valid JSON array."
                ),
                user=(
                    f"Mission: {mission}\nGaps: {gaps_text}\n\n"
                    "Propose 3 Python features for ARIA AI.\n"
                    'JSON: [{"name": str, "description": str, "file_to_create": "apps/core/tools/xxx.py",'
                    '"impact_usd_monthly": int, "implementation_hint": str, "priority": int}]\n'
                    "Criteria: real, does not duplicate existing ones, measurable economic impact."
                ),
                model=AIModel.STRATEGY,
                json_mode=True,
            )
            if not analysis:
                return []
            data = analysis
            if isinstance(data, str):
                import re as _re

                m = _re.search(r"\[.*\]", data, _re.DOTALL)
                data = json.loads(m.group()) if m else []
            if isinstance(data, list):
                return sorted(data, key=lambda x: x.get("priority", 99))[:3]
        except Exception as exc:
            logger.error("[EvolutionAgent] propose_features error: %s", exc)
        return []

    async def _implement_feature_code(self, engine, proposal: dict) -> dict:
        """Generates code with AI, validates syntax, and pushes to GitHub."""
        import ast
        import re

        name = proposal.get("name", "Feature")
        description = proposal.get("description", "")
        file_path = proposal.get("file_to_create", "")
        hint = proposal.get("implementation_hint", "")
        if not file_path:
            slug = re.sub(r"[^a-z0-9]", "_", name.lower()).strip("_")
            file_path = f"apps/core/tools/{slug}.py"
        try:
            from apps.core.tools.ai_client import AIModel, get_ai_client

            ai = get_ai_client()
            if not ai:
                return {"success": False, "error": "AI not available", "feature": name}
            resp = await ai.complete(
                system="Senior Python developer. Generate complete modules. Python code only, no fences.",
                user=(
                    f"Feature: {name}\nDescription: {description}\nHint: {hint}\n\n"
                    "Requirements: main class with async execute(**kwargs)->dict, "
                    "is_available()->bool, from apps.core.config import settings, "
                    "explicit errors (never simulate), minimum 40 lines, docstring."
                ),
                model=AIModel.CODE,
                max_tokens=3000,
            )
            if not resp or not resp.success:
                return {"success": False, "error": "AI did not generate code", "feature": name}
            code = resp.content.strip()
            # Strip markdown fences
            lines = code.split("\n")
            if lines and lines[0].strip().startswith("```"):
                lines = lines[1:]
            code = "\n".join(lines).rstrip("`").strip()
            try:
                ast.parse(code)
            except SyntaxError as se:
                return {"success": False, "error": f"Invalid syntax: {se}", "feature": name}
            if len(code.splitlines()) < 20:
                return {"success": False, "error": "Code too short", "feature": name}
            push = await engine.push_file(
                file_path=file_path,
                content=code,
                commit_message=f"feat: {name}\n\n{description[:200]}\n\nGenerated by ARIA EvolutionAgent.",
            )
            return {
                "success": push.get("success", False),
                "feature": name,
                "file": file_path,
                "commit_sha": push.get("commit_sha"),
                "impact_usd_monthly": proposal.get("impact_usd_monthly", 0),
                "error": push.get("error"),
            }
        except Exception as exc:
            logger.error("[EvolutionAgent] implement_feature_code error: %s", exc)
            return {"success": False, "error": str(exc), "feature": name}

    async def _notify_feature_result(self, results: dict, top: dict) -> None:
        """Notifies via Telegram of the created feature and its estimated impact."""
        created = [f for f in results.get("features_created", []) if f.get("success")]
        proposed = results.get("features_proposed", [])
        name = top.get("name", "?")
        impact = top.get("impact_usd_monthly", 0)
        lines = [f"Feature Creation: {name}", f"Estimated impact: {impact} USD/month"]
        if created:
            lines.append("Implemented: " + ", ".join(f["feature"] for f in created))
        if len(proposed) > 1:
            lines.append("Next: " + proposed[1].get("name", "?"))
        await self._send_telegram("\n".join(lines))

    # ══════════════════════════════════════════════════════════════
    # READING PRODUCTION LOGS
    # ══════════════════════════════════════════════════════════════

    async def _learn_from_production_logs(self, engine) -> dict[str, Any]:
        """Reads real Fly.io logs and extracts lessons for self-improvement."""
        logs_result = await engine.read_production_logs(lines=150)
        if not logs_result["success"]:
            logger.warning("[EvolutionAgent] Logs not available: %s", logs_result["error"])
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
            logger.error("[EvolutionAgent] Critical errors in production: %s", critical)
            await self._send_telegram(
                "🚨 <b>Critical errors detected in production</b>\n\n"
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
    # CODE SELF-IMPROVEMENT
    # ══════════════════════════════════════════════════════════════

    async def _run_code_improvement(
        self,
        engine,
        max_files: int,
        lessons: dict,
    ) -> list[dict[str, Any]]:
        """
        Selects the most critical files and improves them autonomously.
        Prioritizes files with errors reported in the production logs.
        """
        # Get the real list of modifiable files from GitHub
        all_files = await engine.list_all_python_files("apps/core")
        if not all_files:
            return [{"success": False, "error": "Could not list files from GitHub"}]

        # Prioritize files mentioned in log errors
        critical_files: list[str] = []
        error_text = json.dumps(
            lessons.get("critical_errors", []) + lessons.get("performance_issues", [])
        )
        for f in engine.MODIFIABLE_FILES:
            filename = f.split("/")[-1].replace(".py", "")
            if filename in error_text.lower():
                critical_files.append(f)

        # Fill up to max_files with the rest of MODIFIABLE_FILES
        candidates = critical_files.copy()
        for f in engine.MODIFIABLE_FILES:
            if f not in candidates and len(candidates) < max_files:
                candidates.append(f)

        candidates = candidates[:max_files]
        logger.info("[EvolutionAgent] Candidate files for improvement: %s", candidates)

        # Improve sequentially (respects CI/CD rate limit)
        results = []
        for file_path in candidates:
            result = await engine.improve_file(
                file_path,
                log_lessons=lessons if lessons.get("available") else None,
            )
            results.append(result)
            if result.get("success") and not result.get("skipped"):
                logger.info(
                    "[EvolutionAgent] Improved: %s (commit: %s, +%d lines)",
                    file_path,
                    result.get("commit_sha", "?"),
                    result.get("lines_delta", 0),
                )
            elif result.get("skipped"):
                logger.info(
                    "[EvolutionAgent] Skipped: %s — %s", file_path, result.get("reason", "")
                )
            else:
                logger.warning(
                    "[EvolutionAgent] Failed: %s — %s", file_path, result.get("error", "")
                )
            # Pause between pushes to avoid overloading CI/CD
            await asyncio.sleep(2)

        return results

    # ══════════════════════════════════════════════════════════════
    # API DISCOVERY AND INTEGRATION
    # ══════════════════════════════════════════════════════════════

    async def _run_api_discovery(self, mission: str, max_apis: int) -> list[dict[str, Any]]:
        """
        Discovers new APIs and generates real integration code.
        Only discovers free APIs — never spends money without approval.
        """
        try:
            from apps.core.tools.api_discovery import APIDiscovery

            discovery = APIDiscovery()
            candidates = await discovery.find_relevant_apis(mission, limit=max_apis * 3)
            if not candidates:
                return [{"success": False, "error": "No candidate APIs found"}]

            results = []
            for api in candidates[:max_apis]:
                integration_result = await discovery.generate_integration_code(api)
                if integration_result.get("success"):
                    # Only push if valid code was generated
                    push_result = await discovery.add_integration_to_codebase(
                        api, integration_result["code"]
                    )
                    results.append(
                        {
                            "success": push_result.get("success", False),
                            "api": api.get("name"),
                            "category": api.get("category"),
                            "benefit": api.get("benefit"),
                            "commit_sha": push_result.get("commit_sha"),
                            "error": push_result.get("error"),
                        }
                    )
                else:
                    results.append(
                        {
                            "success": False,
                            "api": api.get("name"),
                            "error": integration_result.get(
                                "error", "Could not generate integration code"
                            ),
                        }
                    )
            return results
        except Exception as exc:
            logger.error("[EvolutionAgent] api_discovery error: %s", exc)
            return [{"success": False, "error": str(exc)}]

    # ══════════════════════════════════════════════════════════════
    # ARCHITECTURE ANALYSIS
    # ══════════════════════════════════════════════════════════════

    async def _discover_hf_tools_for_gaps(self) -> dict:
        """
        ARIA identifies capabilities it's missing and searches HuggingFace Hub
        for the best models to cover them. Integrates what it finds.

        Flow:
          1. Checks which APIs are not configured (check_capabilities)
          2. For each gap, searches for HF models that could fill it
          3. Reports findings and updates HF usage in the codebase
        """
        from apps.core.tools.hf_discovery import get_hf

        hf = get_hf()
        hf_report = await hf.capability_report()
        if not hf_report.get("available"):
            return {
                "success": False,
                "error": hf_report.get("error", "HF_TOKEN not configured"),
            }

        caps = await self.check_capabilities()
        gaps = [k for k, v in caps.items() if not v]
        logger.info("[EvolutionAgent] Detected gaps: %s", gaps)

        # ARIA capability -> HF task mapping
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
        for gap in gaps[:5]:  # max 5 searches per cycle
            gap_lower = gap.lower()
            matched_task = next(
                (task for key, task in gap_to_hf_task.items() if key in gap_lower),
                None,
            )
            if not matched_task:
                # Free-form keyword search
                result = await hf.find_tool_for_capability(gap_lower)
            else:
                result = await hf.search_models_for_task(matched_task, limit=3)

            if result.get("success"):
                discoveries.append(
                    {
                        "gap": gap,
                        "hf_task": matched_task or "auto",
                        "models_found": result.get("models", result.get("hub_models", []))[:2],
                        "can_use_now": True,
                        "how_to_use": f"from apps.core.tools.hf_discovery import get_hf; hf = get_hf(); await hf.discover_and_run('{matched_task or 'text-generation'}',...)",
                    }
                )
                logger.info("[EvolutionAgent] HF tool for '%s': %s", gap, matched_task)
            else:
                discoveries.append({"gap": gap, "error": result.get("error", "not found")})

        return {
            "success": True,
            "gaps_analyzed": len(gaps),
            "discoveries": discoveries,
            "hf_tasks_available": hf_report.get("tasks_count", 0),
            "note": "ARIA can use hf_discovery.discover_and_run() for any ML task without an additional API key",
        }

    async def _analyze_architecture(self) -> dict[str, Any]:
        """
        Analyzes the system's complete architecture with AI.
        Reads the real file list from GitHub for the analysis.
        """
        from apps.core.tools.self_improvement import SelfImprovementEngine

        engine = SelfImprovementEngine()

        all_files = await engine.list_all_python_files("apps/core")
        if not all_files:
            return {"success": False, "error": "Could not read file structure"}

        file_summary = "\n".join(all_files)
        analysis = await self.think(
            system="AI systems architect. Respond ONLY with valid JSON.",
            user=(
                f"Analyze this ARIA AI file structure and return JSON with:\n"
                '{"missing_modules": [str], "architectural_risks": [str], '
                '"scalability_recommendations": [str], "next_features_to_add": [str], '
                '"critical_path": [str]}\n\n'
                f"CURRENT FILES:\n{file_summary}"
            ),
            model=AIModel.STRATEGY,
            json_mode=True,
        )

        if not analysis:
            return {"success": False, "error": "AI not available for architecture analysis"}

        try:
            if isinstance(analysis, str):
                match = re.search(r"\{.*\}", analysis, re.DOTALL)
                data = json.loads(match.group()) if match else {}
            else:
                data = analysis
            return {"success": True, "analysis": data, "total_files": len(all_files)}
        except Exception:
            return {"success": False, "error": "Could not parse architecture analysis"}

    # ══════════════════════════════════════════════════════════════
    # TELEGRAM REPORT
    # ══════════════════════════════════════════════════════════════

    async def _report_evolution_results(self, results: dict[str, Any]) -> None:
        """Sends a summary of the evolution cycle via Telegram."""
        improvements = results.get("improvements", [])
        successful = [r for r in improvements if r.get("success") and not r.get("skipped")]
        failed = [r for r in improvements if not r.get("success")]
        skipped = [r for r in improvements if r.get("skipped")]

        new_apis = [a for a in results.get("new_apis", []) if a.get("success")]
        score = results.get("system_score", 0)
        grade = results.get("system_grade", "?")
        lessons = results.get("lessons_learned", {})

        lines = ["🧬 <b>Self-Evolution Cycle</b>"]
        lines.append(f"📊 System score: <b>{score}/100</b> (Grade {grade})")

        if lessons.get("critical_errors"):
            lines.append(f"\n🚨 <b>Critical errors found:</b> {len(lessons['critical_errors'])}")

        if successful:
            lines.append(f"\n✅ <b>Files improved ({len(successful)}):</b>")
            for r in successful[:3]:
                lines.append(
                    f"  • {r['file'].split('/')[-1]} "
                    f"[commit: {r.get('commit_sha', '?')}] "
                    f"(+{r.get('lines_delta', 0)} lines)"
                )

        if new_apis:
            lines.append(f"\n🔌 <b>New APIs integrated ({len(new_apis)}):</b>")
            for a in new_apis[:2]:
                lines.append(f"  • {a.get('api', '?')} — {a.get('benefit', '')[:50]}")

        if skipped:
            lines.append(f"\n⏭️ Already-optimal files: {len(skipped)}")
        if failed:
            lines.append(f"\n❌ Failures: {len(failed)}")

        arch = results.get("architecture_analysis", {})
        if arch.get("success") and arch.get("analysis", {}).get("next_features_to_add"):
            next_f = arch["analysis"]["next_features_to_add"][:2]
            lines.append("\n💡 <b>Suggested next improvements:</b>")
            for f in next_f:
                lines.append(f"  • {f}")

        await self._send_telegram("\n".join(lines))
