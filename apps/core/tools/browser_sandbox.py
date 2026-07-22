"""
browser_sandbox.py — Navegador web completo para ARIA AI.

ARIA puede interactuar con cualquier sitio web como un humano:
  - Navegar a URLs (incluyendo páginas con JavaScript)
  - Hacer clic en elementos, llenar formularios, presionar botones
  - Ejecutar JavaScript arbitrario en la página
  - Tomar screenshots de páginas completas
  - Mantener sesión/cookies entre requests
  - Rellenar y enviar formularios automáticamente
  - Descargar archivos
  - Extraer datos de páginas con JS dinámico

Motor: Playwright (headless Chromium) con fallback a httpx para páginas estáticas.
"""

from __future__ import annotations

import asyncio
import logging
import re
from typing import Any

import httpx

logger = logging.getLogger("aria.browser_sandbox")


class BrowserSession:
    """
    Sesión de navegador persistente con cookies y estado.
    Usa Playwright si está disponible, httpx como fallback.
    """

    def __init__(self) -> None:
        self._page = None
        self._browser = None
        self._context = None
        self._playwright = None
        self._http = httpx.AsyncClient(
            timeout=30.0,
            follow_redirects=True,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/120.0.0.0 Safari/537.36"
                )
            },
        )
        self._playwright_available = None  # None = unchecked

    async def _ensure_browser(self) -> bool:
        """Inicializa Playwright si está disponible."""
        if self._playwright_available is False:
            return False
        if self._page is not None:
            return True
        try:
            from playwright.async_api import async_playwright

            self._playwright = await async_playwright().start()
            self._browser = await self._playwright.chromium.launch(
                headless=True,
                args=["--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu"],
            )
            self._context = await self._browser.new_context(
                viewport={"width": 1280, "height": 900},
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/120.0.0.0 Safari/537.36"
                ),
                java_script_enabled=True,
            )
            self._page = await self._context.new_page()
            self._playwright_available = True
            logger.info("[BrowserSandbox] Playwright iniciado")
            return True
        except Exception as exc:
            logger.warning("[BrowserSandbox] Playwright no disponible: %s — usando httpx", exc)
            self._playwright_available = False
            return False

    async def close(self) -> None:
        if self._browser:
            await self._browser.close()
        if self._playwright:
            await self._playwright.stop()
        await self._http.aclose()

    # ══════════════════════════════════════════════════════════════
    # NAVEGACIÓN
    # ══════════════════════════════════════════════════════════════

    async def navigate(self, url: str, wait_for: str = "load") -> dict[str, Any]:
        """Navega a una URL y espera que cargue.

        SSRF guard: `url` is ultimately steerable by whatever the user asks
        ARIA to browse/interact with. A real browser navigating to an
        internal/metadata address is strictly worse than a plain fetch (it
        executes JS, can submit forms, follows redirects) — same class of bug
        fixed in WebTools.fetch_page, checked here too.
        """
        from apps.core.tools.web_tools import _assert_public_url

        try:
            await _assert_public_url(url)
        except ValueError as exc:
            return {"success": False, "url": url, "error": str(exc)}

        if await self._ensure_browser():
            try:
                response = await self._page.goto(url, wait_until=wait_for, timeout=30000)
                await asyncio.sleep(1)  # esperar renderizado JS
                title = await self._page.title()
                return {
                    "success": True,
                    "url": self._page.url,
                    "title": title,
                    "status": response.status if response else 200,
                    "engine": "playwright",
                }
            except Exception as exc:
                return {"success": False, "url": url, "error": str(exc)}
        else:
            # Fallback httpx
            try:
                r = await self._http.get(url)
                title_m = re.search(r"<title[^>]*>(.*?)</title>", r.text, re.I | re.S)
                return {
                    "success": r.status_code < 400,
                    "url": str(r.url),
                    "title": title_m.group(1).strip() if title_m else "",
                    "status": r.status_code,
                    "engine": "httpx",
                }
            except Exception as exc:
                return {"success": False, "url": url, "error": str(exc)}

    async def get_content(self, url: str | None = None, max_chars: int = 8000) -> dict[str, Any]:
        """Extrae el texto limpio de la página actual (o navega a url primero)."""
        if url:
            nav = await self.navigate(url)
            if not nav["success"]:
                return nav

        if await self._ensure_browser() and self._page:
            try:
                content = await self._page.content()
                text = _extract_text(content)
                title = await self._page.title()
                current_url = self._page.url
                # También intentar extraer datos estructurados
                try:
                    links = await self._page.eval_on_selector_all(
                        "a[href]",
                        "els => els.map(e => ({text: e.textContent.trim(), href: e.href})).filter(e => e.text && e.href).slice(0, 30)",
                    )
                except Exception:
                    links = []
                return {
                    "success": True,
                    "url": current_url,
                    "title": title,
                    "text": text[:max_chars],
                    "chars": len(text),
                    "links": links[:20],
                    "engine": "playwright",
                }
            except Exception as exc:
                return {"success": False, "error": str(exc)}
        else:
            if not url:
                return {
                    "success": False,
                    "error": "Se requiere URL cuando Playwright no está disponible",
                }
            try:
                r = await self._http.get(url)
                text = _extract_text(r.text)
                title_m = re.search(r"<title[^>]*>(.*?)</title>", r.text, re.I | re.S)
                return {
                    "success": True,
                    "url": str(r.url),
                    "title": title_m.group(1).strip() if title_m else "",
                    "text": text[:max_chars],
                    "engine": "httpx",
                }
            except Exception as exc:
                return {"success": False, "error": str(exc)}

    # ══════════════════════════════════════════════════════════════
    # INTERACCIÓN
    # ══════════════════════════════════════════════════════════════

    async def click(self, selector: str, timeout: int = 5000) -> dict[str, Any]:
        """Hace clic en un elemento por CSS selector o texto."""
        if not await self._ensure_browser():
            return {"success": False, "error": "Playwright requerido para clic"}
        try:
            await self._page.click(selector, timeout=timeout)
            await asyncio.sleep(0.5)
            return {"success": True, "selector": selector, "url": self._page.url}
        except Exception as exc:
            return {"success": False, "selector": selector, "error": str(exc)}

    async def fill_field(self, selector: str, value: str) -> dict[str, Any]:
        """Rellena un campo de entrada."""
        if not await self._ensure_browser():
            return {"success": False, "error": "Playwright requerido para fill"}
        try:
            await self._page.fill(selector, value)
            return {"success": True, "selector": selector}
        except Exception as exc:
            return {"success": False, "selector": selector, "error": str(exc)}

    async def press_key(self, key: str, selector: str | None = None) -> dict[str, Any]:
        """Presiona una tecla (ej: 'Enter', 'Tab', 'Escape')."""
        if not await self._ensure_browser():
            return {"success": False, "error": "Playwright requerido"}
        try:
            if selector:
                await self._page.press(selector, key)
            else:
                await self._page.keyboard.press(key)
            return {"success": True, "key": key}
        except Exception as exc:
            return {"success": False, "error": str(exc)}

    async def fill_and_submit_form(
        self,
        url: str,
        fields: dict[str, str],
        submit_selector: str = "button[type=submit], input[type=submit], form",
    ) -> dict[str, Any]:
        """
        Navega a una URL, rellena un formulario y lo envía.
        fields: {"#email": "user@example.com", "#password": "secret"}
        """
        nav = await self.navigate(url)
        if not nav.get("success"):
            return nav

        if not await self._ensure_browser():
            # Fallback: POST con httpx
            return await self._submit_form_httpx(url, fields)

        fill_errors = []
        for selector, value in fields.items():
            r = await self.fill_field(selector, value)
            if not r["success"]:
                fill_errors.append(r)

        try:
            await self._page.click(submit_selector, timeout=5000)
            await asyncio.sleep(2)
            title = await self._page.title()
            return {
                "success": True,
                "url": self._page.url,
                "title": title,
                "fill_errors": fill_errors,
            }
        except Exception as exc:
            # Fallback: presionar Enter en último campo
            try:
                last_selector = list(fields.keys())[-1]
                await self._page.press(last_selector, "Enter")
                await asyncio.sleep(2)
                return {"success": True, "url": self._page.url, "submitted_via": "enter"}
            except Exception:
                return {"success": False, "error": str(exc), "fill_errors": fill_errors}

    async def _submit_form_httpx(self, url: str, fields: dict[str, str]) -> dict[str, Any]:
        """Envía formulario vía POST httpx cuando Playwright no está disponible."""
        try:
            r = await self._http.post(url, data=fields)
            return {
                "success": r.status_code < 400,
                "status": r.status_code,
                "url": str(r.url),
                "engine": "httpx_post",
            }
        except Exception as exc:
            return {"success": False, "error": str(exc)}

    # ══════════════════════════════════════════════════════════════
    # JAVASCRIPT
    # ══════════════════════════════════════════════════════════════

    async def execute_js(self, script: str) -> dict[str, Any]:
        """Ejecuta JavaScript en la página actual y retorna el resultado."""
        if not await self._ensure_browser():
            return {"success": False, "error": "Playwright requerido para ejecutar JS"}
        try:
            result = await self._page.evaluate(script)
            return {"success": True, "result": result}
        except Exception as exc:
            return {"success": False, "error": str(exc), "script": script[:200]}

    async def extract_json_from_page(self, url: str | None = None) -> dict[str, Any]:
        """Extrae todos los datos JSON de la página (scripts, data-attributes, etc.)."""
        if url:
            await self.navigate(url)
        if not await self._ensure_browser():
            return {"success": False, "error": "Playwright requerido"}
        try:
            script = """
            () => {
                const jsonData = {};
                // JSON-LD structured data
                document.querySelectorAll('script[type="application/ld+json"]').forEach((el, i) => {
                    try { jsonData['ld_json_' + i] = JSON.parse(el.textContent); } catch(e) {}
                });
                // Meta tags
                const meta = {};
                document.querySelectorAll('meta[name], meta[property]').forEach(el => {
                    const key = el.getAttribute('name') || el.getAttribute('property');
                    if (key) meta[key] = el.getAttribute('content');
                });
                jsonData['meta'] = meta;
                // Page title and URL
                jsonData['title'] = document.title;
                jsonData['url'] = window.location.href;
                return jsonData;
            }
            """
            result = await self._page.evaluate(script)
            return {"success": True, "data": result}
        except Exception as exc:
            return {"success": False, "error": str(exc)}

    # ══════════════════════════════════════════════════════════════
    # SCREENSHOTS
    # ══════════════════════════════════════════════════════════════

    async def screenshot(
        self,
        url: str | None = None,
        full_page: bool = True,
        selector: str | None = None,
    ) -> dict[str, Any]:
        """
        Captura screenshot de la página actual o de una URL.
        Retorna bytes de la imagen PNG.
        """
        if url:
            nav = await self.navigate(url)
            if not nav.get("success"):
                return nav

        if not await self._ensure_browser():
            return {"success": False, "error": "Playwright requerido para screenshots"}

        try:
            await asyncio.sleep(1)  # esperar animaciones
            kwargs: dict[str, Any] = {"type": "png", "full_page": full_page}
            if selector:
                element = await self._page.query_selector(selector)
                if element:
                    img_bytes = await element.screenshot(
                        **{k: v for k, v in kwargs.items() if k != "full_page"}
                    )
                else:
                    return {"success": False, "error": f"Selector no encontrado: {selector}"}
            else:
                img_bytes = await self._page.screenshot(**kwargs)

            return {
                "success": True,
                "image_bytes": img_bytes,
                "url": self._page.url,
                "format": "png",
                "size_kb": len(img_bytes) // 1024,
            }
        except Exception as exc:
            return {"success": False, "error": str(exc)}

    # ══════════════════════════════════════════════════════════════
    # DESCARGAS
    # ══════════════════════════════════════════════════════════════

    async def download_file(self, url: str) -> dict[str, Any]:
        """Descarga un archivo y retorna los bytes."""
        try:
            from apps.core.tools.web_tools import _assert_public_url

            await _assert_public_url(url)
            r = await self._http.get(url)
            if r.status_code == 200:
                filename = url.split("/")[-1].split("?")[0] or "download"
                return {
                    "success": True,
                    "url": url,
                    "filename": filename,
                    "content_bytes": r.content,
                    "content_type": r.headers.get("content-type", ""),
                    "size_kb": len(r.content) // 1024,
                }
            return {"success": False, "status": r.status_code}
        except Exception as exc:
            return {"success": False, "error": str(exc)}

    # ══════════════════════════════════════════════════════════════
    # BÚSQUEDA AVANZADA
    # ══════════════════════════════════════════════════════════════

    async def search_and_extract(self, query: str, extract_links: bool = True) -> dict[str, Any]:
        """
        Busca en DuckDuckGo y extrae contenido de los primeros resultados.
        Sin API key necesaria.
        """
        ddg_url = f"https://html.duckduckgo.com/html/?q={query.replace(' ', '+')}"
        content = await self.get_content(ddg_url)
        if not content.get("success"):
            return content

        # Extraer URLs de resultados reales
        if await self._ensure_browser():
            try:
                results = await self._page.eval_on_selector_all(
                    "a.result__a",
                    "els => els.map(e => ({title: e.textContent.trim(), href: e.href})).slice(0, 10)",
                )
                return {
                    "success": True,
                    "query": query,
                    "results": results,
                    "page_text": content.get("text", "")[:3000],
                }
            except Exception:
                pass

        return {
            "success": True,
            "query": query,
            "page_text": content.get("text", "")[:5000],
            "results": content.get("links", [])[:10],
        }

    async def interact_with_page(self, instructions: list[dict]) -> dict[str, Any]:
        """
        Ejecuta una secuencia de instrucciones sobre la página actual.

        Cada instrucción es un dict con "action" y parámetros:
          {"action": "navigate", "url": "https://..."}
          {"action": "click", "selector": "#button"}
          {"action": "fill", "selector": "#input", "value": "texto"}
          {"action": "press", "key": "Enter"}
          {"action": "wait", "ms": 1000}
          {"action": "screenshot"}
          {"action": "extract_text"}
          {"action": "js", "script": "document.title"}
        """
        results = []
        for step in instructions:
            action = step.get("action", "")
            try:
                if action == "navigate":
                    r = await self.navigate(step["url"])
                elif action == "click":
                    r = await self.click(step["selector"])
                elif action == "fill":
                    r = await self.fill_field(step["selector"], step["value"])
                elif action == "press":
                    r = await self.press_key(step["key"], step.get("selector"))
                elif action == "wait":
                    ms = int(step.get("ms", 1000))
                    await asyncio.sleep(min(ms, 10000) / 1000)
                    r = {"success": True, "waited_ms": ms}
                elif action == "screenshot":
                    r = await self.screenshot()
                    if r.get("image_bytes"):
                        r = {**r, "image_bytes": f"<{r['size_kb']}KB PNG>"}
                elif action == "extract_text":
                    r = await self.get_content()
                elif action == "js":
                    r = await self.execute_js(step["script"])
                else:
                    r = {"success": False, "error": f"Acción desconocida: {action}"}
                results.append({"action": action, "result": r})
            except Exception as exc:
                results.append({"action": action, "error": str(exc)})

        success_count = sum(1 for r in results if r.get("result", {}).get("success"))
        return {
            "success": success_count > 0,
            "steps_executed": len(results),
            "steps_succeeded": success_count,
            "results": results,
        }


