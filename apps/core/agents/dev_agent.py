"""
DevAgent — Developer Agent
Genera sitios web completos, los sube a GitHub y los despliega en Vercel.
"""
from __future__ import annotations

import base64
import logging
from typing import Any, Optional

import httpx

from apps.core.agents.base_agent import BaseAgent
from apps.core.config import settings
from apps.core.tools.ai_client import AIModel

logger = logging.getLogger("aria.dev_agent")


class DevAgent(BaseAgent):
    def __init__(self) -> None:
        super().__init__(
            name="dev_agent",
            description="Desarrollador — genera sitios web y los despliega",
            capabilities=["web_generation", "github", "vercel", "deployment"],
        )

    async def _execute(self, context: dict[str, Any]) -> dict[str, Any]:
        market_focus = context.get("market_focus", "digital products")
        language = context.get("primary_language", "en")
        task = context.get("task", "")

        website = await self.generate_website(market_focus, language)
        if not website:
            return {"success": False, "error": "No se pudo generar el website"}

        slug = self._slugify(market_focus)
        repo_name = f"aria-site-{slug}"

        results: dict[str, Any] = {
            "success": True,
            "agent": "dev_agent",
            "website_name": website["name"],
        }

        # Crear repo en GitHub (requiere aprobación si REQUIRE_APPROVAL_FOR_DEPLOYS=true)
        if settings.GITHUB_TOKEN and settings.GITHUB_USERNAME:
            deploy_requires_approval = getattr(settings, "REQUIRE_APPROVAL_FOR_DEPLOYS", False)
            if deploy_requires_approval:
                github_result = await self.execute_with_approval(
                    action=f"Crear repositorio GitHub: {repo_name}",
                    details=f"Sitio: {website['name']} | Nicho: {market_focus}",
                    fn=lambda: self.create_github_repo(repo_name, website),
                )
            else:
                github_result = await self.create_github_repo(repo_name, website)
            results["github"] = github_result

            if github_result.get("success") and settings.VERCEL_TOKEN:
                vercel_result = await self.deploy_to_vercel(repo_name, website)
                results["vercel"] = vercel_result

                if vercel_result.get("success"):
                    await self._save_website(
                        name=website["name"],
                        niche=market_focus,
                        language=language,
                        github_url=github_result.get("html_url", ""),
                        vercel_url=vercel_result.get("url", ""),
                    )

        return results

    async def generate_website(self, niche: str, language: str) -> Optional[dict[str, Any]]:
        """Genera HTML/CSS/JS completo para un sitio monetizado con afiliados."""
        meta = await self.think(
            system="Eres un desarrollador web experto en landing pages de alta conversión para productos digitales.",
            user=(
                f"Nicho: {niche} | Idioma: {language}\n"
                "Diseña los metadatos de un sitio web monetizado. JSON:\n"
                '{"name": "SiteName", "tagline": "...", "primary_color": "#hex", '
                '"secondary_color": "#hex", "cta_text": "...", '
                '"sections": ["hero", "features", "testimonials", "cta"]}'
            ),
            model=AIModel.STRATEGY,
            json_mode=True,
        )
        if not meta:
            return None

        # Generar HTML completo
        html = await self.think(
            system="Eres un desarrollador frontend experto. Escribe código HTML/CSS puro de alta calidad, responsivo y optimizado para conversión.",
            user=(
                f"Crea una landing page completa en HTML/CSS/JS para el nicho '{niche}'.\n"
                f"Nombre del sitio: {meta.get('name', 'Aria Site')}\n"
                f"Tagline: {meta.get('tagline', '')}\n"
                f"Color primario: {meta.get('primary_color', '#4F46E5')}\n"
                f"Idioma: {language}\n"
                "Requisitos: responsivo, CTA prominente, sección de beneficios, testimonios, footer.\n"
                "Devuelve SOLO el código HTML completo con CSS embebido en <style>. Sin explicaciones."
            ),
            model=AIModel.CODE,
        )
        meta["html"] = html or "<html><body><h1>Site</h1></body></html>"
        meta["niche"] = niche
        meta["language"] = language
        logger.info("[DevAgent] Website generado: %s", meta.get("name"))
        return meta

    async def create_github_repo(
        self, repo_name: str, website: dict[str, Any]
    ) -> dict[str, Any]:
        """Crea un repositorio en GitHub con el código del sitio."""
        try:
            async with httpx.AsyncClient(timeout=20.0) as client:
                # Crear repo
                create_res = await client.post(
                    "https://api.github.com/user/repos",
                    headers={
                        "Authorization": f"Bearer {settings.GITHUB_TOKEN}",
                        "Accept": "application/vnd.github+json",
                    },
                    json={
                        "name": repo_name,
                        "description": f"Aria AI — {website.get('name', '')} | {website.get('niche', '')}",
                        "private": False,
                        "auto_init": False,
                    },
                )
                if create_res.status_code not in (200, 201):
                    if "already exists" in create_res.text:
                        logger.info("[DevAgent] Repo %s ya existe, actualizando", repo_name)
                    else:
                        return {"success": False, "error": f"GitHub create HTTP {create_res.status_code}"}

                repo_data = create_res.json() if create_res.status_code in (200, 201) else {}
                html_url = repo_data.get("html_url", f"https://github.com/{settings.GITHUB_USERNAME}/{repo_name}")

                # Subir index.html
                html_content = website.get("html", "")
                encoded = base64.b64encode(html_content.encode()).decode()
                await client.put(
                    f"https://api.github.com/repos/{settings.GITHUB_USERNAME}/{repo_name}/contents/index.html",
                    headers={
                        "Authorization": f"Bearer {settings.GITHUB_TOKEN}",
                        "Accept": "application/vnd.github+json",
                    },
                    json={
                        "message": "feat: initial site by Aria AI",
                        "content": encoded,
                    },
                )

                # Agregar vercel.json
                vercel_config = '{"version": 2, "builds": [{"src": "index.html", "use": "@vercel/static"}]}'
                vercel_encoded = base64.b64encode(vercel_config.encode()).decode()
                await client.put(
                    f"https://api.github.com/repos/{settings.GITHUB_USERNAME}/{repo_name}/contents/vercel.json",
                    headers={
                        "Authorization": f"Bearer {settings.GITHUB_TOKEN}",
                        "Accept": "application/vnd.github+json",
                    },
                    json={"message": "chore: add vercel config", "content": vercel_encoded},
                )

                logger.info("[DevAgent] Repo GitHub creado: %s", html_url)
                return {"success": True, "repo_name": repo_name, "html_url": html_url}
        except Exception as exc:
            logger.error("[DevAgent] Error creando repo GitHub: %s", exc)
            return {"success": False, "error": str(exc)}

    async def deploy_to_vercel(
        self, repo_name: str, website: dict[str, Any]
    ) -> dict[str, Any]:
        """Despliega el repo en Vercel via API."""
        if not settings.VERCEL_TOKEN:
            return {"success": False, "error": "VERCEL_TOKEN no configurado"}
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                res = await client.post(
                    "https://api.vercel.com/v13/deployments",
                    headers={
                        "Authorization": f"Bearer {settings.VERCEL_TOKEN}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "name": repo_name,
                        "gitSource": {
                            "type": "github",
                            "repoId": repo_name,
                            "ref": "main",
                            "org": settings.GITHUB_USERNAME,
                            "repo": repo_name,
                        },
                        "projectSettings": {"framework": None},
                    },
                )
                if res.status_code in (200, 201):
                    data = res.json()
                    deploy_url = f"https://{data.get('url', '')}"
                    logger.info("[DevAgent] Desplegado en Vercel: %s", deploy_url)
                    return {"success": True, "url": deploy_url, "deployment_id": data.get("id")}
                return {"success": False, "error": f"Vercel HTTP {res.status_code}: {res.text[:200]}"}
        except Exception as exc:
            logger.error("[DevAgent] Error desplegando en Vercel: %s", exc)
            return {"success": False, "error": str(exc)}

    async def update_website(self, repo_name: str, new_html: str) -> dict[str, Any]:
        """Actualiza el contenido de un sitio existente en GitHub."""
        try:
            async with httpx.AsyncClient(timeout=20.0) as client:
                # Obtener SHA del archivo actual
                get_res = await client.get(
                    f"https://api.github.com/repos/{settings.GITHUB_USERNAME}/{repo_name}/contents/index.html",
                    headers={
                        "Authorization": f"Bearer {settings.GITHUB_TOKEN}",
                        "Accept": "application/vnd.github+json",
                    },
                )
                if get_res.status_code != 200:
                    return {"success": False, "error": "No se pudo obtener SHA del archivo"}
                sha = get_res.json()["sha"]

                encoded = base64.b64encode(new_html.encode()).decode()
                put_res = await client.put(
                    f"https://api.github.com/repos/{settings.GITHUB_USERNAME}/{repo_name}/contents/index.html",
                    headers={
                        "Authorization": f"Bearer {settings.GITHUB_TOKEN}",
                        "Accept": "application/vnd.github+json",
                    },
                    json={"message": "feat: update by Aria AI", "content": encoded, "sha": sha},
                )
                if put_res.status_code in (200, 201):
                    logger.info("[DevAgent] Website actualizado: %s", repo_name)
                    return {"success": True}
                return {"success": False, "error": f"HTTP {put_res.status_code}"}
        except Exception as exc:
            logger.error("[DevAgent] Error actualizando website: %s", exc)
            return {"success": False, "error": str(exc)}

    async def _save_website(
        self, name: str, niche: str, language: str, github_url: str, vercel_url: str
    ) -> None:
        try:
            from apps.core.memory.supabase_client import get_db
            db = get_db()
            await db.save_website(
                name=name, niche=niche, language=language, market="global",
                github_url=github_url, vercel_url=vercel_url,
            )
        except Exception as exc:
            logger.warning("[DevAgent] No se pudo guardar website: %s", exc)

    @staticmethod
    def _slugify(text: str) -> str:
        import re
        return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:30]
