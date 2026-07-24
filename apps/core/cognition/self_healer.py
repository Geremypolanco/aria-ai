import logging
import traceback
from typing import Any

from apps.core.tools.ai_client import AIModel, get_ai_client

logger = logging.getLogger("aria.healer")


class SystemSelfHealer:
    """
    ARIA's Self-Healing Engine.
    Detects failures in tools and agents, analyzes the code, and proposes/applies fixes.
    """

    def __init__(self):
        self.ai = get_ai_client()

    async def diagnose_and_fix(self, error: Exception, context: dict[str, Any]) -> dict[str, Any]:
        """Analyzes an error and generates a repair strategy."""
        error_trace = traceback.format_exc()
        tool_name = context.get("tool", "unknown")

        logger.error(f"[SelfHealer] Failure detected in {tool_name}: {error}")

        prompt = f"""
        ERROR DETECTED IN THE ARIA SYSTEM:
        Tool/Agent: {tool_name}
        Error: {str(error)}
        Traceback: {error_trace}
        Execution context: {context}

        TASK:
        1. Explain the root cause of the failure.
        2. Provide a code patch (Python) to fix the problem.
        3. If it's a missing API key or dependency, state it clearly.

        Respond in JSON with: root_cause, fix_code, required_actions.
        """

        try:
            fix_suggestion = await self.ai.complete_json(
                system="You are ARIA's Site Reliability Engineer. Your mission is the self-healing of the codebase.",
                user=prompt,
                model=AIModel.STRATEGY,
            )

            # Automatic patch application via github_self could be implemented here
            return {
                "success": True,
                "diagnosis": fix_suggestion,
                "message": "Failure analyzed. Repair suggestion ready for application.",
            }
        except Exception as e:
            return {"success": False, "error": f"The healer also failed: {e}"}
