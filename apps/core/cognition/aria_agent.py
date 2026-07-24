import json
import logging
from typing import Any

from apps.core.tools.ai_client import AIModel, get_ai_client
from apps.core.tools.aria_tools import tool_registry

logger = logging.getLogger("aria.agent")


class AriaAgent:
    """
    General-Purpose Agent inspired by Claude Code.
    Implements a ReAct (Reasoning + Acting) loop for autonomous execution.
    """

    # Tool-registry entries that shell out (docker/vercel CLI) or write to a
    # real external system of record (GitHub) on the owner's behalf. Not
    # currently exploitable in production (no GITHUB_TOKEN wired into
    # ToolRegistry's GitHubTool, and the Fly.io container has neither the
    # docker nor vercel CLI installed) — but that's incidental, not a real
    # guard, so gate it properly rather than relying on "it happens to be
    # broken today". Mirrors aria_mind.py's _OWNER_ONLY_TOOLS.
    #
    # "infra" (InfraTools) runs arbitrary shell commands (execute_system_command,
    # shell=True, guarded only by a trivially-bypassable substring blocklist)
    # and arbitrary file read/write/delete (manage_files) — at least as
    # dangerous as github/docker/deployment. It's currently unreachable only
    # because _execute_tool()'s dispatch has no case for it (InfraTools has no
    # run() method) — the exact same "broken by accident, not by design"
    # situation the comment above already warns about. Gated here (plus the
    # two names the LLM is actually told to call, per _get_tools_desc()) so a
    # future dispatch fix doesn't silently turn this into an unauthenticated
    # RCE / arbitrary-file primitive.
    _OWNER_ONLY_TOOLS = frozenset(
        {"github", "docker", "deployment", "infra", "execute_system_command", "manage_files"}
    )

    def __init__(self, name: str = "Aria", identity: str = "", is_owner: bool = False):
        self.name = name
        self.identity = (
            identity
            or "You are a Pure Execution Autonomous Agent. Your mission is to solve complex tasks using tools."
        )
        self.ai = get_ai_client()
        self.max_steps = 15
        self.history = []
        self.is_owner = is_owner

    async def run(self, task: str) -> dict[str, Any]:
        """Executes a task autonomously until it completes or fails."""
        logger.info(f"[AriaAgent] Starting task: {task}")
        self.history = [{"role": "user", "content": task}]

        for step in range(self.max_steps):
            # 1. REASON AND DECIDE ACTION
            response = await self._think()
            if not response:
                return {"success": False, "error": "AI reasoning failure"}

            thought = response.get("thought", "")
            tool_name = response.get("tool")
            tool_args = response.get("tool_args", {})
            reply = response.get("reply", "")

            logger.info(f"[Step {step+1}] Thought: {thought}")

            # 2. IF THERE'S A FINAL REPLY, FINISH
            if not tool_name and reply:
                logger.info(f"[AriaAgent] Task completed: {reply}")
                return {"success": True, "output": reply, "steps": step + 1}

            # 3. EXECUTE TOOL
            if tool_name:
                logger.info(f"[Step {step+1}] Executing: {tool_name}({tool_args})")
                observation = await self._execute_tool(tool_name, tool_args)

                # 4. ADD OBSERVATION TO HISTORY
                self.history.append(
                    {
                        "role": "assistant",
                        "content": json.dumps(
                            {"thought": thought, "tool": tool_name, "tool_args": tool_args}
                        ),
                    }
                )
                self.history.append(
                    {
                        "role": "user",
                        "content": f"OBSERVATION from {tool_name}: {json.dumps(observation)}",
                    }
                )
            else:
                # If there's neither a tool nor a reply, something went wrong
                return {
                    "success": False,
                    "error": "Reasoning loop broken",
                    "last_thought": thought,
                }

        return {"success": False, "error": "Step limit reached"}

    async def _think(self) -> dict[str, Any] | None:
        """Calls the LLM to get the next step."""
        system_prompt = f"""{self.identity}

        AVAILABLE TOOLS:
        {self._get_tools_desc()}

        RULES:
        1. ALWAYS respond in valid JSON.
        2. Format: {{"thought": "...", "tool": "name|null", "tool_args": {{...}}|null, "reply": "..."}}
        3. If the task is finished, set "tool": null and write the final answer in "reply".
        4. If you need information, use a tool. Don't guess.
        5. If a tool fails, analyze the error in 'thought' and try a different approach.
        """

        try:
            return await self.ai.complete_json(
                system=system_prompt,
                user=self.history[-1]["content"],
                model=AIModel.STRATEGY,
                agent_name=self.name,
            )
        except Exception as e:
            logger.error(f"Error in _think: {e}")
            return None

    async def _execute_tool(self, name: str, args: dict[str, Any]) -> Any:
        """Looks up and executes the tool in the global registry."""
        if name in self._OWNER_ONLY_TOOLS and not self.is_owner:
            return {"error": f"'{name}' is reserved for ARIA's owner."}

        # 1. Look up in tool_registry
        tool_obj = tool_registry.get_tool(name)
        if tool_obj:
            # Try to call the method dynamically
            # We assume the tool has a main method or we map it
            try:
                # Simplified implementation: look for a matching method or use a dispatcher
                if hasattr(tool_obj, "run"):
                    return await tool_obj.run(**args)
                if name == "web_search":
                    from apps.core.tools.web_tools import WebTools

                    return await WebTools().search_web(**args)
                # ... more manual mappings if needed ...
                return {"error": f"Tool {name} found but not directly executable"}
            except Exception as e:
                return {"error": str(e)}

        return {"error": f"Tool '{name}' not found"}

    def _get_tools_desc(self) -> str:
        """Generates a description of tools for the prompt."""
        tools = tool_registry.list_tools()
        # Add core and infrastructure tools
        tools.extend(
            [
                "web_search",
                "execute_code",
                "github_view",
                "shopify_create",
                "manage_files",
                "execute_system_command",
                "monitor_api_health",
                "analyze_viral_content",
            ]
        )
        return ", ".join(tools)
