"""
game_builder.py — Generación de videojuegos completos para ARIA AI.
Genera código, assets prompts, y estructura de proyecto empaquetados en ZIP.

Engines soportados:
  - pygame   (Python — juegos 2D clásicos)
  - phaser   (JavaScript/HTML5 — juegos web, self-contained)
  - godot    (GDScript — motor open source profesional)
"""

from __future__ import annotations

import asyncio
import io
import logging
import zipfile
from typing import Any

logger = logging.getLogger("aria.game_builder")

GENRE_PROMPTS = {
    "platformer": "2D platformer with player movement, jumping, enemies, coins, and level progression",
    "puzzle": "logic puzzle game with levels of increasing difficulty, score tracking",
    "rpg": "top-down RPG with player stats, inventory, NPCs, and combat",
    "shooter": "top-down or side-scrolling shooter with bullets, enemies, lives, and score",
    "arcade": "classic arcade game with simple mechanics, high score, and multiple lives",
    "adventure": "point-and-click adventure with dialogue, inventory puzzles, and story",
}


class GameBuilder:
    """Generates complete game project scaffolds for ARIA AI."""

    async def create_game(
        self,
        name: str,
        genre: str = "arcade",
        description: str = "",
        engine: str = "pygame",
    ) -> dict[str, Any]:
        """
        Generate a complete game project as a ZIP archive.
        Returns zip_bytes, filename, and list of generated files.
        """
        engine = engine.lower()
        genre_desc = GENRE_PROMPTS.get(genre.lower(), genre)
        full_desc = description or genre_desc

        if engine == "pygame":
            return await self._build_pygame(name, genre, full_desc)
        if engine == "phaser":
            return await self._build_phaser(name, genre, full_desc)
        if engine == "godot":
            return await self._build_godot(name, genre, full_desc)
        return await self._build_pygame(name, genre, full_desc)

    async def _build_pygame(self, name: str, genre: str, description: str) -> dict[str, Any]:
        """Generate a complete Pygame project."""
        files_to_gen = [
            ("main.py", "Entry point, game loop, initialization"),
            ("game.py", "Main game class with scene management and game state"),
            ("player.py", "Player class with movement, animations, and collision"),
            ("entities.py", "Enemy and other game entity classes"),
            ("ui.py", "HUD, menu, score display, game over screen"),
            ("constants.py", "Game constants: FPS, colors, screen size, speeds"),
            ("requirements.txt", "Python dependencies (pygame, etc.)"),
        ]

        files, failed = await self._generate_files(
            name, genre, description, "pygame Python", files_to_gen
        )
        files["README.md"] = self._pygame_readme(name, genre)

        return self._pack_zip(name, "pygame", files, len(files_to_gen), failed)

    async def _build_phaser(self, name: str, genre: str, description: str) -> dict[str, Any]:
        """Generate a self-contained Phaser 3 HTML5 game."""
        files_to_gen = [
            ("game.js", "Complete Phaser 3 game — all scenes, physics, input, and game logic"),
            ("scenes/BootScene.js", "Asset preloading scene"),
            ("scenes/MenuScene.js", "Main menu with start button"),
            ("scenes/GameScene.js", "Main gameplay scene with all mechanics"),
            ("scenes/UIScene.js", "HUD overlay: score, lives, timer"),
        ]

        files, failed = await self._generate_files(
            name, genre, description, "Phaser 3 JavaScript", files_to_gen
        )

        # Generate self-contained index.html
        files["index.html"] = self._phaser_index(name)
        files["README.md"] = (
            f"# {name}\n\nA {genre} game built with Phaser 3.\n\nOpen `index.html` in a browser to play.\n"
        )

        return self._pack_zip(name, "phaser", files, len(files_to_gen), failed)

    async def _build_godot(self, name: str, genre: str, description: str) -> dict[str, Any]:
        """Generate a Godot 4 GDScript project."""
        files_to_gen = [
            ("Main.gd", "Main game controller script"),
            ("Player.gd", "Player movement, input handling, and stats"),
            ("Enemy.gd", "Enemy AI and behavior"),
            ("GameUI.gd", "HUD and menu logic"),
            ("GameData.gd", "Global game data singleton"),
        ]

        files, failed = await self._generate_files(
            name, genre, description, "Godot 4 GDScript", files_to_gen
        )
        files["project.godot"] = self._godot_project(name)
        files["README.md"] = (
            f"# {name}\n\nA {genre} game for Godot 4.\n\nOpen `project.godot` in Godot Engine to run.\n"
        )

        return self._pack_zip(name, "godot", files, len(files_to_gen), failed)

    async def _generate_files(
        self,
        name: str,
        genre: str,
        description: str,
        engine_desc: str,
        files_to_gen: list[tuple[str, str]],
    ) -> tuple[dict[str, str], list[str]]:
        """Use AI to generate each game file concurrently.

        Returns (files, failed_paths) — failed_paths lists every file that
        fell back to a stub/TODO/error placeholder instead of real
        AI-generated code, so callers can tell a genuinely-built game apart
        from one that's mostly empty stubs.
        """
        try:
            from apps.core.tools.ai_client import AIModel, get_ai_client

            ai = get_ai_client()
        except Exception:
            return (
                {path: f"# {path}\n# TODO: implement {role}\n" for path, role in files_to_gen},
                [path for path, _role in files_to_gen],
            )

        async def gen(path: str, role: str) -> tuple[str, str, bool]:
            try:
                resp = await ai.complete(
                    system=(
                        f"You are an expert {engine_desc} game developer. "
                        f"Generate complete, working game code. No explanations outside comments. "
                        f"Include all imports and make it immediately runnable."
                    ),
                    user=(
                        f"Game: {name} ({genre})\nDescription: {description}\n\n"
                        f"Generate '{path}': {role}"
                    ),
                    model=AIModel.CODE,
                    max_tokens=1500,
                    temperature=0.3,
                    agent_name="game_builder",
                )
                if resp and resp.success:
                    content = resp.content.strip()
                    failed = False
                else:
                    content = f"# {path}\n# TODO\n"
                    failed = True
                if content.startswith("```"):
                    lines = content.split("\n")
                    content = "\n".join(lines[1:-1] if lines[-1] == "```" else lines[1:])
                return path, content, failed
            except Exception as exc:
                return path, f"# {path}\n# Error generating: {exc}\n", True

        tasks = [gen(path, role) for path, role in files_to_gen]
        results = await asyncio.gather(*tasks)
        files = {path: content for path, content, _failed in results}
        failed_paths = [path for path, _content, failed in results if failed]
        return files, failed_paths

    def _pack_zip(
        self,
        name: str,
        engine: str,
        files: dict[str, str],
        total_generated: int,
        failed: list[str],
    ) -> dict[str, Any]:
        root = name.replace(" ", "-").lower()
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            for filepath, content in files.items():
                zf.writestr(f"{root}/{filepath}", content)
        zip_bytes = buf.getvalue()

        # A game where every generated file is a stub/error placeholder
        # isn't a working game — don't report success for it.
        all_failed = total_generated > 0 and len(failed) >= total_generated
        result: dict[str, Any] = {
            "success": not all_failed,
            "zip_bytes": zip_bytes,
            "filename": f"{root}-{engine}.zip",
            "engine": engine,
            "files": list(files.keys()),
            "size_kb": len(zip_bytes) // 1024,
        }
        if failed:
            result["generation_warnings"] = failed
        if all_failed:
            result["error"] = (
                f"AI code generation failed for all {total_generated} files — "
                "project contains only stub placeholders."
            )
        return result

    def _pygame_readme(self, name: str, genre: str) -> str:
        return (
            f"# {name}\n\nA {genre} game built with Pygame.\n\n"
            "## Setup\n```bash\npip install -r requirements.txt\npython main.py\n```\n"
        )

    def _phaser_index(self, name: str) -> str:
        return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <title>{name}</title>
  <style>* {{ margin: 0; padding: 0; }} canvas {{ display: block; }}</style>