# ══════════════════════════════════════════════════════════════
# FUNCIONES DE UTILIDAD
# ══════════════════════════════════════════════════════════════


def _extract_text(html: str) -> str:
    """Extrae texto limpio de HTML."""
    for tag in ("script", "style", "nav", "footer", "header", "aside", "noscript", "iframe"):
        html = re.sub(rf"<{tag}[^>]*>.*?</{tag}>", " ", html, flags=re.DOTALL | re.I)
    html = re.sub(r"<br\s*/?>", "\n", html, flags=re.I)
    html = re.sub(r"<p[^>]*>", "\n", html, flags=re.I)
    html = re.sub(r"<h[1-6][^>]*>", "\n## ", html, flags=re.I)
    html = re.sub(r"<li[^>]*>", "\n- ", html, flags=re.I)
    html = re.sub(r"<[^>]+>", " ", html)
    for e, c in [("&amp;", "&"), ("&lt;", "<"), ("&gt;", ">"), ("&quot;", '"'), ("&nbsp;", " ")]:
        html = html.replace(e, c)
    html = re.sub(r"[ \t]+", " ", html)
    html = re.sub(r"\n{3,}", "\n\n", html)
    return html.strip()


# ══════════════════════════════════════════════════════════════
# SANDBOX MANAGER — Interfaz de alto nivel para ARIA
# ══════════════════════════════════════════════════════════════


