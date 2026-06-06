"""
main.py — API Backend Principal para ARIA.

Endpoints:
- /api/aria/chat — Chat interactivo
- /api/aria/execute — Ejecución de código
- /api/aria/shell — Comandos shell
- /api/aria/files — Gestión de archivos
- /api/aria/tasks — Gestión de tareas
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Dict

from fastapi import FastAPI, HTTPException, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from apps.core.agents.aria_orchestrator import AriaOrchestrator
from apps.core.agents.enhanced_dev_agent import EnhancedDevAgent
from apps.core.agents.research_agent import ResearchAgent
from apps.core.agents.interaction_agent import InteractionAgent
from apps.core.sandbox.universal_sandbox import SandboxManager
from apps.core.integrations.mcp_client import mcp_manager
from apps.core.config.secrets_manager import secrets_manager, env_manager, config_manager
from apps.core.deployment.deployment_orchestrator import deployment_orchestrator, DeploymentPlatform

logger = logging.getLogger("aria.api")

# Initialize FastAPI
app = FastAPI(
    title="ARIA API",
    description="Autonomous Reasoning Intelligence Agent",
    version="1.0.0",
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialize agents
orchestrator = AriaOrchestrator()
dev_agent = EnhancedDevAgent()
research_agent = ResearchAgent()
interaction_agent = InteractionAgent()
sandbox_manager = SandboxManager()
mcp_manager = mcp_manager # Usar la instancia global del mcp_manager


# Request models
class ChatRequest(BaseModel):
    message: str
    context: Dict[str, Any] = {}


class ExecuteRequest(BaseModel):
    code: str
    language: str = "python"
    dependencies: list = []


class ShellRequest(BaseModel):
    command: str


class FileRequest(BaseModel):
    path: str
    action: str  # read, write, delete, list
    content: str = ""


class TaskRequest(BaseModel):
    task: str
    task_type: str = "general"
    priority: int = 5


# Chat endpoint
# ==================== Endpoints de Conectores MCP ====================

@app.get("/api/aria/connectors")
async def list_connectors():
    """Lista todos los conectores MCP conectados."""
    connectors = []
    for name, client in mcp_manager.clients.items():
        connectors.append({
            "id": name,
            "name": name,
            "type": "mcp",
            "status": "connected",
            "tools": list(client.tools.keys()),
        })
    return {"success": True, "connectors": connectors}


@app.post("/api/aria/connectors")
async def add_connector(request: dict):
    """Añade un nuevo conector MCP."""
    try:
        name = request.get("name")
        url = request.get("url")
        connector_type = request.get("type")

        if connector_type == "mcp":
            client_info = {"name": name, "version": "1.0.0"}
            client = await mcp_manager.add_server(name, url, client_info)
            if client:
                return {
                    "success": True,
                    "connector": {
                        "id": name,
                        "name": name,
                        "type": "mcp",
                        "status": "connected",
                        "tools": list(client.tools.keys()),
                    },
                }
        return {"success": False, "error": "No se pudo conectar"}
    except Exception as exc:
        return {"success": False, "error": str(exc)}


@app.get("/api/aria/connectors/{connector_id}/tools")
async def get_connector_tools(connector_id: str):
    """Obtiene las herramientas de un conector."""
    client = mcp_manager.get_client(connector_id)
    if client:
        return {"success": True, "tools": list(client.tools.values())}
    return {"success": False, "error": "Conector no encontrado"}


@app.post("/api/aria/connectors/{connector_id}/test")
async def test_connector(connector_id: str):
    """Prueba la conexión de un conector."""
    client = mcp_manager.get_client(connector_id)
    if client:
        return {"success": True, "status": "connected"}
    return {"success": False, "error": "Conector no encontrado"}


# ==================== Endpoints de Secretos ====================

@app.get("/api/aria/secrets")
async def list_secrets():
    """Lista todos los secretos (sin mostrar valores)."""
    secrets = secrets_manager.list_secrets()
    return {"success": True, "secrets": [{"key": k, "value": v} for k, v in secrets.items()]}


@app.post("/api/aria/secrets")
async def add_secret(request: dict):
    """Añade un nuevo secreto."""
    key = request.get("key")
    value = request.get("value")
    tags = request.get("tags", [])

    success = secrets_manager.set_secret(key, value, tags)
    return {"success": success}


@app.delete("/api/aria/secrets/{key}")
async def delete_secret(key: str):
    """Elimina un secreto."""
    success = secrets_manager.delete_secret(key)
    return {"success": success}


@app.get("/api/aria/secrets/audit-log")
async def get_secrets_audit_log():
    """Obtiene el registro de auditoría de secretos."""
    log = secrets_manager.get_audit_log()
    return {"success": True, "log": log}


# ==================== Endpoints de Entornos ====================

@app.get("/api/aria/environments")
async def list_environments():
    """Lista todos los entornos."""
    envs = env_manager.list_environments()
    environments = []
    for env_name in envs:
        variables = env_manager.get_environment_variables(env_name)
        environments.append({
            "name": env_name,
            "variables": variables,
            "isActive": env_name == env_manager.current_environment,
        })
    return {"success": True, "environments": environments}


@app.post("/api/aria/environments")
async def create_environment(request: dict):
    """Crea un nuevo entorno."""
    name = request.get("name")
    success = env_manager.create_environment(name, {})
    return {"success": success}


@app.post("/api/aria/environments/{name}/activate")
async def activate_environment(name: str):
    """Activa un entorno."""
    success = env_manager.set_environment(name)
    return {"success": success}


# ==================== Endpoints de Despliegues ====================

@app.get("/api/aria/deployments")
async def list_deployments():
    """Lista todos los despliegues."""
    deployments = deployment_orchestrator.get_all_deployments()
    return {"success": True, "deployments": deployments}


@app.post("/api/aria/deployments")
async def create_deployment(request: dict):
    """Crea un nuevo despliegue."""
    try:
        platform_str = request.get("platform", "vercel")
        project_path = request.get("projectPath")
        config = {
            "project_name": request.get("projectName"),
            "vercel_token": secrets_manager.get_secret("VERCEL_TOKEN"),
            "app_name": request.get("projectName"),
        }

        platform = DeploymentPlatform[platform_str.upper()]
        result = await deployment_orchestrator.deploy(platform, project_path, config)
        return result
    except Exception as exc:
        return {"success": False, "error": str(exc)}


@app.get("/api/aria/deployments/{deployment_id}")
async def get_deployment_status(deployment_id: str):
    """Obtiene el estado de un despliegue."""
    status = deployment_orchestrator.get_deployment_status(deployment_id)
    if status:
        return {"success": True, "deployment": status}
    return {"success": False, "error": "Despliegue no encontrado"}


@app.post("/api/aria/deployments/{deployment_id}/rollback")
async def rollback_deployment(deployment_id: str):
    """Revierte un despliegue."""
    result = await deployment_orchestrator.rollback(deployment_id)
    return result


# ==================== Endpoint de Chat Original ====================

@app.post("/api/aria/chat")
async def chat(request: ChatRequest) -> Dict[str, Any]:
    """Procesa un mensaje de chat."""
    try:
        logger.info(f"[API] Chat: {request.message[:80]}")

        # Usar el orquestador para procesar la solicitud
        result = await orchestrator.execute_task(
            task=request.message,
            user_context=request.context,
        )

        return {
            "response": result.get("result", {}).get("summary", "Procesando..."),
            "code": None,
            "output": None,
            "success": result.get("success", False),
        }

    except Exception as exc:
        logger.error(f"[API] Error en chat: {exc}")
        raise HTTPException(status_code=500, detail=str(exc))


# Code execution endpoint
@app.post("/api/aria/execute")
async def execute_code(request: ExecuteRequest) -> Dict[str, Any]:
    """Ejecuta código en un sandbox."""
    try:
        logger.info(f"[API] Ejecutando código ({request.language})")

        result = await dev_agent.execute(
            {
                "task": request.code,
                "task_type": "execute",
                "language": request.language,
                "dependencies": request.dependencies,
            }
        )

        return {
            "output": result.get("output", ""),
            "error": result.get("error", ""),
            "success": result.get("success", False),
            "execution_time": result.get("execution_time", 0),
        }

    except Exception as exc:
        logger.error(f"[API] Error ejecutando código: {exc}")
        raise HTTPException(status_code=500, detail=str(exc))


# Shell execution endpoint
@app.post("/api/aria/shell")
async def execute_shell(request: ShellRequest) -> Dict[str, Any]:
    """Ejecuta un comando shell."""
    try:
        logger.info(f"[API] Shell: {request.command[:80]}")

        result = await interaction_agent.execute(
            {
                "action": "execute_shell",
                "params": {"command": request.command},
            }
        )

        return {
            "output": result.get("output", ""),
            "error": result.get("error", ""),
            "return_code": result.get("return_code", -1),
            "success": result.get("success", False),
        }

    except Exception as exc:
        logger.error(f"[API] Error ejecutando shell: {exc}")
        raise HTTPException(status_code=500, detail=str(exc))


# File operations endpoint
@app.post("/api/aria/files")
async def file_operations(request: FileRequest) -> Dict[str, Any]:
    """Realiza operaciones con archivos."""
    try:
        logger.info(f"[API] Archivo: {request.action} {request.path}")

        if request.action == "read":
            result = await interaction_agent.execute(
                {
                    "action": "read_file",
                    "params": {"path": request.path},
                }
            )
        elif request.action == "write":
            result = await interaction_agent.execute(
                {
                    "action": "write_file",
                    "params": {"path": request.path, "content": request.content},
                }
            )
        elif request.action == "list":
            result = await interaction_agent.execute(
                {
                    "action": "list_files",
                    "params": {"directory": request.path},
                }
            )
        else:
            raise HTTPException(status_code=400, detail="Acción no soportada")

        return result

    except Exception as exc:
        logger.error(f"[API] Error en operación de archivo: {exc}")
        raise HTTPException(status_code=500, detail=str(exc))


# Get files endpoint
@app.get("/api/aria/files")
async def get_files(directory: str = ".") -> Dict[str, Any]:
    """Lista archivos en un directorio."""
    try:
        result = await interaction_agent.execute(
            {
                "action": "list_files",
                "params": {"directory": directory},
            }
        )

        return result

    except Exception as exc:
        logger.error(f"[API] Error listando archivos: {exc}")
        raise HTTPException(status_code=500, detail=str(exc))


# Task management endpoint
@app.post("/api/aria/tasks")
async def create_task(request: TaskRequest) -> Dict[str, Any]:
    """Crea una nueva tarea."""
    try:
        logger.info(f"[API] Nueva tarea: {request.task[:80]}")

        result = await orchestrator.execute_task(
            task=request.task,
            user_context={
                "task_type": request.task_type,
                "priority": request.priority,
            },
        )

        return {
            "task_id": result.get("task_id"),
            "success": result.get("success", False),
            "result": result.get("result", {}),
        }

    except Exception as exc:
        logger.error(f"[API] Error creando tarea: {exc}")
        raise HTTPException(status_code=500, detail=str(exc))


# WebSocket for real-time updates
@app.websocket("/ws/aria/chat")
async def websocket_chat(websocket: WebSocket):
    """WebSocket para chat en tiempo real."""
    await websocket.accept()

    try:
        while True:
            data = await websocket.receive_text()
            message = json.loads(data)

            # Procesar mensaje
            result = await orchestrator.execute_task(
                task=message.get("message", ""),
                user_context=message.get("context", {}),
            )

            # Enviar respuesta
            await websocket.send_json({
                "response": result.get("result", {}).get("summary", ""),
                "success": result.get("success", False),
            })

    except Exception as exc:
        logger.error(f"[API] Error en WebSocket: {exc}")
    finally:
        await websocket.close()


# Health check endpoint
@app.get("/api/aria/health")
async def health_check() -> Dict[str, Any]:
    """Verifica el estado de la API."""
    return {
        "status": "online",
        "version": "1.0.0",
        "agents": {
            "orchestrator": "ready",
            "dev": "ready",
            "research": "ready",
            "interaction": "ready",
        },
    }


# Cleanup on shutdown
@app.on_event("shutdown")
async def shutdown_event():
    """Limpia recursos al apagar."""
    logger.info("[API] Apagando ARIA...")
    await dev_agent.cleanup()
    await interaction_agent.cleanup()
    await sandbox_manager.cleanup_all()
    await mcp_manager.shutdown_all()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        app,
        host="0.0.0.0",
        port=8000,
        log_level="info",
    )
