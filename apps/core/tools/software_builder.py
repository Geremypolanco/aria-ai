"""
software_builder.py — Generación de proyectos de software completos y production-ready.
Genera múltiples archivos estructurados, empaquetados en ZIP.
"""

from __future__ import annotations

import asyncio
import io
import logging
import zipfile
from typing import Any

logger = logging.getLogger("aria.software_builder")

# Stack → file structure templates
STACK_STRUCTURES: dict[str, list[dict]] = {
    "fastapi": [
        {"path": "main.py", "role": "FastAPI application entry point with routes"},
        {"path": "models.py", "role": "Pydantic models and schemas"},
        {"path": "config.py", "role": "Settings using pydantic-settings"},
        {"path": "requirements.txt", "role": "Python dependencies list"},
        {"path": "Dockerfile", "role": "Docker container definition"},
        {"path": ".gitignore", "role": "Git ignore file for Python"},
        {"path": "README.md", "role": "Project documentation"},
        {"path": "tests/test_main.py", "role": "Pytest test suite"},
    ],
    "flask": [
        {"path": "app.py", "role": "Flask application"},
        {"path": "models.py", "role": "SQLAlchemy models"},
        {"path": "requirements.txt", "role": "Python dependencies"},
        {"path": ".gitignore", "role": "Git ignore file for Python"},
        {"path": "README.md", "role": "Project documentation"},
    ],
    "react": [
        {"path": "package.json", "role": "Node.js project manifest with React dependencies"},
        {"path": "src/App.tsx", "role": "Main React application component"},
        {"path": "src/index.tsx", "role": "React app entry point"},
        {"path": "src/components/index.ts", "role": "Component exports barrel"},
        {"path": "tailwind.config.js", "role": "Tailwind CSS configuration"},
        {"path": ".gitignore", "role": "Git ignore for Node.js"},
        {"path": "README.md", "role": "Project documentation"},
    ],
    "nextjs": [
        {"path": "package.json", "role": "Next.js project manifest"},
        {"path": "pages/index.tsx", "role": "Next.js home page"},
        {"path": "pages/_app.tsx", "role": "Next.js app wrapper"},
        {"path": "pages/api/health.ts", "role": "Health check API route"},
        {"path": "components/Layout.tsx", "role": "Page layout wrapper"},
        {"path": "tailwind.config.js", "role": "Tailwind CSS configuration"},
        {"path": ".gitignore", "role": "Git ignore for Node.js"},
        {"path": "README.md", "role": "Project documentation"},
    ],
    "cli": [
        {"path": "main.py", "role": "CLI entry point using Click or Typer"},
        {"path": "commands/", "role": "Command modules"},
        {"path": "utils.py", "role": "Utility functions"},
        {"path": "requirements.txt", "role": "Python dependencies"},
        {"path": ".gitignore", "role": "Git ignore for Python"},
        {"path": "README.md", "role": "CLI documentation with usage examples"},
    ],
    "discord_bot": [
        {"path": "bot.py", "role": "Discord bot entry point with commands"},
        {"path": "cogs/general.py", "role": "General commands cog"},
        {"path": "config.py", "role": "Bot configuration"},
        {"path": "requirements.txt", "role": "Python dependencies including discord.py"},
        {"path": ".env.example", "role": "Environment variables template"},
        {"path": ".gitignore", "role": "Git ignore for Python"},
        {"path": "README.md", "role": "Bot documentation and setup guide"},
    ],
    "telegram_bot": [
        {"path": "bot.py", "role": "Telegram bot using python-telegram-bot"},
        {"path": "handlers.py", "role": "Message and command handlers"},
        {"path": "config.py", "role": "Bot settings"},
        {"path": "requirements.txt", "role": "Python dependencies"},
        {"path": ".env.example", "role": "Environment variables template"},
        {"path": ".gitignore", "role": "Git ignore for Python"},
        {"path": "README.md", "role": "Setup and deployment guide"},
    ],
}


