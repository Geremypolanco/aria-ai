"""
GitAgent - Especialista en operaciones de GitHub
Clona repos, crea branches, hace commits, abre PRs
"""
import logging
import subprocess
from typing import Dict, Any, Optional
from src.agents.base_agent import BaseAgent
from src.core.events.event_bus import EventBus, Event, EventType

logger = logging.getLogger("aria.agents.git")

class GitAgent(BaseAgent):
    """Agente especializado en operaciones de GitHub."""
    
    def __init__(self, event_bus: EventBus, github_token: Optional[str] = None):
        super().__init__(name="git_agent", event_bus=event_bus)
        self.github_token = github_token
    
    async def _subscribe_to_events(self):
        self.event_bus.subscribe(EventType.GOAL_CREATED, self.handle_git_task)
        self.event_bus.subscribe(EventType.AGENT_MESSAGE, self.handle_direct_message)
    
    async def handle_git_task(self, event: Event):
        """Maneja tareas de Git."""
        payload = event.payload
        if payload.get("type") == "git_operation":
            await self.execute_git_operation(payload)
    
    async def handle_direct_message(self, event: Event):
        """Maneja mensajes directos al agente."""
        if event.payload.get("target") == self.name:
            await self.execute_git_operation(event.payload)
    
    async def execute_git_operation(self, task: Dict[str, Any]):
        """Ejecuta operaciones de Git/GitHub."""
        operation = task.get("operation")
        logger.info(f"GitAgent: Ejecutando operación: {operation}")
        
        if operation == "clone":
            result = await self._clone_repo(task.get("repo_url"), task.get("target_dir"))
        elif operation == "commit":
            result = await self._commit_changes(task.get("repo_dir"), task.get("message"))
        elif operation == "push":
            result = await self._push_changes(task.get("repo_dir"), task.get("branch"))
        elif operation == "create_pr":
            result = await self._create_pull_request(task)
        else:
            result = {"success": False, "error": f"Operación desconocida: {operation}"}
        
        await self.event_bus.publish(Event(
            type=EventType.TASK_COMPLETED,
            payload={
                "task_id": task.get("id"),
                "agent": self.name,
                "operation": operation,
                "result": result
            },
            source=self.name
        ))
    
    async def _clone_repo(self, repo_url: str, target_dir: str) -> Dict[str, Any]:
        """Clona un repositorio."""
        try:
            result = subprocess.run(
                ["git", "clone", repo_url, target_dir],
                capture_output=True,
                text=True,
                timeout=60
            )
            return {
                "success": result.returncode == 0,
                "message": result.stdout or result.stderr
            }
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    async def _commit_changes(self, repo_dir: str, message: str) -> Dict[str, Any]:
        """Hace commit de cambios."""
        try:
            subprocess.run(["git", "-C", repo_dir, "add", "."], check=True, capture_output=True)
            result = subprocess.run(
                ["git", "-C", repo_dir, "commit", "-m", message],
                capture_output=True,
                text=True
            )
            return {
                "success": result.returncode == 0,
                "message": result.stdout or result.stderr
            }
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    async def _push_changes(self, repo_dir: str, branch: str = "main") -> Dict[str, Any]:
        """Hace push de cambios."""
        try:
            result = subprocess.run(
                ["git", "-C", repo_dir, "push", "origin", branch],
                capture_output=True,
                text=True,
                timeout=60
            )
            return {
                "success": result.returncode == 0,
                "message": result.stdout or result.stderr
            }
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    async def _create_pull_request(self, task: Dict[str, Any]) -> Dict[str, Any]:
        """Crea un pull request (requiere GitHub CLI)."""
        try:
            title = task.get("title", "Auto-generated PR")
            body = task.get("body", "")
            branch = task.get("branch", "feature")
            
            result = subprocess.run(
                ["gh", "pr", "create", "--title", title, "--body", body, "--head", branch],
                capture_output=True,
                text=True,
                timeout=30
            )
            return {
                "success": result.returncode == 0,
                "pr_url": result.stdout.strip() if result.returncode == 0 else None,
                "message": result.stdout or result.stderr
            }
        except Exception as e:
            return {"success": False, "error": str(e)}