class SandboxManager:
    """
    Entorno sandbox completo para ARIA.
    Combina navegador + código + archivos en un entorno unificado.
    """

    def __init__(self) -> None:
        self._sessions: dict[str, BrowserSession] = {}

    def _get_session(self, session_id: str = "default") -> BrowserSession:
        if session_id not in self._sessions:
            self._sessions[session_id] = BrowserSession()
        return self._sessions[session_id]

    async def browse(
        self,
        url: str,
        extract: bool = True,
        screenshot: bool = False,
        session_id: str = "default",
    ) -> dict[str, Any]:
        """Navega a una URL y extrae contenido."""
        session = self._get_session(session_id)
        result = await session.navigate(url)
        if not result.get("success"):
            return result

        if extract:
            content = await session.get_content()
            result["content"] = content.get("text", "")[:6000]
            result["links"] = content.get("links", [])[:15]

        if screenshot:
            shot = await session.screenshot()
            if shot.get("success"):
                result["screenshot_bytes"] = shot.get("image_bytes")

        return result

    async def fill_form(
        self,
        url: str,
        fields: dict[str, str],
        submit: str = "button[type=submit]",
        session_id: str = "default",
    ) -> dict[str, Any]:
        """Rellena y envía un formulario web."""
        session = self._get_session(session_id)
        return await session.fill_and_submit_form(url, fields, submit)

    async def run_browser_task(
        self,
        task_description: str,
        start_url: str | None = None,
        session_id: str = "default",
    ) -> dict[str, Any]:
        """
        ARIA describe una tarea en lenguaje natural y el sandbox la ejecuta.
        Genera instrucciones step-by-step con IA y las ejecuta en el navegador.
        """
        from apps.core.tools.ai_client import AIModel, get_ai_client

        client = get_ai_client()
        context_url = f"\nURL inicial: {start_url}" if start_url else ""

        instructions = await client.complete_json(
            model=AIModel.FAST,
            system="Eres un agente de automatización web. Convierte tareas en instrucciones JSON.",
            user=(
                f"Tarea: {task_description}{context_url}\n\n"
                f"Genera una lista de instrucciones JSON para ejecutar esta tarea en un navegador.\n"
                f"Acciones disponibles: navigate, click, fill, press, wait, screenshot, extract_text, js\n"
                f"Responde SOLO con JSON array: [{{'action': '...', ...}}, ...]\n"
                f"Máximo 10 pasos."
            ),
            fallback=[],
        )
        if not isinstance(instructions, list):
            instructions = []

        if start_url and (not instructions or instructions[0].get("action") != "navigate"):
            instructions.insert(0, {"action": "navigate", "url": start_url})

        session = self._get_session(session_id)
        return await session.interact_with_page(instructions)

    async def close_all(self) -> None:
        for session in self._sessions.values():
            await session.close()
        self._sessions.clear()


# Singleton
_sandbox: SandboxManager | None = None


def get_sandbox() -> SandboxManager:
    global _sandbox
    if _sandbox is None:
        _sandbox = SandboxManager()
    return _sandbox
