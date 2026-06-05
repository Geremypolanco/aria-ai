"""
api_discovery.py — Sistema de descubrimiento e integración autónoma de APIs para ARIA AI.

ARIA puede:
  1. Buscar APIs públicas gratuitas relevantes a su misión
  2. Evaluar el potencial de cada API con IA
  3. Generar código de integración automáticamente
  4. Agregar la integración a su propio codebase via GitHub
  5. Actualizar su config.py con las nuevas variables de entorno
"""
from __future__ import annotations
import base64
import json
import logging
import re
from typing import Any
import httpx
from apps.core.config import settings

logger = logging.getLogger("aria.api_discovery")

# Catálogo inicial de APIs relevantes que ARIA puede agregar autónomamente
KNOWN_FREE_APIS = [
    {"name": "RapidAPI Hub",        "category": "marketplace",  "url": "https://rapidapi.com",            "free_tier": True,  "benefit": "Acceso a 40,000+ APIs desde un solo token"},
    {"name": "Pexels API",          "category": "images",       "url": "https://www.pexels.com/api/",     "free_tier": True,  "benefit": "Imágenes gratis para marketing y productos"},
    {"name": "Unsplash API",        "category": "images",       "url": "https://unsplash.com/developers", "free_tier": True,  "benefit": "50 requests/hora — imágenes alta calidad"},
    {"name": "NewsAPI",             "category": "news",         "url": "https://newsapi.org",             "free_tier": True,  "benefit": "Noticias de 30,000 fuentes — investigación de mercado"},
    {"name": "CoinGecko API",       "category": "crypto",       "url": "https://coingecko.com/api",       "free_tier": True,  "benefit": "Precios cripto en tiempo real — sin key"},
    {"name": "ExchangeRate API",    "category": "finance",      "url": "https://exchangerate-api.com",    "free_tier": True,  "benefit": "Tipos de cambio para precio multimoneda"},
    {"name": "ReSend Email",        "category": "email",        "url": "https://resend.com",              "free_tier": True,  "benefit": "3000 emails/mes gratis — alternativa a Mailchimp"},
    {"name": "OpenRouter AI",       "category": "ai",           "url": "https://openrouter.ai",           "free_tier": True,  "benefit": "Acceso a 200+ modelos de IA con un solo token"},
    {"name": "Scraping Bee",        "category": "scraping",     "url": "https://scrapingbee.com",         "free_tier": True,  "benefit": "Scraping de cualquier web para market research"},
    {"name": "WooCommerce API",     "category": "ecommerce",    "url": "https://woocommerce.com/docs/",   "free_tier": True,  "benefit": "Integración con tiendas WooCommerce"},
    {"name": "Stripe API",          "category": "payments",     "url": "https://stripe.com/docs/api",     "free_tier": True,  "benefit": "Pagos, suscripciones, products"},
    {"name": "Notion API",          "category": "productivity", "url": "https://developers.notion.com",   "free_tier": True,  "benefit": "Gestión de proyectos y base de conocimiento"},
    {"name": "Discord Webhooks",    "category": "messaging",    "url": "https://discord.com/developers",  "free_tier": True,  "benefit": "Notificaciones a Discord sin bot"},
    {"name": "Slack Webhooks",      "category": "messaging",    "url": "https://api.slack.com",           "free_tier": True,  "benefit": "Notificaciones a Slack"},
    {"name": "Twitter/X API v2",    "category": "social",       "url": "https://developer.twitter.com",   "free_tier": True,  "benefit": "Publicar tweets, leer tendencias"},
    {"name": "Reddit API",          "category": "research",     "url": "https://www.reddit.com/dev/api/", "free_tier": True,  "benefit": "Investigación de nichos via subreddits"},
    {"name": "Product Hunt API",    "category": "research",     "url": "https://api.producthunt.com",     "free_tier": True,  "benefit": "Descubrir productos digitales trending"},
    {"name": "Hacker News API",     "category": "research",     "url": "https://hacker-news.firebaseio.com/v0/", "free_tier": True, "benefit": "Trending tech sin auth"},
    {"name": "OpenAI API",          "category": "ai",           "url": "https://platform.openai.com",     "free_tier": False, "benefit": "GPT-4o, DALL-E 3, Whisper"},
    {"name": "Anthropic Claude",    "category": "ai",           "url": "https://anthropic.com",           "free_tier": False, "benefit": "Claude 3.5 Sonnet — razonamiento avanzado"},
    {"name": "Replicate API",       "category": "ai",           "url": "https://replicate.com",           "free_tier": True,  "benefit": "Run any AI model — imagen, video, audio"},
    {"name": "Stability AI",        "category": "images",       "url": "https://stability.ai",            "free_tier": True,  "benefit": "SDXL, SD3.5 — imágenes fotoreales"},
    {"name": "Deepgram",            "category": "audio",        "url": "https://deepgram.com",            "free_tier": True,  "benefit": "STT más preciso que Whisper"},
    {"name": "Lemon Squeezy",       "category": "payments",     "url": "https://lemonsqueezy.com",        "free_tier": True,  "benefit": "Venta de productos digitales — alternativa a Gumroad"},
    {"name": "Paddle API",          "category": "payments",     "url": "https://developer.paddle.com",    "free_tier": True,  "benefit": "Pagos globales con tax handling automático"},
    {"name": "Tally Forms",         "category": "forms",        "url": "https://tally.so",                "free_tier": True,  "benefit": "Formularios + webhooks para leads"},
    {"name": "Cal.com API",         "category": "scheduling",   "url": "https://cal.com/docs/api",        "free_tier": True,  "benefit": "Agendar llamadas y demos automáticamente"},
    {"name": "Firecrawl",           "category": "scraping",     "url": "https://firecrawl.dev",           "free_tier": True,  "benefit": "Scraping con AI — extrae datos estructurados"},
    {"name": "Exa AI Search",       "category": "search",       "url": "https://exa.ai",                  "free_tier": True,  "benefit": "Búsqueda semántica en internet"},
    {"name": "Perplexity API",      "category": "search",       "url": "https://www.perplexity.ai/api",   "free_tier": True,  "benefit": "Respuestas con fuentes verificadas en tiempo real"},
    {"name": "Hunter.io",           "category": "leads",        "url": "https://hunter.io",               "free_tier": True,  "benefit": "Encontrar emails de empresas para outreach"},
    {"name": "Apollo.io",           "category": "leads",        "url": "https://apolloio.github.io/apollo-api-docs/", "free_tier": True, "benefit": "Base de datos B2B — 270M+ contactos"},
    {"name": "Bannerbear",          "category": "images",       "url": "https://www.bannerbear.com",      "free_tier": True,  "benefit": "Generar imágenes marketing programáticamente"},
    {"name": "Vercel AI SDK",       "category": "ai",           "url": "https://sdk.vercel.ai",           "free_tier": True,  "benefit": "Streaming AI responses fácilmente"},
    {"name": "Zapier Webhooks",     "category": "automation",   "url": "https://zapier.com",              "free_tier": True,  "benefit": "Conectar con 6000+ apps sin código"},
    {"name": "Make (Integromat)",   "category": "automation",   "url": "https://make.com",                "free_tier": True,  "benefit": "Automatización visual más potente que Zapier"},
]


