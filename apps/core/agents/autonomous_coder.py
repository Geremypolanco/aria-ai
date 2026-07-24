"""
autonomous_coder.py — Autonomous Coding for ARIA AI.

Integrates Aider and SWE-agent so ARIA can:
  - Modify its own code autonomously (Aider)
  - Create Pull Requests with documented changes
  - Resolve GitHub issues automatically (SWE-agent)
  - Perform refactors and code improvements
  - Add new capabilities without human intervention

Extends the existing EvolutionAgent with real coding tools.

Reference:
  - Aider: https://github.com/Aider-AI/aider
  - SWE-agent: https://github.com/SWE-agent/SWE-agent
"""

from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path
from typing import Any

logger = logging.getLogger("aria.autonomous_coder")

# ── Aider Import with fallback ───────────────────────────────────────────────
try:
    from aider.coders import Coder
    from aider.io import InputOutput
    from aider.models import Model

    AIDER_AVAILABLE = True
    logger.info("[Aider] Library loaded successfully.")
except ImportError:
    AIDER_AVAILABLE = False
    logger.warning(
        "[Aider] aider-chat not installed. "
        "Using subprocess as fallback. "
        "Install with: pip install aider-chat"
    )
    Coder = None  # type: ignore[assignment,misc]
    Model = None  # type: ignore[assignment,misc]
    InputOutput = None  # type: ignore[assignment,misc]

# ── SWE-agent Import with fallback ───────────────────────────────────────────
try:
    import sweagent  # noqa: F401

    SWEAGENT_AVAILABLE = True
    logger.info("[SWE-agent] Library loaded successfully.")
except ImportError:
    SWEAGENT_AVAILABLE = False
    logger.warning(
        "[SWE-agent] sweagent not installed. "
        "Using the GitHub API as fallback. "
        "Install with: pip install sweagent"
    )


# ── Aider Engine ──────────────────────────────────────────────────────────────