class SoftwareBuilder:
    """Generates complete, production-ready software projects as ZIP archives."""

    async def build_project(
        self,
        name: str,
        description: str,
        stack: str = "fastapi",
        requirements_text: str = "",
    ) -> dict[str, Any]:
        """
        Generate a complete project scaffold.
        Returns ZIP bytes containing all project files.
        """
        stack = stack.lower()
        structure = STACK_STRUCTURES.get(stack, STACK_STRUCTURES["fastapi"])

        try:
            from apps.core.tools.ai_client import AIModel, get_ai_client

            ai = get_ai_client()

            files: dict[str, str] = {}

            # Generate each file concurrently
            async def gen_file(file_def: dict) -> tuple[str, str]:
                path = file_def["path"]
                role = file_def["role"]
                if path.endswith("/"):
                    return path + ".gitkeep", ""

                ext = path.split(".")[-1] if "." in path else "txt"
                lang_map = {
                    "py": "Python",
                    "tsx": "TypeScript React",
                    "ts": "TypeScript",
                    "js": "JavaScript",
                    "json": "JSON",
                    "md": "Markdown",
                    "txt": "text",
                    "toml": "TOML",
                    "yml": "YAML",
                    "yaml": "YAML",
                    "example": "shell environment",
                }
                lang = lang_map.get(ext, ext)

                resp = await ai.complete(
                    system=(
                        f"You are a senior {stack} developer. "
                        f"Generate production-ready {lang} code only. "
                        f"No explanations outside comments. Include error handling, type hints where applicable."
                    ),
                    user=(
                        f"Project: {name}\nDescription: {description}\n"
                        f"Stack: {stack}\nExtra requirements: {requirements_text}\n\n"
                        f"Generate the file '{path}' which is: {role}. "
                        f"Make it complete and production-ready."
                    ),
                    model=AIModel.CODE,
                    max_tokens=1500,
                    temperature=0.2,
                    agent_name="software_builder",
                )
                content = (
                    resp.content.strip()
                    if (resp and resp.success)
                    else f"# {path}\n# TODO: implement\n"
                )
                # Strip markdown code fences if present
                if content.startswith("```"):
                    lines = content.split("\n")
                    content = "\n".join(lines[1:-1] if lines[-1] == "```" else lines[1:])
                return path, content

            tasks = [gen_file(f) for f in structure]
            results = await asyncio.gather(*tasks, return_exceptions=True)

            for r in results:
                if isinstance(r, tuple):
                    files[r[0]] = r[1]

            # Pack into ZIP
            zip_buffer = io.BytesIO()
            root = name.replace(" ", "-").lower()
            with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
                for filepath, content in files.items():
                    zf.writestr(f"{root}/{filepath}", content)

            zip_bytes = zip_buffer.getvalue()
            return {
                "success": True,
                "zip_bytes": zip_bytes,
                "filename": f"{root}.zip",
                "files": list(files.keys()),
                "stack": stack,
                "size_kb": len(zip_bytes) // 1024,
            }

        except Exception as exc:
            logger.error("[SoftwareBuilder] build_project error: %s", exc, exc_info=True)
            return {"success": False, "error": str(exc)}

    async def generate_module(self, description: str, language: str = "python") -> dict[str, Any]:
        """Generate a single, well-structured module."""
        try:
            from apps.core.tools.ai_client import AIModel, get_ai_client

            ai = get_ai_client()
            resp = await ai.complete(
                system=f"Expert {language} developer. Generate production-ready code only. No markdown fences.",
                user=f"Create a complete {language} module: {description}",
                model=AIModel.CODE,
                max_tokens=2000,
                temperature=0.2,
                agent_name="module_gen",
            )
            if resp and resp.success:
                return {"success": True, "code": resp.content, "language": language}
            return {"success": False, "error": "Module generation failed"}
        except Exception as exc:
            return {"success": False, "error": str(exc)}

    async def generate_api(
        self, endpoints_description: str, auth_type: str = "jwt"
    ) -> dict[str, Any]:
        """Generate a complete FastAPI REST API from endpoint descriptions."""
        try:
            from apps.core.tools.ai_client import AIModel, get_ai_client

            ai = get_ai_client()
            resp = await ai.complete(
                system=(
                    "Senior FastAPI architect. Generate complete, working FastAPI code "
                    "with proper Pydantic models, error handling, status codes, and docstrings. "
                    "No markdown fences."
                ),
                user=(
                    f"Create a FastAPI REST API with {auth_type} authentication.\n"
                    f"Endpoints: {endpoints_description}"
                ),
                model=AIModel.CODE,
                max_tokens=2500,
                temperature=0.2,
                agent_name="api_gen",
            )
            if resp and resp.success:
                return {"success": True, "code": resp.content, "auth": auth_type}
            return {"success": False, "error": "API generation failed"}
        except Exception as exc:
            return {"success": False, "error": str(exc)}
