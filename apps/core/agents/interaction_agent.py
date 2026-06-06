"""
interaction_agent.py — Agente de Interacción para ARIA.

Capacidades de Manus:
- Navegación web con Chromium headless
- Ejecución de comandos shell
- Gestión de archivos
- Interacción con el usuario
- Manejo de credenciales
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional

from apps.core.agents.base_agent import BaseAgent
from apps.core.tools.ai_client import AIModel, get_ai_client

logger = logging.getLogger("aria.interaction_agent")


class InteractionAgent(BaseAgent):
    """Agente de interacción con capacidades de navegación y shell."""

    def __init__(self) -> None:
        super().__init__(
            name="interaction",
            description="Interacción — navegación web, shell, gestión de archivos",
            capabilities=[
                "web_navigation",
                "shell_execution",
                "file_management",
                "user_communication",
                "credential_handling",
            ],
        )
        self.browser_context: Optional[Any] = None
        self.current_directory = Path.cwd()

    async def _execute(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """Punto de entrada principal."""
        action = context.get("action", "")
        params = context.get("params", {})

        logger.info(f"[InteractionAgent] Ejecutando acción: {action}")

        try:
            if action == "navigate":
                return await self._navigate(params.get("url", ""))
            elif action == "execute_shell":
                return await self._execute_shell(params.get("command", ""))
            elif action == "write_file":
                return await self._write_file(params.get("path", ""), params.get("content", ""))
            elif action == "read_file":
                return await self._read_file(params.get("path", ""))
            elif action == "list_files":
                return await self._list_files(params.get("directory", "."))
            elif action == "click_element":
                return await self._click_element(params.get("selector", ""))
            elif action == "fill_form":
                return await self._fill_form(params.get("form_data", {}))
            elif action == "screenshot":
                return await self._take_screenshot(params.get("filename", "screenshot.png"))
            else:
                return {"success": False, "error": f"Acción no reconocida: {action}"}

        except Exception as exc:
            logger.error(f"[InteractionAgent] Error ejecutando acción: {exc}")
            return {"success": False, "error": str(exc)}

    async def _navigate(self, url: str) -> Dict[str, Any]:
        """Navega a una URL usando Chromium headless."""
        try:
            from playwright.async_api import async_playwright

            async with async_playwright() as p:
                browser = await p.chromium.launch(headless=True)
                page = await browser.new_page()

                await page.goto(url, wait_until="networkidle", timeout=30000)

                # Obtener contenido
                content = await page.content()
                title = await page.title()

                # Extraer links
                links = await page.evaluate("""
                    () => Array.from(document.querySelectorAll('a')).map(a => ({
                        text: a.textContent,
                        href: a.href
                    }))
                """)

                await browser.close()

                return {
                    "success": True,
                    "url": url,
                    "title": title,
                    "content_length": len(content),
                    "links_found": len(links),
                    "links": links[:20],  # Top 20 links
                }

        except Exception as exc:
            logger.error(f"[InteractionAgent] Error navegando: {exc}")
            return {"success": False, "error": str(exc)}

    async def _execute_shell(self, command: str) -> Dict[str, Any]:
        """Ejecuta un comando shell."""
        logger.info(f"[InteractionAgent] Ejecutando comando: {command[:80]}")

        try:
            process = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(self.current_directory),
            )

            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=60)

            return {
                "success": process.returncode == 0,
                "command": command,
                "output": stdout.decode("utf-8", errors="ignore"),
                "error": stderr.decode("utf-8", errors="ignore") if stderr else "",
                "return_code": process.returncode,
            }

        except asyncio.TimeoutError:
            return {"success": False, "error": "Comando excedió timeout de 60 segundos"}
        except Exception as exc:
            return {"success": False, "error": str(exc)}

    async def _write_file(self, path: str, content: str) -> Dict[str, Any]:
        """Escribe un archivo."""
        try:
            file_path = self.current_directory / path
            file_path.parent.mkdir(parents=True, exist_ok=True)
            file_path.write_text(content)

            return {
                "success": True,
                "path": str(file_path),
                "size": len(content),
            }

        except Exception as exc:
            logger.error(f"[InteractionAgent] Error escribiendo archivo: {exc}")
            return {"success": False, "error": str(exc)}

    async def _read_file(self, path: str) -> Dict[str, Any]:
        """Lee un archivo."""
        try:
            file_path = self.current_directory / path

            if not file_path.exists():
                return {"success": False, "error": f"Archivo no encontrado: {path}"}

            content = file_path.read_text()

            return {
                "success": True,
                "path": str(file_path),
                "content": content,
                "size": len(content),
            }

        except Exception as exc:
            logger.error(f"[InteractionAgent] Error leyendo archivo: {exc}")
            return {"success": False, "error": str(exc)}

    async def _list_files(self, directory: str) -> Dict[str, Any]:
        """Lista archivos en un directorio."""
        try:
            dir_path = self.current_directory / directory

            if not dir_path.exists():
                return {"success": False, "error": f"Directorio no encontrado: {directory}"}

            files = []
            for item in dir_path.iterdir():
                files.append({
                    "name": item.name,
                    "type": "directory" if item.is_dir() else "file",
                    "size": item.stat().st_size if item.is_file() else 0,
                })

            return {
                "success": True,
                "directory": str(dir_path),
                "files": files,
                "count": len(files),
            }

        except Exception as exc:
            logger.error(f"[InteractionAgent] Error listando archivos: {exc}")
            return {"success": False, "error": str(exc)}

    async def _click_element(self, selector: str) -> Dict[str, Any]:
        """Hace click en un elemento de la página."""
        try:
            from playwright.async_api import async_playwright

            if not self.browser_context:
                return {"success": False, "error": "No hay navegador activo"}

            page = self.browser_context.pages[0] if self.browser_context.pages else None
            if not page:
                return {"success": False, "error": "No hay página activa"}

            await page.click(selector)

            return {
                "success": True,
                "selector": selector,
                "action": "clicked",
            }

        except Exception as exc:
            logger.error(f"[InteractionAgent] Error haciendo click: {exc}")
            return {"success": False, "error": str(exc)}

    async def _fill_form(self, form_data: Dict[str, str]) -> Dict[str, Any]:
        """Rellena un formulario en la página."""
        try:
            from playwright.async_api import async_playwright

            if not self.browser_context:
                return {"success": False, "error": "No hay navegador activo"}

            page = self.browser_context.pages[0] if self.browser_context.pages else None
            if not page:
                return {"success": False, "error": "No hay página activa"}

            filled_fields = []

            for selector, value in form_data.items():
                await page.fill(selector, value)
                filled_fields.append(selector)

            return {
                "success": True,
                "filled_fields": filled_fields,
                "count": len(filled_fields),
            }

        except Exception as exc:
            logger.error(f"[InteractionAgent] Error rellenando formulario: {exc}")
            return {"success": False, "error": str(exc)}

    async def _take_screenshot(self, filename: str) -> Dict[str, Any]:
        """Toma una captura de pantalla."""
        try:
            from playwright.async_api import async_playwright

            if not self.browser_context:
                return {"success": False, "error": "No hay navegador activo"}

            page = self.browser_context.pages[0] if self.browser_context.pages else None
            if not page:
                return {"success": False, "error": "No hay página activa"}

            screenshot_path = self.current_directory / filename
            await page.screenshot(path=str(screenshot_path))

            return {
                "success": True,
                "filename": filename,
                "path": str(screenshot_path),
            }

        except Exception as exc:
            logger.error(f"[InteractionAgent] Error tomando screenshot: {exc}")
            return {"success": False, "error": str(exc)}

    async def change_directory(self, path: str) -> bool:
        """Cambia el directorio de trabajo."""
        try:
            new_path = self.current_directory / path
            if new_path.exists() and new_path.is_dir():
                self.current_directory = new_path
                return True
            return False
        except Exception:
            return False

    async def cleanup(self) -> None:
        """Limpia recursos."""
        if self.browser_context:
            try:
                await self.browser_context.close()
            except Exception as exc:
                logger.error(f"[InteractionAgent] Error limpiando navegador: {exc}")