class AriaAiderEngine:
    """
    Autonomous coding engine using Aider for ARIA AI.

    Lets ARIA modify its own code, create features,
    fix bugs, and perform refactors autonomously.

    Integrates with the existing EvolutionAgent for the self-improvement cycle.

    Usage:
        engine = AriaAiderEngine()

        # Modify a specific file
        result = await engine.modify_file(
            file_path="apps/core/agents/marketing_agent.py",
            instruction="Add PostHog analytics support in the _execute method",
        )

        # Create a new feature
        result = await engine.create_feature(
            description="Add Stripe webhooks integration",
            target_files=["apps/core/tools/sales_engine.py"],
        )
    """

    def __init__(
        self,
        repo_path: str = ".",
        model: str = "gpt-4o-mini",
        openai_api_key: str = "",
    ) -> None:
        self._repo_path = Path(repo_path).resolve()
        self._model = model
        self._openai_api_key = openai_api_key or os.getenv("OPENAI_API_KEY", "")
        self._history: list[dict[str, Any]] = []

    async def modify_file(
        self,
        file_path: str,
        instruction: str,
        auto_commit: bool = True,
        commit_message: str = "",
    ) -> dict[str, Any]:
        """
        Modifies a specific file according to a natural-language instruction.

        Args:
            file_path: Relative path to the file to modify
            instruction: Natural-language instruction
            auto_commit: Whether to auto-commit
            commit_message: Commit message (auto-generated if empty)

        Returns:
            Dict with the result of the modification
        """
        full_path = self._repo_path / file_path

        if not full_path.exists():
            return {
                "success": False,
                "error": f"File not found: {file_path}",
                "file": file_path,
            }

        if AIDER_AVAILABLE and Coder is not None:
            return await self._modify_with_aider(
                file_path=str(full_path),
                instruction=instruction,
                auto_commit=auto_commit,
                commit_message=commit_message,
            )
        return await self._modify_with_subprocess(
            file_path=str(full_path),
            instruction=instruction,
            auto_commit=auto_commit,
            commit_message=commit_message,
        )

    async def _modify_with_aider(
        self,
        file_path: str,
        instruction: str,
        auto_commit: bool,
        commit_message: str,
    ) -> dict[str, Any]:
        """Modifies a file using the Aider API."""
        try:
            io = InputOutput(
                yes=True,  # Auto-confirm changes
                chat_history_file=None,
            )

            model = Model(self._model)
            coder = Coder.create(
                main_model=model,
                fnames=[file_path],
                io=io,
                auto_commits=auto_commit,
                git=auto_commit,
            )

            # Run in a thread so we don't block the event loop
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(
                None,
                lambda: coder.run(instruction),
            )

            result = {
                "success": True,
                "file": file_path,
                "instruction": instruction,
                "auto_committed": auto_commit,
                "source": "aider",
            }

            self._history.append(result)
            logger.info("[Aider] File modified: %s", file_path)
            return result

        except Exception as exc:
            logger.error("[Aider] Error modifying %s: %s", file_path, exc)
            return {
                "success": False,
                "error": str(exc),
                "file": file_path,
                "source": "aider",
            }

    async def _modify_with_subprocess(
        self,
        file_path: str,
        instruction: str,
        auto_commit: bool,
        commit_message: str,
    ) -> dict[str, Any]:
        """Fallback: uses aider as a subprocess."""
        if not self._openai_api_key:
            return {
                "success": False,
                "error": "OPENAI_API_KEY not configured for Aider",
                "file": file_path,
                "source": "subprocess_fallback",
            }

        try:
            cmd = [
                "aider",
                "--model",
                self._model,
                "--yes",
                "--no-pretty",
                "--message",
                instruction,
                file_path,
            ]

            if not auto_commit:
                cmd.append("--no-auto-commits")

            env = {**os.environ, "OPENAI_API_KEY": self._openai_api_key}

            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=env,
                cwd=str(self._repo_path),
            )

            stdout, stderr = await asyncio.wait_for(
                process.communicate(),
                timeout=120.0,
            )

            success = process.returncode == 0
            result = {
                "success": success,
                "file": file_path,
                "instruction": instruction,
                "stdout": stdout.decode()[:2000] if stdout else "",
                "stderr": stderr.decode()[:500] if stderr else "",
                "source": "aider_subprocess",
            }

            if success:
                logger.info("[Aider] Successful modification via subprocess: %s", file_path)
            else:
                logger.warning("[Aider] Subprocess error: %s", result["stderr"])

            self._history.append(result)
            return result

        except TimeoutError:
            return {
                "success": False,
                "error": "Aider timeout (120s)",
                "file": file_path,
                "source": "aider_subprocess",
            }
        except FileNotFoundError:
            return {
                "success": False,
                "error": "Aider not found. Install with: pip install aider-chat",
                "file": file_path,
                "source": "aider_subprocess",
            }
        except Exception as exc:
            return {
                "success": False,
                "error": str(exc),
                "file": file_path,
                "source": "aider_subprocess",
            }

    async def create_feature(
        self,
        description: str,
        target_files: list[str],
        create_tests: bool = True,
    ) -> dict[str, Any]:
        """
        Creates a new feature in the specified files.

        Args:
            description: Description of the feature to create
            target_files: Files to modify
            create_tests: Whether to auto-create tests

        Returns:
            Dict with the result of the creation
        """
        instruction = description
        if create_tests:
            instruction += "\n\nAlso add unit tests for the new functionality."

        results = []
        for file_path in target_files:
            result = await self.modify_file(
                file_path=file_path,
                instruction=instruction,
            )
            results.append(result)

        success = all(r.get("success") for r in results)
        return {
            "success": success,
            "description": description,
            "files_modified": target_files,
            "results": results,
            "tests_created": create_tests,
        }

    async def create_pull_request(
        self,
        title: str,
        description: str,
        branch_name: str = "",
        files_to_modify: list[str] | None = None,
        instruction: str = "",
    ) -> dict[str, Any]:
        """
        Creates a Pull Request with code changes.

        Args:
            title: PR title
            description: PR description
            branch_name: Branch name (auto-generated if empty)
            files_to_modify: Files to modify before the PR
            instruction: Instruction for Aider

        Returns:
            Dict with the URL of the created PR
        """
        import re

        branch = branch_name or f"aria/auto-{re.sub(r'[^a-z0-9-]', '-', title.lower())[:40]}"

        try:
            # Create branch
            await asyncio.create_subprocess_exec(
                "git",
                "checkout",
                "-b",
                branch,
                cwd=str(self._repo_path),
            )

            # Modify files if specified
            if files_to_modify and instruction:
                for file_path in files_to_modify:
                    await self.modify_file(file_path, instruction)

            # Create PR with GitHub CLI
            process = await asyncio.create_subprocess_exec(
                "gh",
                "pr",
                "create",
                "--title",
                title,
                "--body",
                description,
                "--head",
                branch,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(self._repo_path),
            )
            stdout, stderr = await process.communicate()

            if process.returncode == 0:
                pr_url = stdout.decode().strip()
                logger.info("[Aider] PR created: %s", pr_url)
                return {
                    "success": True,
                    "pr_url": pr_url,
                    "branch": branch,
                    "title": title,
                }
            return {
                "success": False,
                "error": stderr.decode()[:500],
                "branch": branch,
            }

        except Exception as exc:
            logger.error("[Aider] Error creating PR: %s", exc)
            return {"success": False, "error": str(exc)}

    def get_history(self) -> list[dict[str, Any]]:
        """Returns the modification history."""
        return self._history.copy()


