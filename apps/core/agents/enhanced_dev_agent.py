"""
enhanced_dev_agent.py — Enhanced Development Agent for ARIA.

Combines the capabilities of:
- Multi-language code generation
- Sandbox execution
- Debugging and testing
- Automatic deployment
- Repository analysis
"""

from __future__ import annotations

import logging
from typing import Any

from apps.core.agents.base_agent import BaseAgent
from apps.core.sandbox.universal_sandbox import SandboxManager
from apps.core.tools.ai_client import AIModel, get_ai_client
from apps.core.tools.aria_tools import tool_registry

logger = logging.getLogger("aria.dev_agent")


class EnhancedDevAgent(BaseAgent):
    """Development agent with full Replit + Manus-level capabilities."""

    def __init__(self) -> None:
        super().__init__(
            name="enhanced_dev",
            description="Full software development — code, testing, deployment",
            capabilities=[
                "code_generation",
                "code_execution",
                "testing",
                "debugging",
                "deployment",
                "repository_analysis",
                "architecture_design",
                "refactoring",
            ],
        )
        self.sandbox_manager = SandboxManager()

    async def _execute(self, context: dict[str, Any]) -> dict[str, Any]:
        """Main entry point."""
        task = context.get("task", "")
        task_type = context.get("task_type", "general")
        language = context.get("language", "python")

        logger.info(f"[DevAgent] Running task: {task[:80]} ({language})")

        if "generate" in task_type.lower():
            return await self._generate_code(task, language, context)
        if "execute" in task_type.lower():
            return await self._execute_code(task, language, context)
        if "test" in task_type.lower():
            return await self._test_code(task, language, context)
        if "deploy" in task_type.lower():
            return await self._deploy(task, context)
        return await self._general_task(task, language, context)

    async def _generate_code(
        self, task: str, language: str, context: dict[str, Any]
    ) -> dict[str, Any]:
        """Generates complete code for a task."""
        ai = get_ai_client()
        if not ai:
            return {"success": False, "error": "AI client not available"}

        system_prompt = f"""You are an expert {language} developer.
Generate clean, well-documented, production-ready code.
Include error handling, logging, and unit tests.
Respond ONLY with valid code."""

        user_prompt = f"""Generate {language} code for:

{task}

REQUIREMENTS:
- Modular, reusable code
- Clear documentation
- Error handling
- Unit tests included
- Follow {language} best practices"""

        try:
            response = await ai.complete(
                system=system_prompt,
                user=user_prompt,
                model=AIModel.CODE,
                max_tokens=4000,
            )

            if not response.success:
                return {"success": False, "error": response.error or "Code generation failed"}

            # Extract code from the response
            code = self._extract_code(response.content)

            return {
                "success": True,
                "code": code,
                "language": language,
                "task": task,
            }

        except Exception as exc:
            logger.error(f"[DevAgent] Error generating code: {exc}")
            return {"success": False, "error": str(exc)}

    async def _execute_code(
        self, code: str, language: str, context: dict[str, Any]
    ) -> dict[str, Any]:
        """Executes code in an isolated sandbox."""
        try:
            # Create a sandbox session
            session = await self.sandbox_manager.create_session(language=language)
            if not session:
                return {"success": False, "error": "Could not create sandbox session"}

            # Install dependencies if needed
            dependencies = context.get("dependencies", [])
            for dep in dependencies:
                await session.install_package(dep)

            # Execute the code
            result = await session.execute_code(code, timeout=60)

            # Clean up
            await self.sandbox_manager.cleanup_session(session.session_id)

            return {
                "success": result.get("success", False),
                "output": result.get("output", ""),
                "error": result.get("error", ""),
                "execution_time": result.get("execution_time", 0),
                "session_id": session.session_id,
            }

        except Exception as exc:
            logger.error(f"[DevAgent] Error executing code: {exc}")
            return {"success": False, "error": str(exc)}

    async def _test_code(self, code: str, language: str, context: dict[str, Any]) -> dict[str, Any]:
        """Runs tests against code."""
        try:
            session = await self.sandbox_manager.create_session(language=language)
            if not session:
                return {"success": False, "error": "Could not create sandbox session"}

            # Install testing framework
            if language == "python":
                await session.install_package("pytest")
                test_cmd = "pytest -v"
            elif language == "node":
                await session.install_package("jest")
                test_cmd = "npm test"
            else:
                test_cmd = "test"

            # Write the test code
            test_file = f"test_code.{self._get_extension(language)}"
            await session.write_file(test_file, code)

            # Run the tests
            result = await session.execute_code(test_cmd, timeout=120)

            await self.sandbox_manager.cleanup_session(session.session_id)

            return {
                "success": result.get("success", False),
                "output": result.get("output", ""),
                "error": result.get("error", ""),
                "test_results": self._parse_test_results(result.get("output", "")),
            }

        except Exception as exc:
            logger.error(f"[DevAgent] Error running tests: {exc}")
            return {"success": False, "error": str(exc)}

    async def _deploy(self, project_path: str, context: dict[str, Any]) -> dict[str, Any]:
        """Deploys an application."""
        deployment_target = context.get("deployment_target", "vercel")
        token = context.get("deployment_token", "")

        try:
            deployment_tool = tool_registry.get_tool("deployment")
            if not deployment_tool:
                return {"success": False, "error": "Deployment tool not available"}

            if deployment_target == "vercel":
                result = await deployment_tool.deploy_to_vercel(project_path, token)
            elif deployment_target == "fly":
                app_name = context.get("app_name", "aria-app")
                result = await deployment_tool.deploy_to_fly(project_path, app_name)
            else:
                return {
                    "success": False,
                    "error": f"Unsupported deployment target: {deployment_target}",
                }

            return {
                "success": result.get("success", False),
                "output": result.get("output", ""),
                "error": result.get("error", ""),
                "deployment_target": deployment_target,
            }

        except Exception as exc:
            logger.error(f"[DevAgent] Error deploying: {exc}")
            return {"success": False, "error": str(exc)}

    async def _general_task(
        self, task: str, language: str, context: dict[str, Any]
    ) -> dict[str, Any]:
        """Handles general development tasks."""
        # Generate code first
        code_result = await self._generate_code(task, language, context)
        if not code_result.get("success"):
            return code_result

        # Execute the generated code
        code = code_result.get("code", "")
        exec_result = await self._execute_code(code, language, context)

        return {
            "success": exec_result.get("success", False),
            "code": code,
            "output": exec_result.get("output", ""),
            "error": exec_result.get("error", ""),
        }

    def _extract_code(self, response: str) -> str:
        """Extracts code from an AI response."""
        # Look for markdown code blocks
        import re

        pattern = r"```(?:python|javascript|node|go|rust|java)?\n(.*?)```"
        matches = re.findall(pattern, response, re.DOTALL)
        if matches:
            return matches[0].strip()
        return response

    def _get_extension(self, language: str) -> str:
        """Gets the file extension for a language."""
        extensions = {
            "python": "py",
            "node": "js",
            "javascript": "js",
            "go": "go",
            "rust": "rs",
            "java": "java",
            "cpp": "cpp",
            "csharp": "cs",
        }
        return extensions.get(language, language)

    def _parse_test_results(self, output: str) -> dict[str, Any]:
        """Parses test results."""
        # Simplified implementation
        return {
            "raw_output": output,
            "passed": "passed" in output.lower(),
        }

    async def cleanup(self) -> None:
        """Cleans up resources."""
        await self.sandbox_manager.cleanup_all()
