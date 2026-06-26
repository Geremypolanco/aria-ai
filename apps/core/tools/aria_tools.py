"""
aria_tools.py — Sistema de Herramientas Extensible para ARIA.

Proporciona acceso a:
- Integraciones de desarrollo (GitHub, Docker, despliegue)
- Herramientas de datos y APIs
- Generación de medios
- Utilidades del sistema
"""

from __future__ import annotations

import asyncio
import json
import logging
import subprocess
from typing import Any, Dict, List, Optional

from apps.core.integrations.mcp_client import mcp_manager

import httpx

logger = logging.getLogger("aria.tools")


class GitHubTool:
    """Herramienta para interactuar con GitHub."""

    def __init__(self, token: str = None):
        self.token = token
        self.base_url = "https://api.github.com"
        self.headers = {
            "Authorization": f"token {token}" if token else "",
            "Accept": "application/vnd.github.v3+json",
        }

    async def clone_repo(self, repo_url: str, destination: str) -> Dict[str, Any]:
        """Clona un repositorio de GitHub."""
        try:
            result = subprocess.run(
                ["git", "clone", repo_url, destination],
                capture_output=True,
                text=True,
                timeout=60,
            )
            return {
                "success": result.returncode == 0,
                "output": result.stdout,
                "error": result.stderr if result.returncode != 0 else "",
            }
        except Exception as exc:
            return {"success": False, "error": str(exc)}

    async def create_pull_request(
        self,
        owner: str,
        repo: str,
        title: str,
        body: str,
        head: str,
        base: str = "main",
    ) -> Dict[str, Any]:
        """Crea un pull request en GitHub."""
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    f"{self.base_url}/repos/{owner}/{repo}/pulls",
                    headers=self.headers,
                    json={
                        "title": title,
                        "body": body,
                        "head": head,
                        "base": base,
                    },
                )
                return {
                    "success": response.status_code == 201,
                    "data": response.json() if response.status_code == 201 else {},
                    "error": response.text if response.status_code != 201 else "",
                }
        except Exception as exc:
            return {"success": False, "error": str(exc)}

    async def list_issues(self, owner: str, repo: str, state: str = "open") -> Dict[str, Any]:
        """Lista issues de un repositorio."""
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    f"{self.base_url}/repos/{owner}/{repo}/issues",
                    headers=self.headers,
                    params={"state": state},
                )
                return {
                    "success": response.status_code == 200,
                    "data": response.json() if response.status_code == 200 else [],
                }
        except Exception as exc:
            return {"success": False, "error": str(exc), "data": []}


class DockerTool:
    """Herramienta para interactuar con Docker."""

    async def build_image(self, dockerfile_path: str, tag: str, context: str = ".") -> Dict[str, Any]:
        """Construye una imagen Docker."""
        try:
            result = subprocess.run(
                ["docker", "build", "-t", tag, "-f", dockerfile_path, context],
                capture_output=True,
                text=True,
                timeout=300,
            )
            return {
                "success": result.returncode == 0,
                "output": result.stdout,
                "error": result.stderr if result.returncode != 0 else "",
            }
        except Exception as exc:
            return {"success": False, "error": str(exc)}

    async def run_container(
        self,
        image: str,
        command: str = None,
        ports: Dict[str, int] = None,
        volumes: Dict[str, str] = None,
    ) -> Dict[str, Any]:
        """Ejecuta un contenedor Docker."""
        try:
            cmd = ["docker", "run"]

            if ports:
                for container_port, host_port in ports.items():
                    cmd.extend(["-p", f"{host_port}:{container_port}"])

            if volumes:
                for host_path, container_path in volumes.items():
                    cmd.extend(["-v", f"{host_path}:{container_path}"])

            cmd.append(image)

            if command:
                cmd.extend(command.split())

            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=60,
            )

            return {
                "success": result.returncode == 0,
                "output": result.stdout,
                "error": result.stderr if result.returncode != 0 else "",
            }
        except Exception as exc:
            return {"success": False, "error": str(exc)}


class DeploymentTool:
    """Herramienta para desplegar aplicaciones."""

    async def deploy_to_vercel(self, project_path: str, token: str) -> Dict[str, Any]:
        """Despliega a Vercel."""
        try:
            result = subprocess.run(
                ["vercel", "--token", token, "--prod"],
                cwd=project_path,
                capture_output=True,
                text=True,
                timeout=300,
            )
            return {
                "success": result.returncode == 0,
                "output": result.stdout,
                "error": result.stderr if result.returncode != 0 else "",
            }
        except Exception as exc:
            return {"success": False, "error": str(exc)}

    async def deploy_to_fly(self, project_path: str, app_name: str) -> Dict[str, Any]:
        """Despliega a Fly.io."""
        try:
            result = subprocess.run(
                ["flyctl", "deploy", "--app", app_name],
                cwd=project_path,
                capture_output=True,
                text=True,
                timeout=300,
            )
            return {
                "success": result.returncode == 0,
                "output": result.stdout,
                "error": result.stderr if result.returncode != 0 else "",
            }
        except Exception as exc:
            return {"success": False, "error": str(exc)}


