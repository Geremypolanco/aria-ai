"""
computer_agent.py — Agente de "Uso de Computadora" para ARIA (estilo Manus AI).

Base técnica para que ARIA controle una computadora de forma autónoma usando la
API nativa **Computer Use** de Anthropic sobre un entorno aislado (sandbox): un
navegador Chromium controlado con Playwright.

Flujo (Agent Loop con retroalimentación visual):
  1. ARIA recibe una tarea en lenguaje natural.
  2. Claude (modelo multimodal) mira una captura de pantalla y decide una acción
     física con coordenadas (X, Y): mover el ratón, hacer clic, escribir, etc.
  3. Ejecutamos esa acción en el sandbox (Playwright).
  4. Tomamos una nueva captura, la convertimos a Base64 y la inyectamos de vuelta
     como `tool_result` en el historial de la API.
  5. Se repite hasta que Claude termina (`stop_reason == "end_turn"`).

Todo es asíncrono (`async/await`) para poder ejecutarse en segundo plano dentro
de una cola de tareas (patrón Manus).

Sin claves / sin gastar tokens:
  - `BrowserComputer` y el ejecutor de acciones funcionan 100% offline.
  - `ComputerUseAgent.run_mock()` ejecuta una secuencia de acciones guionizada
    contra el navegador real y prueba TODO el bucle de retroalimentación visual
    (screenshot → base64 → tool_result) sin llamar a Anthropic.
  - `ComputerUseAgent.run()` sólo usa la API de Anthropic si hay ANTHROPIC_API_KEY.

Notas sobre versiones:
  El usuario pidió `claude-3-5-sonnet` + `computer_20241022`. Ese modelo está
  retirado; usamos por defecto el equivalente estable actual (`claude-sonnet-5`
  + herramienta `computer_20251124`, beta `computer-use-2025-11-24`). Todo es
  configurable con las constantes de abajo.
"""

from __future__ import annotations

import base64
import glob
import logging
import os
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger("aria.computer_agent")

# ── Configuración del sandbox y del modelo ────────────────────────
DISPLAY_WIDTH = 1024
DISPLAY_HEIGHT = 768

# Modelo multimodal + herramienta Computer Use (versiones estables actuales).
MODEL = "claude-sonnet-5"
COMPUTER_TOOL_TYPE = "computer_20251124"
COMPUTER_BETA = "computer-use-2025-11-24"


def _find_chromium() -> str | None:
    """Localiza un binario de Chromium preinstalado (fallback si la versión de
    Playwright no coincide con la build descargada). Se puede forzar con
    ARIA_CHROMIUM_PATH."""
    env = os.getenv("ARIA_CHROMIUM_PATH")
    if env and os.path.exists(env):
        return env
    root = os.getenv("PLAYWRIGHT_BROWSERS_PATH", "/opt/pw-browsers")
    matches = sorted(glob.glob(f"{root}/chromium-*/chrome-linux/chrome"))
    return matches[-1] if matches else None


SYSTEM_PROMPT = (
    "Eres ARIA operando una computadora a través de un navegador web. "
    "Observa la captura de pantalla, razona el siguiente paso y usa la "
    "herramienta 'computer' para actuar (mover, clic, escribir, teclas). "
    "Trabaja paso a paso; toma una captura cuando necesites ver el estado."
)


def computer_tool_def(width: int = DISPLAY_WIDTH, height: int = DISPLAY_HEIGHT) -> dict[str, Any]:
    """Definición de la herramienta nativa Computer Use para el payload de Claude."""
    return {
        "type": COMPUTER_TOOL_TYPE,
        "name": "computer",
        "display_width_px": width,
        "display_height_px": height,
        "display_number": 1,
    }