</head>
<body>
  <script src="https://cdn.jsdelivr.net/npm/phaser@3.60.0/dist/phaser.min.js"></script>
  <script type="module">
    import BootScene from './scenes/BootScene.js';
    import MenuScene from './scenes/MenuScene.js';
    import GameScene from './scenes/GameScene.js';
    import UIScene   from './scenes/UIScene.js';

    const config = {{
      type: Phaser.AUTO,
      width: 800, height: 600,
      physics: {{ default: 'arcade', arcade: {{ gravity: {{ y: 300 }}, debug: false }} }},
      scene: [BootScene, MenuScene, GameScene, UIScene],
    }};
    new Phaser.Game(config);
  </script>
</body>
</html>"""

    def _godot_project(self, name: str) -> str:
        return f"""; Engine configuration file.
[application]
config/name="{name}"
run/main_scene="res://Main.tscn"
config/features=PackedStringArray("4.2")

[rendering]
renderer/rendering_method="forward_plus"
"""

    async def generate_game_concept(self, genre: str, target_audience: str) -> dict[str, Any]:
        """Generate a full game design document using AI."""
        try:
            from apps.core.tools.ai_client import AIModel, get_ai_client

            ai = get_ai_client()
            resp = await ai.complete(
                system="You are a game designer. Create concise, actionable game design documents.",
                user=(
                    f"Create a game design document for a {genre} game targeting {target_audience}. "
                    f"Include: concept, core mechanics, progression, art style, monetization."
                ),
                model=AIModel.STRATEGY,
                max_tokens=1000,
                temperature=0.7,
                agent_name="game_concept",
            )
            if resp and resp.success:
                return {"success": True, "concept": resp.content, "genre": genre}
            return {"success": False, "error": "Concept generation failed"}
        except Exception as exc:
            return {"success": False, "error": str(exc)}

    async def create_game_asset_prompts(
        self, game_name: str, style: str = "pixel art"
    ) -> dict[str, Any]:
        """Generate image generation prompts for all game assets."""
        try:
            from apps.core.tools.ai_client import AIModel, get_ai_client

            ai = get_ai_client()
            resp = await ai.complete(
                system="Generate detailed image prompts for AI image generators (FLUX, SDXL).",
                user=(
                    f"Game: {game_name}, Style: {style}\n"
                    f"Generate prompts for: player character, 3 enemy types, background, "
                    f"UI elements (health bar, coins), logo/title screen. "
                    f"Format as JSON dict with asset names as keys."
                ),
                model=AIModel.STRATEGY,
                max_tokens=800,
                temperature=0.6,
                agent_name="game_assets",
            )
            if resp and resp.success:
                return {"success": True, "prompts": resp.content, "style": style}
            return {"success": False, "error": "Asset prompt generation failed"}
        except Exception as exc:
            return {"success": False, "error": str(exc)}