# ── SWE-agent Engine ──────────────────────────────────────────────────────────


class AriaSWEAgentEngine:
    """
    Issue-resolution engine using SWE-agent for ARIA AI.

    SWE-agent can resolve GitHub issues automatically,
    generating patches and PRs with complete solutions.

    Integrates with the EvolutionAgent for the self-improvement cycle.

    Usage:
        engine = AriaSWEAgentEngine()

        # Resolve a GitHub issue
        result = await engine.resolve_github_issue(
            repo="Geremypolanco/aria-ai",
            issue_number=42,
        )
    """

    def __init__(
        self,
        model: str = "gpt-4o",
        openai_api_key: str = "",
    ) -> None:
        self._model = model
        self._openai_api_key = openai_api_key or os.getenv("OPENAI_API_KEY", "")
        self._history: list[dict[str, Any]] = []

    async def resolve_github_issue(
        self,
        repo: str,
        issue_number: int,
        create_pr: bool = True,
    ) -> dict[str, Any]:
        """
        Resolves a GitHub issue automatically.

        Args:
            repo: Repository in "owner/repo" format
            issue_number: Issue number
            create_pr: Whether to create a PR with the solution

        Returns:
            Dict with the result and PR URL if one was created
        """
        if SWEAGENT_AVAILABLE:
            return await self._resolve_with_sweagent(repo, issue_number, create_pr)
        return await self._resolve_with_github_api(repo, issue_number, create_pr)

    async def _resolve_with_sweagent(
        self,
        repo: str,
        issue_number: int,
        create_pr: bool,
    ) -> dict[str, Any]:
        """Resolves the issue using native SWE-agent."""
        try:
            cmd = [
                "python",
                "-m",
                "sweagent.run",
                "--model_name",
                self._model,
                "--data.type",
                "github",
                "--data.repo_name",
                repo,
                "--data.issue_number",
                str(issue_number),
            ]

            if create_pr:
                cmd.extend(["--actions.open_pr", "true"])

            env = {**os.environ, "OPENAI_API_KEY": self._openai_api_key}

            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=env,
            )

            stdout, stderr = await asyncio.wait_for(
                process.communicate(),
                timeout=300.0,  # 5 minutes for complex issues
            )

            success = process.returncode == 0
            result = {
                "success": success,
                "repo": repo,
                "issue_number": issue_number,
                "stdout": stdout.decode()[:3000] if stdout else "",
                "source": "sweagent",
            }

            self._history.append(result)
            return result

        except TimeoutError:
            return {
                "success": False,
                "error": "SWE-agent timeout (300s)",
                "repo": repo,
                "issue_number": issue_number,
            }
        except Exception as exc:
            logger.error("[SWE-agent] Error: %s", exc)
            return {"success": False, "error": str(exc)}

    async def _resolve_with_github_api(
        self,
        repo: str,
        issue_number: int,
        create_pr: bool,
    ) -> dict[str, Any]:
        """
        Fallback: analyzes the issue with AI and proposes a solution.
        Uses the GitHub API to fetch the issue and ARIA's ai_client.
        """
        try:
            import httpx

            github_token = os.getenv("GITHUB_TOKEN", "")
            headers = {"Authorization": f"token {github_token}"} if github_token else {}

            async with httpx.AsyncClient() as client:
                response = await client.get(
                    f"https://api.github.com/repos/{repo}/issues/{issue_number}",
                    headers=headers,
                )
                issue_data = response.json()

            issue_title = issue_data.get("title", "")
            issue_body = issue_data.get("body", "")

            # Analyze with AI
            try:
                from apps.core.tools.ai_client import AIModel, get_ai_client

                ai = get_ai_client()
                analysis = await ai.think(
                    system=(
                        "You are a software engineering expert. "
                        "Analyze the GitHub issue and propose a detailed solution."
                    ),
                    user=f"Issue #{issue_number}: {issue_title}\n\n{issue_body}",
                    model=AIModel.STRATEGY,
                )
            except Exception:
                analysis = f"Issue analyzed: {issue_title}"

            result = {
                "success": True,
                "repo": repo,
                "issue_number": issue_number,
                "issue_title": issue_title,
                "proposed_solution": analysis,
                "source": "github_api_fallback",
                "note": "SWE-agent not available. Install with: pip install sweagent",
            }

            self._history.append(result)
            return result

        except Exception as exc:
            return {
                "success": False,
                "error": str(exc),
                "repo": repo,
                "issue_number": issue_number,
                "source": "github_api_fallback",
            }

    async def analyze_codebase(
        self,
        repo_path: str,
        focus: str = "performance and bugs",
    ) -> dict[str, Any]:
        """
        Analyzes the full codebase looking for improvements.
        Integrates with ARIA's EvolutionAgent.

        Args:
            repo_path: Path to the repository
            focus: Focus area of the analysis

        Returns:
            Analysis report with suggested improvements
        """
        try:
            # Get list of Python files
            python_files = list(Path(repo_path).rglob("*.py"))
            python_files = [f for f in python_files if "__pycache__" not in str(f)][:20]

            file_list = "\n".join(str(f.relative_to(repo_path)) for f in python_files)

            try:
                from apps.core.tools.ai_client import AIModel, get_ai_client

                ai = get_ai_client()
                analysis = await ai.think(
                    system=(
                        "You are a software architecture and Python expert. "
                        "Analyze the project structure and suggest concrete improvements."
                    ),
                    user=(
                        f"Project: ARIA AI (autonomous digital income system)\n"
                        f"Focus: {focus}\n\n"
                        f"Main files:\n{file_list}\n\n"
                        "Suggest the 5 most impactful improvements."
                    ),
                    model=AIModel.STRATEGY,
                )
            except Exception:
                analysis = "Analysis not available (ai_client not configured)"

            return {
                "success": True,
                "repo_path": repo_path,
                "files_analyzed": len(python_files),
                "focus": focus,
                "analysis": analysis,
                "source": "swe_agent_analysis",
            }

        except Exception as exc:
            return {"success": False, "error": str(exc)}

    def get_history(self) -> list[dict[str, Any]]:
        """Returns the resolution history."""
        return self._history.copy()