class APIDiscoveryEngine:
    """ARIA descubre, evalúa e integra nuevas APIs autónomamente."""

    def __init__(self) -> None:
        self._http = httpx.AsyncClient(timeout=30.0)
        self._github_token = settings.GITHUB_TOKEN
        self._github_headers = {
            "Authorization": f"Bearer {self._github_token}",
            "Accept": "application/vnd.github+json",
            "Content-Type": "application/json",
        }
        self.repo = settings.GITHUB_REPO or "Geremypolanco/aria-ai"

    # ══════════════════════════════════════════════════════════════
    # 1. BÚSQUEDA DE APIS RELEVANTES
    # ══════════════════════════════════════════════════════════════

    async def discover_apis_for_mission(self, mission: str = "digital business automation") -> list[dict]:
        """Descubre APIs relevantes para la misión actual de ARIA."""
        import asyncio

        # Buscar en catálogo local
        local_apis = await self._search_local_catalog(mission)

        # Buscar en GitHub (repos de API lists)
        github_apis = await self._search_github_api_lists(mission)

        # Buscar en public-apis.io
        public_apis = await self._fetch_public_apis_list(mission)

        all_apis = local_apis + github_apis + public_apis

        # Deduplicar por nombre
        seen = set()
        unique = []
        for api in all_apis:
            name = api.get("name", "").lower()
            if name not in seen:
                seen.add(name)
                unique.append(api)

        return unique[:30]

    async def _search_local_catalog(self, mission: str) -> list[dict]:
        """Filtra el catálogo local por relevancia."""
        try:
            from apps.core.tools.ai_client import AIModel, get_ai_client
            ai = await get_ai_client()

            # Usar IA para determinar cuáles APIs del catálogo son más relevantes
            catalog_names = [f"{a['name']}: {a['benefit']}" for a in KNOWN_FREE_APIS]
            response = await ai.complete(
                system="You select the most relevant APIs for a given mission. Return JSON array of API names only.",
                user=f"Mission: {mission}\nAPIs available:\n" + "\n".join(catalog_names[:30]) +
                     "\nReturn JSON array of the 10 most relevant API names for this mission.",
                model=AIModel.FAST,
            )
            if response and response.success:
                try:
                    match = re.search(r"\[.*?\]", response.content, re.DOTALL)
                    if match:
                        selected_names = json.loads(match.group())
                        selected_names_lower = [n.lower() for n in selected_names]
                        return [a for a in KNOWN_FREE_APIS
                                if any(n in a["name"].lower() for n in selected_names_lower)]
                except Exception:
                    pass
        except Exception as exc:
            logger.warning("[APIDiscovery] local catalog error: %s", exc)
        return KNOWN_FREE_APIS[:10]

    async def _search_github_api_lists(self, query: str) -> list[dict]:
        """Busca listas de APIs en GitHub (public-apis repo)."""
        try:
            res = await self._http.get(
                "https://raw.githubusercontent.com/public-apis/public-apis/master/apis.json",
                timeout=15.0,
            )
            if res.status_code == 200:
                data = res.json()
                results = []
                query_lower = query.lower()
                for category, apis in data.items():
                    if isinstance(apis, list):
                        for api in apis:
                            desc = api.get("Description", "").lower()
                            name = api.get("API", "")
                            if any(kw in desc or kw in name.lower()
                                   for kw in query_lower.split()[:5]):
                                results.append({
                                    "name": name,
                                    "description": api.get("Description", ""),
                                    "url": api.get("Link", ""),
                                    "auth": api.get("Auth", ""),
                                    "free_tier": api.get("Auth", "") in ("", "No"),
                                    "category": category,
                                    "benefit": api.get("Description", ""),
                                    "source": "public-apis",
                                })
                return results[:10]
        except Exception as exc:
            logger.warning("[APIDiscovery] github search error: %s", exc)
        return []

    async def _fetch_public_apis_list(self, category: str) -> list[dict]:
        """Fetches from publicapis.dev for more APIs."""
        try:
            res = await self._http.get(
                "https://api.publicapis.org/entries",
                params={"category": "business", "https": "true"},
                timeout=10.0,
            )
            if res.status_code == 200:
                entries = res.json().get("entries", [])
                return [{
                    "name": e.get("API", ""),
                    "description": e.get("Description", ""),
                    "url": e.get("Link", ""),
                    "category": e.get("Category", ""),
                    "benefit": e.get("Description", ""),
                    "free_tier": e.get("Auth", "") in ("", "No"),
                    "source": "publicapis.org",
                } for e in entries[:10]]
        except Exception:
            pass
        return []

    # ══════════════════════════════════════════════════════════════
    # 2. EVALUACIÓN DE APIS
    # ══════════════════════════════════════════════════════════════

    async def evaluate_api_potential(self, api_info: dict) -> dict[str, Any]:
        """Evalúa si una API vale la pena integrar, basándose en la misión de ARIA."""
        try:
            from apps.core.tools.ai_client import AIModel, get_ai_client
            ai = await get_ai_client()

            prompt = (
                f"ARIA AI es un sistema de negocios digitales autónomo que:\n"
                f"- Investiga mercados y nichos\n"
                f"- Crea y publica productos digitales\n"
                f"- Gestiona marketing multi-plataforma\n"
                f"- Maximiza revenue automáticamente\n\n"
                f"Evalúa si esta API vale la pena integrar:\n"
                f"Nombre: {api_info.get('name', '')}\n"
                f"Descripción: {api_info.get('description', api_info.get('benefit', ''))}\n"
                f"URL: {api_info.get('url', '')}\n"
                f"Gratis: {api_info.get('free_tier', False)}\n\n"
                "Responde en JSON: {\"worth_integrating\": true/false, \"score\": 0-100, "
                "\"reason\": str, \"use_cases\": [str], \"implementation_complexity\": \"baja/media/alta\"}"
            )

            response = await ai.complete(
                system="API evaluator for an autonomous digital business AI. Be concise. Return only JSON.",
                user=prompt,
                model=AIModel.FAST,
            )

            if response and response.success:
                try:
                    match = re.search(r"\{.*?\}", response.content, re.DOTALL)
                    if match:
                        eval_data = json.loads(match.group())
                        eval_data["api_name"] = api_info.get("name", "")
                        return {"success": True, "evaluation": eval_data}
                except Exception:
                    pass
        except Exception as exc:
            logger.error("[APIDiscovery] evaluate error: %s", exc)

        # Fallback evaluation
        score = 80 if api_info.get("free_tier") else 40
        return {
            "success": True,
            "evaluation": {
                "worth_integrating": score >= 60,
                "score": score,
                "reason": "Free tier available" if api_info.get("free_tier") else "Paid API",
                "use_cases": ["market research", "content creation"],
                "implementation_complexity": "baja",
                "api_name": api_info.get("name", ""),
            },
        }

    # ══════════════════════════════════════════════════════════════
    # 3. GENERACIÓN AUTOMÁTICA DE CÓDIGO DE INTEGRACIÓN
    # ══════════════════════════════════════════════════════════════

    async def generate_api_integration(self, api_info: dict, use_cases: list[str]) -> dict[str, Any]:
        """Genera código Python completo para integrar una nueva API."""
        try:
            from apps.core.tools.ai_client import AIModel, get_ai_client
            ai = await get_ai_client()

            api_name = api_info.get("name", "Unknown API")
            api_url = api_info.get("url", "")
            api_desc = api_info.get("description", api_info.get("benefit", ""))

            # Nombre del módulo Python
            module_name = re.sub(r"[^a-z0-9]", "_", api_name.lower()).strip("_")
            class_name = "".join(w.capitalize() for w in module_name.split("_")) + "Tools"
            env_var = module_name.upper() + "_API_KEY"

            prompt = (
                f"Generate a complete Python integration module for ARIA AI system.\n\n"
                f"API: {api_name}\n"
                f"URL: {api_url}\n"
                f"Description: {api_desc}\n"
                f"Use cases: {use_cases}\n"
                f"Module name: {module_name}_tools.py\n"
                f"Class name: {class_name}\n"
                f"Config var: settings.{env_var}\n\n"
                "Requirements:\n"
                "1. Use httpx.AsyncClient for all HTTP calls\n"
                "2. Import settings from apps.core.config\n"
                "3. All methods async, return dict with success:bool\n"
                "4. Full error handling with logger\n"
                "5. Include 5-8 practical methods for ARIA\'s mission\n"
                "6. Add module docstring listing all available methods\n"
                "7. Follow the exact same pattern as google_suite.py\n"
                "8. Include a helper method that does the most common task in one call\n\n"
                "Return ONLY the complete Python code, no markdown, no explanations."
            )

            response = await ai.complete(
                system="Expert Python developer. Generate production-ready async API integration following FastAPI patterns. Return ONLY Python code.",
                user=prompt,
                model=AIModel.CODE,
                max_tokens=6000,
            )

            if not response or not response.success:
                return {"success": False, "error": "No code generated"}

            code = response.content.strip()
            # Clean markdown if present
            code = re.sub(r"^```python\n?", "", code)
            code = re.sub(r"^```\n?", "", code)
            code = re.sub(r"\n?```$", "", code)
            code = code.strip()

            # Validate Python syntax
            try:
                import ast
                ast.parse(code)
            except SyntaxError as e:
                return {"success": False, "error": f"Generated code has syntax error: {e}"}

            return {
                "success": True,
                "module_name": f"{module_name}_tools.py",
                "class_name": class_name,
                "env_var": env_var,
                "file_path": f"apps/core/tools/{module_name}_tools.py",
                "code": code,
                "api_name": api_name,
            }
        except Exception as exc:
            logger.error("[APIDiscovery] generate_integration error: %s", exc)
            return {"success": False, "error": str(exc)}

    # ══════════════════════════════════════════════════════════════
    # 4. PUSH DE NUEVA INTEGRACIÓN A GITHUB
    # ══════════════════════════════════════════════════════════════

    async def push_new_integration(self, integration: dict) -> dict[str, Any]:
        """Pushea la nueva integración al repositorio de GitHub."""
        if not self._github_token:
            return {"success": False, "error": "GITHUB_TOKEN no configurado"}

        file_path = integration.get("file_path", "")
        code = integration.get("code", "")
        api_name = integration.get("api_name", "Unknown")

        if not file_path or not code:
            return {"success": False, "error": "file_path o code vacíos"}

        try:
            # Verificar si el archivo ya existe
            check = await self._http.get(
                f"https://api.github.com/repos/{self.repo}/contents/{file_path}",
                headers=self._github_headers,
            )
            sha = check.json().get("sha") if check.status_code == 200 else None

            body = {
                "message": f"feat(api): Auto-integrate {api_name} — added by ARIA EvolutionAgent",
                "content": base64.b64encode(code.encode()).decode(),
                "branch": "main",
            }
            if sha:
                body["sha"] = sha

            res = await self._http.put(
                f"https://api.github.com/repos/{self.repo}/contents/{file_path}",
                headers=self._github_headers,
                json=body,
            )

            if res.status_code in (200, 201):
                commit_sha = res.json().get("commit", {}).get("sha", "")

                # Also update __init__.py to export the new tool
                await self._update_tools_init(integration)

                # Log the integration
                await self._log_new_integration(api_name, file_path, commit_sha)

                return {
                    "success": True,
                    "api": api_name,
                    "file": file_path,
                    "commit": commit_sha[:7] if commit_sha else "",
                    "deployed": True,
                }
            return {"success": False, "error": f"GitHub HTTP {res.status_code}: {res.text[:200]}"}
        except Exception as exc:
            logger.error("[APIDiscovery] push error: %s", exc)
            return {"success": False, "error": str(exc)}

    async def _update_tools_init(self, integration: dict) -> None:
        """Agrega el nuevo tool al __init__.py de tools."""
        try:
            class_name = integration.get("class_name", "")
            module = integration.get("module_name", "").replace(".py", "")
            if not class_name or not module:
                return

            init_path = "apps/core/tools/__init__.py"
            check = await self._http.get(
                f"https://api.github.com/repos/{self.repo}/contents/{init_path}",
                headers=self._github_headers,
            )
            if check.status_code != 200:
                return

            data = check.json()
            current = base64.b64decode(data["content"]).decode()
            sha = data["sha"]

            import_line = f"from apps.core.tools.{module} import {class_name}"
            if import_line in current:
                return  # Already imported

            # Add import before __all__
            updated = current.replace(
                "from apps.core.tools.telegram_bot import",
                f"{import_line}\nfrom apps.core.tools.telegram_bot import",
            )

            # Add to __all__
            updated = updated.replace(
                '"AriaTelegramBot", "get_bot",',
                f'"{class_name}",\n    "AriaTelegramBot", "get_bot",',
            )

            body = {
                "message": f"feat: Export {class_name} in tools/__init__.py",
                "content": base64.b64encode(updated.encode()).decode(),
                "branch": "main",
                "sha": sha,
            }
            await self._http.put(
                f"https://api.github.com/repos/{self.repo}/contents/{init_path}",
                headers=self._github_headers,
                json=body,
            )
        except Exception as exc:
            logger.warning("[APIDiscovery] update_init error: %s", exc)

    async def _log_new_integration(self, api_name: str, file_path: str, sha: str) -> None:
        """Registra la nueva integración en Supabase + Redis."""
        try:
            from apps.core.memory.supabase_client import get_db
            from apps.core.memory.redis_client import get_cache
            db = get_db()
            cache = get_cache()

            await db.log_event(
                level="SUCCESS",
                agent="evolution_agent",
                message=f"New API integrated: {api_name} — {file_path}",
                metadata={"sha": sha, "api": api_name},
            )

            # Registro de APIs integradas
            apis_key = "aria:integrated_apis"
            raw = await cache.get(apis_key)
            apis_list = json.loads(raw) if raw else []
            apis_list.append({"api": api_name, "file": file_path, "sha": sha[:7]})
            await cache.set(apis_key, json.dumps(apis_list[-50:]))

        except Exception as exc:
            logger.warning("[APIDiscovery] log error: %s", exc)

    # ══════════════════════════════════════════════════════════════
    # 5. CICLO COMPLETO DE DESCUBRIMIENTO E INTEGRACIÓN
    # ══════════════════════════════════════════════════════════════

    async def run_discovery_cycle(self, mission: str = "maximize digital revenue", max_new_apis: int = 2) -> dict[str, Any]:
        """
        Ciclo completo:
        1. Descubrir APIs relevantes
        2. Evaluar las más prometedoras
        3. Generar código de integración
        4. Pushear a GitHub (deploy automático)
        """
        logger.info("[APIDiscovery] Iniciando ciclo de descubrimiento...")
        results = {"success": True, "integrated": [], "evaluated": [], "mission": mission}

        try:
            # Paso 1: Descubrir APIs relevantes
            candidates = await self.discover_apis_for_mission(mission)
            logger.info("[APIDiscovery] Found %d API candidates", len(candidates))

            # Paso 2: Evaluar las mejores candidatas
            import asyncio
            eval_tasks = [self.evaluate_api_potential(api) for api in candidates[:8]]
            evaluations = await asyncio.gather(*eval_tasks, return_exceptions=True)

            # Filtrar y ordenar por score
            scored = []
            for api, eval_r in zip(candidates[:8], evaluations):
                if isinstance(eval_r, dict) and eval_r.get("success"):
                    ev = eval_r["evaluation"]
                    if ev.get("worth_integrating") and ev.get("score", 0) >= 70:
                        scored.append({**api, "score": ev["score"], "use_cases": ev.get("use_cases", []), "complexity": ev.get("implementation_complexity", "media")})

            scored.sort(key=lambda x: x["score"], reverse=True)
            results["evaluated"] = scored[:5]
            logger.info("[APIDiscovery] %d APIs worth integrating", len(scored))

            # Paso 3: Integrar las mejores (baja/media complejidad primero)
            to_integrate = [a for a in scored if a.get("complexity") != "alta"][:max_new_apis]

            for api in to_integrate:
                logger.info("[APIDiscovery] Integrating: %s (score: %s)", api["name"], api["score"])

                integration = await self.generate_api_integration(api, api.get("use_cases", []))
                if not integration.get("success"):
                    logger.warning("[APIDiscovery] Failed to generate: %s — %s", api["name"], integration.get("error"))
                    continue

                push_result = await self.push_new_integration(integration)

                if push_result.get("success"):
                    results["integrated"].append({
                        "api": api["name"],
                        "file": integration["file_path"],
                        "score": api["score"],
                        "commit": push_result.get("commit", ""),
                        "env_var": integration.get("env_var", ""),
                    })
                    logger.info("[APIDiscovery] ✅ Integrated: %s", api["name"])

        except Exception as exc:
            logger.error("[APIDiscovery] Discovery cycle error: %s", exc)
            results["error"] = str(exc)

        return results

    async def get_integrated_apis(self) -> list[dict]:
        """Lista todas las APIs que ARIA ha integrado autónomamente."""
        try:
            from apps.core.memory.redis_client import get_cache
            raw = await get_cache().get("aria:integrated_apis")
            return json.loads(raw) if raw else []
        except Exception:
            return []