class WebScrapingTool:
    """Herramienta avanzada para web scraping."""

    async def scrape_page(self, url: str, selectors: Dict[str, str] = None) -> Dict[str, Any]:
        """Extrae datos de una página web."""
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(url, timeout=30)

                if response.status_code == 200:
                    # Usar BeautifulSoup para parsing
                    from bs4 import BeautifulSoup

                    soup = BeautifulSoup(response.text, "html.parser")
                    data = {}

                    if selectors:
                        for key, selector in selectors.items():
                            elements = soup.select(selector)
                            data[key] = [elem.get_text(strip=True) for elem in elements]
                    else:
                        # Extracción automática de contenido principal
                        main_content = soup.find("main") or soup.find("article") or soup.body
                        data["content"] = main_content.get_text(strip=True) if main_content else ""

                    return {
                        "success": True,
                        "data": data,
                        "url": url,
                    }
                else:
                    return {
                        "success": False,
                        "error": f"HTTP {response.status_code}",
                    }
        except Exception as exc:
            return {"success": False, "error": str(exc)}

    async def scrape_with_browser(self, url: str, script: str = None) -> Dict[str, Any]:
        """Extrae datos usando navegador headless (Chromium)."""
        try:
            from playwright.async_api import async_playwright

            async with async_playwright() as p:
                browser = await p.chromium.launch()
                page = await browser.new_page()
                await page.goto(url, wait_until="networkidle")

                if script:
                    result = await page.evaluate(script)
                else:
                    result = await page.content()

                await browser.close()

                return {
                    "success": True,
                    "data": result,
                    "url": url,
                }
        except Exception as exc:
            return {"success": False, "error": str(exc)}


class ZapierTool:
    """Herramienta para interactuar con Zapier a través de su servidor MCP."""

    async def call_zapier_action(self, action_name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Llama a una acción de Zapier usando el servidor MCP."""
        logger.info(f"[ZapierTool] Llamando acción Zapier: {action_name} con {arguments}")
        result = await mcp_manager.call_tool_on_server(
            "zapier_mcp",  # Nombre del servidor MCP de Zapier
            action_name,
            arguments,
        )
        if result:
            return {"success": not result.get("isError", False), "output": result}
        return {"success": False, "error": "No se pudo conectar con el servidor MCP de Zapier o la acción falló."}


class APIDiscoveryTool:
    """Herramienta para descubrir e integrar APIs."""

    async def discover_api(self, service_name: str) -> Dict[str, Any]:
        """Descubre información sobre una API."""
        try:
            # Consultar OpenAPI Hub o similar
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    f"https://api.apis.guru/v1/list.json",
                    timeout=10,
                )

                if response.status_code == 200:
                    apis = response.json()
                    matching_apis = [
                        api for api in apis.values()
                        if service_name.lower() in str(api).lower()
                    ]
                    return {
                        "success": True,
                        "apis": matching_apis[:5],
                    }
                else:
                    return {"success": False, "error": "No se pudo acceder al API Hub"}
        except Exception as exc:
            return {"success": False, "error": str(exc)}

    async def generate_client(self, openapi_spec: Dict[str, Any], language: str = "python") -> Dict[str, Any]:
        """Genera un cliente para una API basado en OpenAPI spec."""
        try:
            # Usar OpenAPI Generator
            spec_json = json.dumps(openapi_spec)

            result = subprocess.run(
                [
                    "openapi-generator-cli",
                    "generate",
                    "-i",
                    "-",
                    "-g",
                    language,
                    "-o",
                    "/tmp/generated_client",
                ],
                input=spec_json,
                capture_output=True,
                text=True,
                timeout=60,
            )

            return {
                "success": result.returncode == 0,
                "output": result.stdout,
                "error": result.stderr if result.returncode != 0 else "",
            }
        except Exception as exc:
            return {"success": False, "error": str(exc)}


class ToolRegistry:
    """Registro central de herramientas disponibles."""

    def __init__(self):
        from apps.core.tools.infra_tools import InfraTools
        from apps.core.tools.viral_analyzer import ViralAnalyzer
        self.tools: Dict[str, Any] = {
            "github": GitHubTool(),
            "docker": DockerTool(),
            "deployment": DeploymentTool(),
            "web_scraping": WebScrapingTool(),
            "api_discovery": APIDiscoveryTool(),
            "zapier": ZapierTool(),
            "infra": InfraTools(),
            "viral": ViralAnalyzer(),
        }

    def get_tool(self, tool_name: str) -> Optional[Any]:
        """Obtiene una herramienta por nombre."""
        return self.tools.get(tool_name)

    def list_tools(self) -> List[str]:
        """Lista todas las herramientas disponibles."""
        return list(self.tools.keys())

    def register_tool(self, name: str, tool: Any) -> None:
        """Registra una nueva herramienta."""
        self.tools[name] = tool
        logger.info(f"[Tools] Herramienta registrada: {name}")


# Instancia global del registro
tool_registry = ToolRegistry()