# ── Unified Autonomous Coding Engine ─────────────────────────────────────────


class AriaAutonomousCoderEngine:
    """
    Unified Autonomous Coding engine for ARIA AI.

    Combines Aider (file modification) and SWE-agent (issue resolution)
    to give ARIA full code self-evolution capabilities.

    Integrates with:
    - EvolutionAgent (self-improvement cycle)
    - DevAgent (feature development)
    - GitHub (PRs and issues)
    - ExecutionPipeline (change auditing)
    """

    def __init__(
        self,
        repo_path: str = ".",
        model: str = "gpt-4o-mini",
    ) -> None:
        self.aider = AriaAiderEngine(
            repo_path=repo_path,
            model=model,
        )
        self.swe_agent = AriaSWEAgentEngine(model=model)
        self._repo_path = repo_path

    async def auto_improve(
        self,
        target: str,
        improvement_type: str = "feature",
        context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """
        Automatic improvement of ARIA's code.

        Args:
            target: File or description of the target
            improvement_type: 'feature', 'bug_fix', 'refactor', 'test', 'issue'
            context: Additional context

        Returns:
            Result of the improvement
        """
        ctx = context or {}

        if improvement_type == "issue" and ctx.get("issue_number"):
            return await self.swe_agent.resolve_github_issue(
                repo=ctx.get("repo", "Geremypolanco/aria-ai"),
                issue_number=ctx["issue_number"],
            )

        if improvement_type in ("feature", "bug_fix", "refactor"):
            instruction = ctx.get("instruction", f"Improve {target}: {improvement_type}")
            return await self.aider.modify_file(
                file_path=target,
                instruction=instruction,
            )

        if improvement_type == "test":
            instruction = f"Add comprehensive unit tests for {target}"
            test_file = target.replace(".py", "_test.py").replace("apps/", "tests/")
            return await self.aider.create_feature(
                description=instruction,
                target_files=[target, test_file],
                create_tests=True,
            )

        return {
            "success": False,
            "error": f"Unrecognized improvement type: {improvement_type}",
        }

    def get_capabilities(self) -> dict[str, Any]:
        """Returns the available capabilities."""
        return {
            "aider": {
                "available": AIDER_AVAILABLE,
                "capabilities": ["modify_file", "create_feature", "create_pr"],
            },
            "swe_agent": {
                "available": SWEAGENT_AVAILABLE,
                "capabilities": ["resolve_github_issue", "analyze_codebase"],
            },
        }


# ── Singleton ──────────────────────────────────────────────────────────────
_coder_instance: AriaAutonomousCoderEngine | None = None


def get_autonomous_coder() -> AriaAutonomousCoderEngine:
    """Returns the singleton of the Autonomous Coding engine."""
    global _coder_instance
    if _coder_instance is None:
        _coder_instance = AriaAutonomousCoderEngine(
            repo_path=os.getenv("ARIA_REPO_PATH", "."),
            model=os.getenv("AIDER_MODEL", "gpt-4o-mini"),
        )
    return _coder_instance
