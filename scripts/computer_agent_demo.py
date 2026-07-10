"""
computer_agent_demo.py — Prueba inicial del Agente de Uso de Computadora de ARIA.

Levanta el navegador aislado (Chromium/Playwright), "abre una web", y ejecuta el
bucle de retroalimentación visual con una secuencia de acciones guionizada
(mover ratón → clic → escribir → captura). Guarda las capturas en el scratchpad.
NO gasta tokens: usa run_mock().

Si defines ANTHROPIC_API_KEY, corre además el bucle real con Claude sobre la
misma tarea ("abre un navegador y busca algo").

Uso:  python3 scripts/computer_agent_demo.py
"""

from __future__ import annotations

import asyncio
import base64
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from apps.core.integrations.computer_agent import (  # noqa: E402
    BrowserComputer,
    ComputerUseAgent,
)

OUT = Path(os.getenv("ARIA_SCRATCH", "/tmp/claude-0/-home-user-aria-ai/scratchpad"))
OUT.mkdir(parents=True, exist_ok=True)


async def main() -> None:
    print("=" * 64)
    print("1) Levantando el sandbox (Chromium headless, 1024x768) y abriendo una web")
    print("=" * 64)
    computer = BrowserComputer(headless=True)
    await computer.start()
    agent = ComputerUseAgent(computer)

    # Página local (sin depender de red): una barra de búsqueda simulada.
    await computer.load_html(
        """
        <html><body style="font-family:sans-serif;margin:0;background:#f4f1ea">
          <div style="padding:40px">
            <h1 style="color:#c65d3b">ARIA — Navegador Sandbox</h1>
            <input id="q" placeholder="Busca algo..."
                   style="width:420px;padding:12px;font-size:18px" />
            <button style="padding:12px 20px;font-size:18px">Buscar</button>
          </div>
        </body></html>
        """
    )

    try:
        # Secuencia de acciones al estilo de las que devuelve Computer Use.
        actions = [
            {"action": "screenshot"},
            {"action": "mouse_move", "coordinate": [200, 150]},
            {"action": "left_click", "coordinate": [200, 150]},
            {"action": "type", "text": "ARIA usa la computadora"},
            {"action": "screenshot"},
        ]
        print("\n2) Ejecutando el bucle de retroalimentación visual (run_mock):")
        run = await agent.run_mock(actions)
        for i, step in enumerate(run.steps):
            print(f"   paso {i}: {step.action.get('action'):12s} -> {step.kind}")

        # Prueba que la captura final es un PNG Base64 válido, y la guardamos.
        b64 = await computer.screenshot_b64()
        png = base64.b64decode(b64)
        assert png[:8] == b"\x89PNG\r\n\x1a\n", "la captura no es un PNG válido"
        shot = OUT / "computer_agent_demo.png"
        shot.write_bytes(png)
        print(f"\n3) Captura final válida: {len(png)} bytes -> {shot}")

        if os.getenv("ANTHROPIC_API_KEY"):
            print("\n4) Bucle real con Claude (Computer Use):")
            real = await agent.run(
                "Estás en example.com. Toma una captura y dime qué título muestra la página.",
                max_steps=6,
            )
            print(f"   Respuesta: {real.final_text}")
            print(f"   Pasos: {len(real.steps)} | stop_reason={real.stop_reason}")
        else:
            print("\n4) [omitido] Define ANTHROPIC_API_KEY para el bucle real con Claude.")
    finally:
        await computer.close()

    print("\nOK — agente de uso de computadora operativo (sandbox + feedback visual).")


if __name__ == "__main__":
    asyncio.run(main())
