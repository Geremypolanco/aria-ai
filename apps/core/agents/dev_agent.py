"""
dev_agent.py — Developer Agent with HuggingFace Code Generation + image analysis.
Generates code, analyzes repositories, creates complete digital products.
"""

from __future__ import annotations

import logging
from typing import Any

from apps.core.agents.base_agent import BaseAgent
from apps.core.tools.ai_client import AIModel

logger = logging.getLogger("aria.dev_agent")


class DevAgent(BaseAgent):
    def __init__(self) -> None:
        super().__init__(
            name="dev",
            description="Software and digital product development — code with HuggingFace Qwen2.5-Coder",
            capabilities=[
                "code_generation",
                "product_development",
                "api_integration",
                "database_design",
                "frontend_development",
                "automation_scripts",
                "code_review",
                "bug_fixing",
                "architecture_design",
            ],
        )

    async def _execute(self, context: dict[str, Any]) -> dict[str, Any]:
        task = context.get("task", "")
        product = context.get("product", {})
        language = context.get("coding_language", "python")
        build_type = context.get("build_type", "api")

        results: dict[str, Any] = {"success": True, "agent": "dev_agent"}

        # Determine what to build (bilingual match against user task text — left untranslated)
        if product or "producto" in task.lower() or "product" in task.lower():
            artifact = await self._build_digital_product(product, task, language, build_type)
            results["artifact"] = artifact
        else:
            code_result = await self._generate_code_solution(task, language)
            results["code"] = code_result

        # Generate documentation if there is code
        if results.get("artifact") or results.get("code"):
            docs = await self._generate_documentation(task, results)
            results["documentation"] = docs

        await self._log("dev_task_complete", f"Task: {task[:80]} | Language: {language}")
        return results

    async def _build_digital_product(
        self, product: dict, task: str, language: str, build_type: str
    ) -> dict[str, Any]:
        """Builds a complete digital product using HuggingFace Qwen2.5-Coder."""
        import asyncio

        from apps.core.tools.huggingface_suite import HuggingFaceSuite

        hf = HuggingFaceSuite()

        product_name = product.get("name", "Digital Product")
        product_desc = product.get("description", task)

        # Backend code generation
        backend_prompt = (
            f"Build a production-ready {build_type} for: {product_name}\n"
            f"Description: {product_desc}\n"
            f"Requirements: RESTful API, authentication, database models, error handling, logging\n"
            f"Stack: FastAPI + SQLAlchemy + PostgreSQL (use {language})\n"
            "Generate complete, working code."
        )

        # Frontend generation
        frontend_prompt = (
            f"Build a modern landing page / frontend for: {product_name}\n"
            f"Description: {product_desc}\n"
            "Requirements: HTML5 + Tailwind CSS + vanilla JS, responsive, conversion-optimized\n"
            "Include: hero section, features, pricing, CTA, contact form"
        )

        # Run in parallel
        backend_task = hf.generate_code(backend_prompt, language)
        frontend_task = hf.generate_code(frontend_prompt, "html")
        readme_task = hf.generate_code(
            f"Write a complete README.md for {product_name}: {product_desc}. Include setup, API docs, deployment.",
            "markdown",
        )

        backend, frontend, readme = await asyncio.gather(
            backend_task, frontend_task, readme_task, return_exceptions=True
        )

        return {
            "product": product_name,
            "backend_code": (
                backend.get("code", "")
                if isinstance(backend, dict) and backend.get("success")
                else ""
            ),
            "frontend_code": (
                frontend.get("code", "")
                if isinstance(frontend, dict) and frontend.get("success")
                else ""
            ),
            "readme": (
                readme.get("code", "") if isinstance(readme, dict) and readme.get("success") else ""
            ),
            "build_type": build_type,
        }

    async def _generate_code_solution(self, task: str, language: str) -> dict[str, Any]:
        """Generates a code solution for any task."""
        from apps.core.tools.huggingface_suite import HuggingFaceSuite

        hf = HuggingFaceSuite()
        result = await hf.generate_code(task, language)

        if not result.get("success"):
            # Fallback to ai_client
            from apps.core.tools.ai_client import get_ai_client

            ai = get_ai_client()
            response = await ai.complete(
                system=f"Expert {language} developer. Write clean, production-ready code only.",
                user=task,
                model=AIModel.CODE,
            )
            return {
                "code": response.content if response else "",
                "language": language,
                "model": "fallback",
            }

        return result

    async def _generate_documentation(self, task: str, results: dict) -> str:
        """Generates technical documentation for the produced code."""
        code_preview = ""
        if results.get("artifact", {}).get("backend_code"):
            code_preview = results["artifact"]["backend_code"][:500]
        elif results.get("code", {}).get("code"):
            code_preview = results["code"]["code"][:500]

        if not code_preview:
            return ""

        response = await self.think(
            system="Technical writer. Generate concise developer documentation in Markdown.",
            user=f"Document this code briefly (max 200 words):\n{code_preview}",
            model=AIModel.FAST,
        )
        return response or ""
