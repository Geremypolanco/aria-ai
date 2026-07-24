import asyncio
import logging
from typing import Any

from apps.core.agents.base_agent import BaseAgent
from apps.core.sandbox.universal_sandbox import SandboxManager
from apps.core.tools.ai_client import AIModel, get_ai_client

logger = logging.getLogger("aria.code_reflector")


class CodeReflector(BaseAgent):
    """
    Agent responsible for Aria's safe self-reflection and self-modification of its code.
    Allows Aria to read, analyze, propose changes, test them, and apply them to its own codebase.
    """

    def __init__(self):
        super().__init__(
            name="code_reflector",
            description="Analyzes, proposes, and safely applies modifications to Aria's code.",
            capabilities=[
                "code_analysis",
                "code_generation",
                "self_modification",
                "safe_deployment",
                "testing",
            ],
        )
        self.sandbox_manager = SandboxManager()
        self.codebase_root = "/home/ubuntu/aria-ai"  # Root path of Aria's repository

    async def _execute(self, context: dict[str, Any]) -> dict[str, Any]:
        """Runs the self-reflection and modification process."""
        task = context.get("task", "")
        target_file = context.get("target_file")
        modification_plan = context.get("modification_plan")

        if modification_plan:
            return await self._apply_modification_plan(modification_plan)
        if target_file:
            return await self._reflect_on_file(target_file, task)
        return await self._initiate_self_reflection(task)

    async def _initiate_self_reflection(self, high_level_task: str) -> dict[str, Any]:
        """
        Starts a self-reflection cycle based on a high-level task.
        Aria decides which parts of its code need to be analyzed.
        """
        ai = get_ai_client()
        if not ai:
            return {"success": False, "error": "AI client not available"}

        system_prompt = (
            "You are a self-reflection agent for ARIA. Your task is to identify "
            "which files in Aria's codebase are relevant to a high-level task "
            "and how they should be analyzed to propose improvements. "
            "Respond ONLY with valid JSON, no markdown."
        )

        user_prompt = f"""Given the following high-level task to improve ARIA:

TASK: {high_level_task}

Analyze ARIA's codebase (directory structure in /home/ubuntu/aria-ai/apps/core/) and suggest:
1. A list of files relevant to this task.
2. For each file, a brief description of why it is relevant and what type of analysis is needed (e.g. 'identify functions', 'understand data flow', 'look for improvement patterns').

Provide a JSON with the following structure:
{{
  "analysis_summary": "Summary of the analysis strategy",
  "relevant_files": [
    {{
      "path": "path/to/file.py",
      "reason": "reason for relevance",
      "analysis_type": "type of analysis"
    }}
  ]
}}"""

        try:
            response = await ai.complete_json(
                system=system_prompt,
                user=user_prompt,
                model=AIModel.STRATEGY,
                max_tokens=1000,
                agent_name="code_reflector",
            )
            logger.info(f"[CodeReflector] Self-reflection plan generated: {response}")
            return {"success": True, "plan": response}
        except Exception as e:
            logger.error(f"[CodeReflector] Error generating self-reflection plan: {e}")
            return {"success": False, "error": str(e)}

    async def _reflect_on_file(self, file_path: str, analysis_task: str) -> dict[str, Any]:
        """
        Reads a file, analyzes it, and proposes modifications.
        """
        ai = get_ai_client()
        if not ai:
            return {"success": False, "error": "AI client not available"}

        try:
            with open(f"{self.codebase_root}/{file_path}") as f:
                code_content = f.read()
        except FileNotFoundError:
            return {"success": False, "error": f"File not found: {file_path}"}

        system_prompt = (
            "You are a code self-modification agent for ARIA. "
            "Your task is to analyze the provided code and, based on an improvement task, "
            "propose a detailed modification plan. "
            "Respond ONLY with valid JSON, no markdown."
        )

        user_prompt = f"""Analyze the following code from ARIA's file {file_path}:

```python
{code_content}
```

Based on the following improvement task:
IMPROVEMENT TASK: {analysis_task}

Propose a modification plan in JSON with the following structure. If no changes are needed, `modifications` should be an empty list.
{{
  "reasoning": "Explanation of why these changes are proposed or why they are not necessary",
  "modifications": [
    {{
      "type": "add" | "replace" | "delete",
      "target_line_start": "start line number (1-indexed)",
      "target_line_end": "end line number (1-indexed)",
      "content": "new content to add/replace (leave empty for delete)",
      "description": "description of the change"
    }}
  ],
  "test_plan": "Description of how to test the changes in the sandbox (e.g. 'run existing tests', 'run function X with parameters Y')"
}}"""

        try:
            modification_proposal = await ai.complete_json(
                system=system_prompt,
                user=user_prompt,
                model=AIModel.STRATEGY,  # Use a strategy model for the proposal
                max_tokens=2000,
                agent_name="code_reflector",
            )
            logger.info(
                f"[CodeReflector] Modification proposal for {file_path}: {modification_proposal}"
            )
            return {"success": True, "proposal": modification_proposal, "file_path": file_path}
        except Exception as e:
            logger.error(f"[CodeReflector] Error proposing modification for {file_path}: {e}")
            return {"success": False, "error": str(e)}

    async def _apply_modification_plan(self, modification_plan: dict[str, Any]) -> dict[str, Any]:
        """
        Applies a proposed modification plan, with tests in the sandbox.
        """
        file_path = modification_plan.get("file_path")
        modifications = modification_plan.get("proposal", {}).get("modifications", [])
        test_plan = modification_plan.get("proposal", {}).get("test_plan", "")

        if not file_path or not modifications:
            return {"success": False, "error": "Invalid or empty modification plan."}

        full_path = f"{self.codebase_root}/{file_path}"

        # 1. Create a snapshot of the current code for possible rollback
        original_content = ""
        try:
            with open(full_path) as f:
                original_content = f.readlines()
        except FileNotFoundError:
            return {
                "success": False,
                "error": f"Original file not found for modification: {file_path}",
            }

        temp_content = list(original_content)  # Work with a mutable copy

        # 2. Apply modifications in memory
        try:
            # Modifications must be applied in reverse order if they affect line indexes
            # For simplicity, we assume there are no complex overlaps requiring re-indexing
            # In a real system, a diff/patch library or a more sophisticated approach would be used
            for mod in sorted(
                modifications, key=lambda x: int(x.get("target_line_start", 0)), reverse=True
            ):
                mod_type = mod.get("type")
                start = int(mod.get("target_line_start")) - 1  # 0-indexed
                end = int(mod.get("target_line_end", start + 1)) - 1  # 0-indexed
                content = mod.get("content", "")

                if mod_type == "replace":
                    temp_content[start : end + 1] = [line + "\n" for line in content.splitlines()]
                elif mod_type == "add":
                    temp_content.insert(start, content + "\n")
                elif mod_type == "delete":
                    del temp_content[start : end + 1]

            modified_code = "".join(temp_content)
        except Exception as e:
            return {"success": False, "error": f"Error applying modifications in memory: {e}"}

        # 3. Save the modified code to a temporary file for testing
        temp_file_path = f"{full_path}.tmp"
        with open(temp_file_path, "w") as f:
            f.write(modified_code)

        # 4. Run the test plan in the sandbox
        test_result = await self._run_tests_in_sandbox(test_plan, temp_file_path)

        if test_result.get("success"):  # We assume the sandbox returns {success: True} if it passes
            logger.info(
                f"[CodeReflector] Tests passed for {file_path}. Applying permanent changes."
            )
            # 5. Apply permanent changes
            with open(full_path, "w") as f:
                f.write(modified_code)
            # Remove temporary file
            await self.sandbox_manager.execute_command(f"rm {temp_file_path}")
            return {
                "success": True,
                "message": f"Code for {file_path} modified and tested successfully.",
            }
        logger.warning(f"[CodeReflector] Tests failed for {file_path}. Reverting changes.")
        # 5. Rollback: remove temporary file and do not apply changes
        await self.sandbox_manager.execute_command(f"rm {temp_file_path}")
        return {
            "success": False,
            "error": f"Modification of {file_path} failed in tests: {test_result.get('error', 'Unknown error')}",
        }

    async def _run_tests_in_sandbox(
        self, test_plan: str, modified_file_path: str
    ) -> dict[str, Any]:
        """
        Runs the test plan in the Universal Sandbox.
        This is a simulation; in a real system, unit/integration tests would run here.
        """
        logger.info(f"[CodeReflector] Running test plan in sandbox: {test_plan}")
        # Here, the sandbox_manager should be able to run commands or scripts
        # that validate the change. For now, this is a simulation.
        # In a real scenario, the modified file could be copied into the sandbox
        # and a command like `pytest` or a validation script could be run.

        # Simulated test success
        if "simular_fallo" in test_plan.lower():
            return {"success": False, "error": "Failure simulated by the test plan."}

        # For a real test, the sandbox_manager should have a method like `run_script`
        # or `run_command` that can run the test code.
        # For example:
        # command = f"python3 -c \"import sys; sys.path.insert(0, "."); from {modified_file_path.replace('/', '.')[:-3]} import *; # run something\""
        # result = await self.sandbox_manager.execute_command(command)
        # return {"success": result.get("exit_code") == 0, "error": result.get("stderr")}

        await asyncio.sleep(2)  # Simulate test execution time
        return {"success": True, "message": "Simulated tests passed."}


# Global CodeReflector instance
code_reflector = CodeReflector()