# ──────────────────────────────────────────────────────────────────
# Sandbox: un navegador Chromium como "computadora"
# ──────────────────────────────────────────────────────────────────
class BrowserComputer:
    """Entorno aislado controlado por Playwright que ejecuta acciones físicas.

    Traduce las acciones de la API Computer Use (basadas en coordenadas) a
    operaciones reales del navegador y produce capturas de pantalla en Base64.
    """

    def __init__(
        self,
        width: int = DISPLAY_WIDTH,
        height: int = DISPLAY_HEIGHT,
        headless: bool = True,
        start_url: str = "about:blank",
    ):
        self.width = width
        self.height = height
        self.headless = headless
        self.start_url = start_url
        self._pw: Any = None
        self._browser: Any = None
        self._page: Any = None
        self._cursor: tuple[int, int] = (width // 2, height // 2)

    async def start(self) -> None:
        """Levanta el navegador aislado a la resolución estándar."""
        from playwright.async_api import async_playwright

        self._pw = await async_playwright().start()
        launch_kwargs: dict[str, Any] = {"headless": self.headless}
        try:
            self._browser = await self._pw.chromium.launch(**launch_kwargs)
        except Exception as exc:  # noqa: BLE001 — fallback al binario preinstalado
            chromium = _find_chromium()
            logger.warning(
                "[computer] launch por defecto falló (%s); uso executable_path=%s", exc, chromium
            )
            self._browser = await self._pw.chromium.launch(
                executable_path=chromium, **launch_kwargs
            )
        context = await self._browser.new_context(
            viewport={"width": self.width, "height": self.height}
        )
        self._page = await context.new_page()
        if self.start_url and self.start_url != "about:blank":
            try:
                await self._page.goto(self.start_url)
            except Exception as exc:  # noqa: BLE001 — egress puede estar restringido
                logger.warning("[computer] no se pudo abrir %s: %s", self.start_url, exc)
        logger.info("[computer] sandbox listo (%dx%d)", self.width, self.height)

    # ── acciones físicas basadas en coordenadas ──────────────────
    async def goto(self, url: str) -> None:
        await self._page.goto(url)

    async def load_html(self, html: str) -> None:
        """Renderiza HTML local en el navegador (útil sin acceso a red)."""
        await self._page.set_content(html, wait_until="load")

    async def move(self, x: int, y: int) -> None:
        self._cursor = (x, y)
        await self._page.mouse.move(x, y)

    async def click(self, x: int, y: int, button: str = "left") -> None:
        self._cursor = (x, y)
        await self._page.mouse.click(x, y, button=button)

    async def double_click(self, x: int, y: int) -> None:
        self._cursor = (x, y)
        await self._page.mouse.dblclick(x, y)

    async def type_text(self, text: str) -> None:
        await self._page.keyboard.type(text)

    async def key(self, combo: str) -> None:
        # Computer Use usa notación xdotool ("Return", "ctrl+a"); Playwright usa "+".
        mapped = "+".join(part.capitalize() if len(part) > 1 else part for part in combo.split("+"))
        await self._page.keyboard.press(mapped)

    async def scroll(self, x: int, y: int, dx: int = 0, dy: int = 0) -> None:
        await self._page.mouse.move(x, y)
        await self._page.mouse.wheel(dx, dy)

    async def screenshot_b64(self) -> str:
        """Captura la pantalla y la devuelve como PNG en Base64."""
        png = await self._page.screenshot(type="png")
        return base64.b64encode(png).decode("ascii")

    async def close(self) -> None:
        try:
            if self._browser:
                await self._browser.close()
            if self._pw:
                await self._pw.stop()
        except Exception as exc:  # noqa: BLE001
            logger.warning("[computer] error al cerrar: %s", exc)

    # ── dispatcher de una acción de la API Computer Use ──────────
    async def execute(self, action_input: dict[str, Any]) -> dict[str, Any]:
        """Ejecuta una acción `computer` y devuelve el resultado para el tool_result.

        Devuelve {"image_b64": ...} para acciones que producen una captura, o
        {"text": ...} para acciones sin imagen.
        """
        action = action_input.get("action")
        coord = action_input.get("coordinate") or [None, None]
        x, y = (coord + [None, None])[:2]

        if action == "screenshot":
            return {"image_b64": await self.screenshot_b64()}
        if action == "mouse_move":
            await self.move(int(x), int(y))
        elif action in ("left_click", "right_click", "middle_click"):
            button = {"left_click": "left", "right_click": "right", "middle_click": "middle"}[
                action
            ]
            await self.click(int(x), int(y), button=button)
        elif action == "double_click":
            await self.double_click(int(x), int(y))
        elif action == "type":
            await self.type_text(action_input.get("text", ""))
        elif action == "key":
            await self.key(action_input.get("text", ""))
        elif action == "scroll":
            amount = int(action_input.get("scroll_amount", 3)) * 100
            direction = action_input.get("scroll_direction", "down")
            dy = amount if direction == "down" else -amount if direction == "up" else 0
            dx = amount if direction == "right" else -amount if direction == "left" else 0
            await self.scroll(int(x or self._cursor[0]), int(y or self._cursor[1]), dx, dy)
        elif action in ("cursor_position", "wait"):
            pass  # sin efecto físico; devolvemos captura igualmente
        else:
            return {"text": f"acción no soportada: {action}"}

        # Tras cualquier acción física devolvemos una captura fresca (feedback visual).
        return {"image_b64": await self.screenshot_b64()}


# ──────────────────────────────────────────────────────────────────
# Agente: bucle de ejecución con Claude (Computer Use)
# ──────────────────────────────────────────────────────────────────
@dataclass
class AgentStep:
    action: dict[str, Any]
    kind: str  # "image" | "text"


@dataclass
class AgentRun:
    final_text: str
    steps: list[AgentStep] = field(default_factory=list)
    stop_reason: str | None = None


def _tool_result_block(tool_use_id: str, result: dict[str, Any]) -> dict[str, Any]:
    """Convierte el resultado de una acción en un bloque tool_result de Anthropic.

    Una captura se inyecta como bloque de imagen Base64 (retroalimentación visual);
    el resto como texto.
    """
    if "image_b64" in result:
        content = [
            {
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": "image/png",
                    "data": result["image_b64"],
                },
            }
        ]
    else:
        content = [{"type": "text", "text": result.get("text", "")}]
    return {"type": "tool_result", "tool_use_id": tool_use_id, "content": content}


