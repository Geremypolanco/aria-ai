"""
interaction_agent.py — Interaction Agent for ARIA.

Manus-style capabilities:
- Web navigation with headless Chromium
- Shell command execution
- File management
- User interaction
- Credential handling
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any

from apps.core.agents.base_agent import BaseAgent

logger = logging.getLogger("aria.interaction_agent")


class InteractionAgent(BaseAgent):
    """Interaction agent with web navigation and shell capabilities."""

    def __init__(self) -> None:
        super().__init__(
            name="interaction",
            description="Interaction — web navigation, shell, file management",
            capabilities=[
                "web_navigation",
                "shell_execution",
                "file_management",
                "user_communication",
                "credential_handling",
            ],
        )
        self.browser_context: Any | None = None
        self.current_directory = Path.cwd()

    async def _execute(self, context: dict[str, Any]) -> dict[str, Any]:
        """Main entry point."""
        action = context.get("action", "")
        params = context.get("params", {})

        logger.info(f"[InteractionAgent] Running action: {action}")

        try:
            if action == "navigate":
                return await self._navigate(params.get("url", ""))
            if action == "execute_shell":
                return await self._execute_shell(params.get("command", ""))
            if action == "write_file":
                return await self._write_file(params.get("path", ""), params.get("content", ""))
            if action == "read_file":
                return await self._read_file(params.get("path", ""))
            if action == "list_files":
                return await self._list_files(params.get("directory", "."))
            if action == "click_element":
                return await self._click_element(params.get("selector", ""))
            if action == "fill_form":
                return await self._fill_form(params.get("form_data", {}))
            if action == "screenshot":
                return await self._take_screenshot(params.get("filename", "screenshot.png"))
            return {"success": False, "error": f"Unrecognized action: {action}"}

        except Exception as exc:
            logger.error(f"[InteractionAgent] Error running action: {exc}")
            return {"success": False, "error": str(exc)}

    async def _navigate(self, url: str) -> dict[str, Any]:
        """Navigates to a URL using headless Chromium."""
        try:
            from playwright.async_api import async_playwright

            async with async_playwright() as p:
                browser = await p.chromium.launch(headless=True)
                page = await browser.new_page()

                await page.goto(url, wait_until="networkidle", timeout=30000)

                # Get content
                content = await page.content()
                title = await page.title()

                # Extract links
                links = await page.evaluate(
                    """
                    () => Array.from(document.querySelectorAll('a')).map(a => ({
                        text: a.textContent,
                        href: a.href
                    }))
                """
                )

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
            logger.error(f"[InteractionAgent] Error navigating: {exc}")
            return {"success": False, "error": str(exc)}

    async def _execute_shell(self, command: str) -> dict[str, Any]:
        """Executes a shell command."""
        logger.info(f"[InteractionAgent] Running command: {command[:80]}")

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

        except TimeoutError:
            return {"success": False, "error": "Command exceeded the 60-second timeout"}
        except Exception as exc:
            return {"success": False, "error": str(exc)}

    async def _write_file(self, path: str, content: str) -> dict[str, Any]:
        """Writes a file."""
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
            logger.error(f"[InteractionAgent] Error writing file: {exc}")
            return {"success": False, "error": str(exc)}

    async def _read_file(self, path: str) -> dict[str, Any]:
        """Reads a file."""
        try:
            file_path = self.current_directory / path

            if not file_path.exists():
                return {"success": False, "error": f"File not found: {path}"}

            content = file_path.read_text()

            return {
                "success": True,
                "path": str(file_path),
                "content": content,
                "size": len(content),
            }

        except Exception as exc:
            logger.error(f"[InteractionAgent] Error reading file: {exc}")
            return {"success": False, "error": str(exc)}

    async def _list_files(self, directory: str) -> dict[str, Any]:
        """Lists files in a directory."""
        try:
            dir_path = self.current_directory / directory

            if not dir_path.exists():
                return {"success": False, "error": f"Directory not found: {directory}"}

            files = []
            for item in dir_path.iterdir():
                files.append(
                    {
                        "name": item.name,
                        "type": "directory" if item.is_dir() else "file",
                        "size": item.stat().st_size if item.is_file() else 0,
                    }
                )

            return {
                "success": True,
                "directory": str(dir_path),
                "files": files,
                "count": len(files),
            }

        except Exception as exc:
            logger.error(f"[InteractionAgent] Error listing files: {exc}")
            return {"success": False, "error": str(exc)}

    async def _click_element(self, selector: str) -> dict[str, Any]:
        """Clicks an element on the page."""
        try:

            if not self.browser_context:
                return {"success": False, "error": "No active browser"}

            page = self.browser_context.pages[0] if self.browser_context.pages else None
            if not page:
                return {"success": False, "error": "No active page"}

            await page.click(selector)

            return {
                "success": True,
                "selector": selector,
                "action": "clicked",
            }

        except Exception as exc:
            logger.error(f"[InteractionAgent] Error clicking: {exc}")
            return {"success": False, "error": str(exc)}

    async def _fill_form(self, form_data: dict[str, str]) -> dict[str, Any]:
        """Fills out a form on the page."""
        try:

            if not self.browser_context:
                return {"success": False, "error": "No active browser"}

            page = self.browser_context.pages[0] if self.browser_context.pages else None
            if not page:
                return {"success": False, "error": "No active page"}

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
            logger.error(f"[InteractionAgent] Error filling form: {exc}")
            return {"success": False, "error": str(exc)}

    async def _take_screenshot(self, filename: str) -> dict[str, Any]:
        """Takes a screenshot."""
        try:

            if not self.browser_context:
                return {"success": False, "error": "No active browser"}

            page = self.browser_context.pages[0] if self.browser_context.pages else None
            if not page:
                return {"success": False, "error": "No active page"}

            screenshot_path = self.current_directory / filename
            await page.screenshot(path=str(screenshot_path))

            return {
                "success": True,
                "filename": filename,
                "path": str(screenshot_path),
            }

        except Exception as exc:
            logger.error(f"[InteractionAgent] Error taking screenshot: {exc}")
            return {"success": False, "error": str(exc)}

    async def change_directory(self, path: str) -> bool:
        """Changes the working directory."""
        try:
            new_path = self.current_directory / path
            if new_path.exists() and new_path.is_dir():
                self.current_directory = new_path
                return True
            return False
        except Exception:
            return False

    async def cleanup(self) -> None:
        """Cleans up resources."""
        if self.browser_context:
            try:
                await self.browser_context.close()
            except Exception as exc:
                logger.error(f"[InteractionAgent] Error cleaning up browser: {exc}")
