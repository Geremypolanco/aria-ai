"""
aria_tools.py — Extensible Tools System for ARIA.

Provides access to:
- Development integrations (GitHub, Docker, deployment)
- Data and API tools
- Media generation
- System utilities
"""

from __future__ import annotations

import json
import logging
import subprocess
from typing import Any

import httpx

from apps.core.integrations.mcp_client import mcp_manager

logger = logging.getLogger("aria.tools")


class GitHubTool:
    """Tool for interacting with GitHub."""

    def __init__(self, token: str = None):
        self.token = token
        self.base_url = "https://api.github.com"
        self.headers = {
            "Authorization": f"token {token}" if token else "",
            "Accept": "application/vnd.github.v3+json",
        }

    async def clone_repo(self, repo_url: str, destination: str) -> dict[str, Any]:
        """Clones a GitHub repository."""
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
    ) -> dict[str, Any]:
        """Creates a pull request on GitHub."""
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

    async def list_issues(self, owner: str, repo: str, state: str = "open") -> dict[str, Any]:
        """Lists issues for a repository."""
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
    """Tool for interacting with Docker."""

    async def build_image(
        self, dockerfile_path: str, tag: str, context: str = "."
    ) -> dict[str, Any]:
        """Builds a Docker image."""
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
        ports: dict[str, int] = None,
        volumes: dict[str, str] = None,
    ) -> dict[str, Any]:
        """Runs a Docker container."""
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
    """Tool for deploying applications."""

    async def deploy_to_vercel(self, project_path: str, token: str) -> dict[str, Any]:
        """Deploys to Vercel."""
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

    async def deploy_to_fly(self, project_path: str, app_name: str) -> dict[str, Any]:
        """Deploys to Fly.io."""
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
    """Advanced tool for web scraping."""

    async def scrape_page(self, url: str, selectors: dict[str, str] = None) -> dict[str, Any]:
        """Extracts data from a web page."""
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(url, timeout=30)

                if response.status_code == 200:
                    # Use BeautifulSoup for parsing
                    from bs4 import BeautifulSoup

                    soup = BeautifulSoup(response.text, "html.parser")
                    data = {}

                    if selectors:
                        for key, selector in selectors.items():
                            elements = soup.select(selector)
                            data[key] = [elem.get_text(strip=True) for elem in elements]
                    else:
                        # Automatic extraction of main content
                        main_content = soup.find("main") or soup.find("article") or soup.body
                        data["content"] = main_content.get_text(strip=True) if main_content else ""

                    return {
                        "success": True,
                        "data": data,
                        "url": url,
                    }
                return {
                    "success": False,
                    "error": f"HTTP {response.status_code}",
                }
        except Exception as exc:
            return {"success": False, "error": str(exc)}

    async def scrape_with_browser(self, url: str, script: str = None) -> dict[str, Any]:
        """Extracts data using a headless browser (Chromium)."""
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
    """Tool for interacting with Zapier through its MCP server."""

    async def call_zapier_action(
        self, action_name: str, arguments: dict[str, Any]
    ) -> dict[str, Any]:
        """Calls a Zapier action using the MCP server."""
        logger.info(f"[ZapierTool] Calling Zapier action: {action_name} with {arguments}")
        result = await mcp_manager.call_tool_on_server(
            "zapier_mcp",  # Name of the Zapier MCP server
            action_name,
            arguments,
        )
        if result:
            return {"success": not result.get("isError", False), "output": result}
        return {
            "success": False,
            "error": "Could not connect to the Zapier MCP server or the action failed.",
        }


class APIDiscoveryTool:
    """Tool for discovering and integrating APIs."""

    async def discover_api(self, service_name: str) -> dict[str, Any]:
        """Discovers information about an API."""
        try:
            # Query OpenAPI Hub or similar
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    "https://api.apis.guru/v1/list.json",
                    timeout=10,
                )

                if response.status_code == 200:
                    apis = response.json()
                    matching_apis = [
                        api for api in apis.values() if service_name.lower() in str(api).lower()
                    ]
                    return {
                        "success": True,
                        "apis": matching_apis[:5],
                    }
                return {"success": False, "error": "Could not access the API Hub"}
        except Exception as exc:
            return {"success": False, "error": str(exc)}

    async def generate_client(
        self, openapi_spec: dict[str, Any], language: str = "python"
    ) -> dict[str, Any]:
        """Generates a client for an API based on an OpenAPI spec."""
        try:
            # Use OpenAPI Generator
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
    """Central registry of available tools."""

    def __init__(self):
        from apps.core.tools.infra_tools import InfraTools
        from apps.core.tools.viral_analyzer import ViralAnalyzer

        self.tools: dict[str, Any] = {
            "github": GitHubTool(),
            "docker": DockerTool(),
            "deployment": DeploymentTool(),
            "web_scraping": WebScrapingTool(),
            "api_discovery": APIDiscoveryTool(),
            "zapier": ZapierTool(),
            "infra": InfraTools(),
            "viral": ViralAnalyzer(),
        }

    def get_tool(self, tool_name: str) -> Any | None:
        """Gets a tool by name."""
        return self.tools.get(tool_name)

    def list_tools(self) -> list[str]:
        """Lists all available tools."""
        return list(self.tools.keys())

    def register_tool(self, name: str, tool: Any) -> None:
        """Registers a new tool."""
        self.tools[name] = tool
        logger.info(f"[Tools] Tool registered: {name}")


# Global registry instance
tool_registry = ToolRegistry()