class ComputerUseAgent:
    """Bucle agéntico Computer Use — asíncrono, listo para una cola de tareas."""

    def __init__(
        self,
        computer: BrowserComputer,
        *,
        api_key: str | None = None,
        model: str = MODEL,
        system: str = SYSTEM_PROMPT,
    ):
        self.computer = computer
        self.model = model
        self.system = system
        self._api_key = api_key
        self._anthropic: Any = None

    def _client(self) -> Any:
        if self._anthropic is None:
            from anthropic import AsyncAnthropic

            self._anthropic = AsyncAnthropic(api_key=self._api_key)
        return self._anthropic

    async def run(self, task: str, *, max_steps: int = 15, max_tokens: int = 4096) -> AgentRun:
        """Bucle real con Claude. Requiere ANTHROPIC_API_KEY."""
        client = self._client()
        tools = [computer_tool_def(self.computer.width, self.computer.height)]
        messages: list[dict[str, Any]] = [{"role": "user", "content": task}]
        run = AgentRun(final_text="")

        for _ in range(max_steps):
            response = await client.beta.messages.create(
                model=self.model,
                max_tokens=max_tokens,
                system=self.system,
                tools=tools,
                betas=[COMPUTER_BETA],
                messages=messages,
            )
            run.stop_reason = response.stop_reason

            # pause_turn: el bucle server-side pausó; reenviar para continuar.
            if response.stop_reason == "pause_turn":
                messages.append({"role": "assistant", "content": response.content})
                continue

            if response.stop_reason != "tool_use":
                run.final_text = "".join(
                    b.text for b in response.content if getattr(b, "type", None) == "text"
                ).strip()
                return run

            messages.append({"role": "assistant", "content": response.content})
            tool_results: list[dict[str, Any]] = []
            for block in response.content:
                if getattr(block, "type", None) != "tool_use":
                    continue
                result = await self.computer.execute(block.input or {})
                run.steps.append(
                    AgentStep(
                        action=block.input or {}, kind="image" if "image_b64" in result else "text"
                    )
                )
                tool_results.append(_tool_result_block(block.id, result))
            messages.append({"role": "user", "content": tool_results})

        run.final_text = "(límite de pasos alcanzado)"
        return run

    async def run_mock(self, actions: list[dict[str, Any]]) -> AgentRun:
        """Ejecuta una secuencia de acciones guionizada — SIN llamar a Anthropic.

        Prueba el bucle completo de retroalimentación visual (acción → screenshot →
        base64 → tool_result) contra el navegador real, sin gastar tokens.
        """
        run = AgentRun(final_text="(mock)", stop_reason="mock")
        for i, action in enumerate(actions):
            result = await self.computer.execute(action)
            # Construimos el tool_result tal como se enviaría a la API (validación de formato).
            block = _tool_result_block(f"mock_{i}", result)
            assert block["type"] == "tool_result"
            run.steps.append(
                AgentStep(action=action, kind="image" if "image_b64" in result else "text")
            )
            logger.info(
                "[computer:mock] paso %d %s -> %s", i, action.get("action"), run.steps[-1].kind
            )
        return run
