"""
api_discovery.py — Sistema de descubrimiento e integracion autonoma de APIs para ARIA AI v2.

ARIA puede:
  1. Buscar APIs publicas gratuitas relevantes a su mision (catalogo + GitHub + publicapis.org)
  2. Evaluar el potencial de cada API con IA
  3. Generar codigo de integracion real con Qwen2.5-Coder
  4. Agregar la integracion a su propio codebase via GitHub
  5. APIs gratuitas y de pago — evalua ROI y solicita aprobacion CFO para APIs con costo

Principio: Si no puede integrar una API, lo dice explicitamente.
"""

from __future__ import annotations

import ast
import base64
import json
import logging
import re
import time
from typing import Any

import httpx

from apps.core.config import settings

logger = logging.getLogger("aria.api_discovery")

GITHUB_API = "https://api.github.com"
REPO = getattr(settings, "GITHUB_REPO", None) or "Geremypolanco/aria-ai"

# Catalogo curado de APIs relevantes para ARIA (todas gratuitas o con free tier)
KNOWN_FREE_APIS: list[dict] = [
    {
        "name": "CoinGecko API",
        "category": "crypto",
        "url": "https://coingecko.com/api",
        "free_tier": True,
        "requires_key": False,
        "benefit": "Precios cripto en tiempo real — sin API key",
    },
    {
        "name": "Hacker News API",
        "category": "research",
        "url": "https://hacker-news.firebaseio.com/v0/",
        "free_tier": True,
        "requires_key": False,
        "benefit": "Trending tech — sin auth",
    },
    {
        "name": "ExchangeRate API",
        "category": "finance",
        "url": "https://exchangerate-api.com",
        "free_tier": True,
        "requires_key": False,
        "benefit": "Tipos de cambio multimoneda — sin key",
    },
    {
        "name": "Pexels API",
        "category": "images",
        "url": "https://www.pexels.com/api/",
        "free_tier": True,
        "requires_key": True,
        "benefit": "Imagenes gratis para marketing",
    },
    {
        "name": "NewsAPI",
        "category": "news",
        "url": "https://newsapi.org",
        "free_tier": True,
        "requires_key": True,
        "benefit": "Noticias de 30,000 fuentes",
    },
    {
        "name": "OpenRouter AI",
        "category": "ai",
        "url": "https://openrouter.ai",
        "free_tier": True,
        "requires_key": True,
        "benefit": "200+ modelos IA con un solo token",
    },
    {
        "name": "Product Hunt API",
        "category": "research",
        "url": "https://api.producthunt.com",
        "free_tier": True,
        "requires_key": True,
        "benefit": "Productos digitales trending",
    },
    {
        "name": "Reddit API",
        "category": "research",
        "url": "https://www.reddit.com/dev/api/",
        "free_tier": True,
        "requires_key": True,
        "benefit": "Investigacion de nichos via subreddits",
    },
    {
        "name": "Discord Webhooks",
        "category": "messaging",
        "url": "https://discord.com/developers",
        "free_tier": True,
        "requires_key": True,
        "benefit": "Notificaciones sin bot",
    },
    {
        "name": "Lemon Squeezy",
        "category": "payments",
        "url": "https://lemonsqueezy.com",
        "free_tier": True,
        "requires_key": True,
        "benefit": "Venta productos digitales — alternativa a Gumroad",
    },
    {
        "name": "Resend Email",
        "category": "email",
        "url": "https://resend.com",
        "free_tier": True,
        "requires_key": True,
        "benefit": "3000 emails/mes gratis",
    },
    {
        "name": "Firecrawl",
        "category": "scraping",
        "url": "https://firecrawl.dev",
        "free_tier": True,
        "requires_key": True,
        "benefit": "Scraping con IA — extrae datos estructurados",
    },
    {
        "name": "Exa AI Search",
        "category": "search",
        "url": "https://exa.ai",
        "free_tier": True,
        "requires_key": True,
        "benefit": "Busqueda semantica en internet",
    },
    {
        "name": "Hunter.io",
        "category": "leads",
        "url": "https://hunter.io",
        "free_tier": True,
        "requires_key": True,
        "benefit": "Encontrar emails de empresas",
    },
    {
        "name": "Cal.com API",
        "category": "scheduling",
        "url": "https://cal.com/docs/api",
        "free_tier": True,
        "requires_key": True,
        "benefit": "Agendar llamadas automaticamente",
    },
    {
        "name": "Bannerbear",
        "category": "images",
        "url": "https://www.bannerbear.com",
        "free_tier": True,
        "requires_key": True,
        "benefit": "Generar imagenes marketing via API",
    },
    {
        "name": "Unsplash API",
        "category": "images",
        "url": "https://unsplash.com/developers",
        "free_tier": True,
        "requires_key": True,
        "benefit": "50 req/hora — imagenes alta calidad",
    },
    {
        "name": "Replicate API",
        "category": "ai",
        "url": "https://replicate.com",
        "free_tier": True,
        "requires_key": True,
        "benefit": "Cualquier modelo IA — imagen, video, audio",
    },
    {
        "name": "Stability AI",
        "category": "images",
        "url": "https://stability.ai",
        "free_tier": True,
        "requires_key": True,
        "benefit": "SDXL, SD3.5 — imagenes fotoreales",
    },
    {
        "name": "Tally Forms",
        "category": "forms",
        "url": "https://tally.so",
        "free_tier": True,
        "requires_key": True,
        "benefit": "Formularios + webhooks para leads",
    },
]

# APIs de alto valor con posible costo mensual — evaluadas por ROI antes de incluirlas
# Aquellas con monthly_cost_usd > MAX_SPEND_WITHOUT_APPROVAL_USD requieren aprobacion CFO
KNOWN_PAID_APIS: list[dict] = [
    {
        "name": "Stripe Payments",
        "category": "payments",
        "url": "https://stripe.com/docs/api",
        "free_tier": True,
        "monthly_cost_usd": 0,
        "requires_key": True,
        "roi_multiplier": 10.0,
        "benefit": "Pagos online — max conversion, 2.9%+0.30 por tx",
    },
    {
        "name": "Apollo.io Leads",
        "category": "leads",
        "url": "https://apolloio.com",
        "free_tier": True,
        "monthly_cost_usd": 0,
        "requires_key": True,
        "roi_multiplier": 8.0,
        "benefit": "50 leads/mes gratis — base de 260M contactos B2B",
    },
    {
        "name": "Paddle Payments",
        "category": "payments",
        "url": "https://paddle.com",
        "free_tier": True,
        "monthly_cost_usd": 0,
        "requires_key": True,
        "roi_multiplier": 9.0,
        "benefit": "Pagos SaaS + gestion fiscal global automatica",
    },
    {
        "name": "ElevenLabs TTS",
        "category": "audio",
        "url": "https://elevenlabs.io",
        "free_tier": True,
        "monthly_cost_usd": 0,
        "requires_key": True,
        "roi_multiplier": 5.0,
        "benefit": "Text-to-speech premium para podcasts/videos",
    },
    {
        "name": "Hotjar Analytics",
        "category": "analytics",
        "url": "https://hotjar.com",
        "free_tier": True,
        "monthly_cost_usd": 0,
        "requires_key": True,
        "roi_multiplier": 4.0,
        "benefit": "Heatmaps y grabacion — optimiza conversion",
    },
    {
        "name": "Mixpanel",
        "category": "analytics",
        "url": "https://mixpanel.com",
        "free_tier": True,
        "monthly_cost_usd": 0,
        "requires_key": True,
        "roi_multiplier": 4.0,
        "benefit": "Analytics de producto — 100k events/mes gratis",
    },
    {
        "name": "Klaviyo Email",
        "category": "email",
        "url": "https://klaviyo.com",
        "free_tier": True,
        "monthly_cost_usd": 0,
        "requires_key": True,
        "roi_multiplier": 7.0,
        "benefit": "Email marketing avanzado — free hasta 500 contactos",
    },
    {
        "name": "Phantombuster",
        "category": "automation",
        "url": "https://phantombuster.com",
        "free_tier": True,
        "monthly_cost_usd": 0,
        "requires_key": True,
        "roi_multiplier": 6.0,
        "benefit": "Automatizacion LinkedIn/Twitter — scraping leads cualificados",
    },
    {
        "name": "Make Automation",
        "category": "automation",
        "url": "https://make.com",
        "free_tier": True,
        "monthly_cost_usd": 0,
        "requires_key": True,
        "roi_multiplier": 5.0,
        "benefit": "1000 operaciones/mes — conecta cualquier herramienta",
    },
    {
        "name": "Webflow CMS",
        "category": "publishing",
        "url": "https://webflow.com",
        "free_tier": True,
        "monthly_cost_usd": 0,
        "requires_key": True,
        "roi_multiplier": 4.0,
        "benefit": "CMS headless + hosting — landing pages sin deploy",
    },
    {
        "name": "Twilio SMS",
        "category": "messaging",
        "url": "https://twilio.com",
        "free_tier": False,
        "monthly_cost_usd": 10,
        "requires_key": True,
        "roi_multiplier": 8.0,
        "benefit": "SMS/WhatsApp recuperacion de carritos — ROI 800%+",
    },
    {
        "name": "Semrush API",
        "category": "seo",
        "url": "https://www.semrush.com/api/",
        "free_tier": False,
        "monthly_cost_usd": 120,
        "requires_key": True,
        "roi_multiplier": 3.0,
        "benefit": "SEO avanzado — keywords, backlinks, competidores",
    },
    {
        "name": "Ahrefs API",
        "category": "seo",
        "url": "https://ahrefs.com/api",
        "free_tier": False,
        "monthly_cost_usd": 99,
        "requires_key": True,
        "roi_multiplier": 3.0,
        "benefit": "SEO research profundo — necesita aprobacion CFO",
    },
    {
        "name": "Descript Video",
        "category": "video",
        "url": "https://descript.com",
        "free_tier": True,
        "monthly_cost_usd": 0,
        "requires_key": True,
        "roi_multiplier": 5.0,
        "benefit": "Edicion video/podcasts con IA — contenido multimedia auto",
    },
]


class APIDiscovery:
    """
    ARIA descubre, evalua e integra nuevas APIs autonomamente.
    Alias principal — usa este nombre para importar desde evolution_agent.
    """

    # Rate limit: 1 integracion cada 40 min
    _last_integration_time: float = 0.0
    MIN_INTEGRATION_INTERVAL_SECONDS: int = 2400

    def __init__(self) -> None:
        self._http = httpx.AsyncClient(timeout=30.0)
        self._token = getattr(settings, "GITHUB_TOKEN", None)
        self._gh_headers = {
            "Authorization": f"Bearer {self._token}",
            "Accept": "application/vnd.github+json",
            "Content-Type": "application/json",
        }

    def is_available(self) -> bool:
        return bool(self._token)

    def _can_push(self) -> bool:
        if not self.is_available():
            return False
        elapsed = time.time() - APIDiscovery._last_integration_time
        return elapsed >= self.MIN_INTEGRATION_INTERVAL_SECONDS

    # ══════════════════════════════════════════════════════════════
    # 1. DESCUBRIMIENTO DE APIS
    # ══════════════════════════════════════════════════════════════

    async def find_relevant_apis(
        self,
        mission: str,
        limit: int = 10,
        include_paid: bool = True,
        max_monthly_cost_usd: float = 50.0,
    ) -> list[dict]:
        """
        Encuentra APIs relevantes para la mision de ARIA.
        Incluye APIs gratuitas y de pago (con filtro ROI).
        Las APIs de pago > max_monthly_cost_usd se marcan para aprobacion CFO.
        """
        # Filtrar catalogo gratuito con IA
        local_apis = await self._filter_catalog_by_mission(mission)

        # Incluir APIs de pago con ROI justificado
        if include_paid:
            paid_filtered = await self._filter_paid_apis_by_roi(
                [
                    a
                    for a in KNOWN_PAID_APIS
                    if a.get("monthly_cost_usd", 0) <= max_monthly_cost_usd
                ],
                mission,
            )
            seen_names = {a["name"].lower() for a in local_apis}
            for api in paid_filtered:
                if api["name"].lower() not in seen_names:
                    local_apis.append(api)
                    seen_names.add(api["name"].lower())

        # Buscar en publicapis.org (sin auth)
        public_apis = await self._fetch_public_apis(limit=20)
        seen_names = {a["name"].lower() for a in local_apis}
        for api in public_apis:
            if api["name"].lower() not in seen_names:
                local_apis.append(api)
                seen_names.add(api["name"].lower())

        # Evaluar relevancia con IA y ordenar
        ranked = await self._rank_apis_by_relevance(local_apis, mission)
        return ranked[:limit]

    async def _filter_paid_apis_by_roi(
        self,
        paid_apis: list[dict],
        mission: str,
    ) -> list[dict]:
        """
        Filtra APIs de pago por ROI estimado.
        Solo incluye las con roi_multiplier >= 3.0 o costo cero.
        Marca con needs_cfo_approval=True las que superan el umbral de gasto.
        """
        max_auto = getattr(settings, "MAX_SPEND_WITHOUT_APPROVAL_USD", 20.0)
        qualified = []
        for api in paid_apis:
            cost = api.get("monthly_cost_usd", 0)
            roi = api.get("roi_multiplier", 1.0)
            if cost == 0:
                qualified.append({**api, "needs_cfo_approval": False})
            elif roi >= 3.0:
                needs_approval = cost > max_auto
                qualified.append({**api, "needs_cfo_approval": needs_approval})
                if needs_approval:
                    logger.info(
                        "[APIDiscovery] '%s' requiere aprobacion CFO (costo: $%.0f/mes, ROI: %.1fx)",
                        api["name"],
                        cost,
                        roi,
                    )
        return qualified

    async def _filter_catalog_by_mission(self, mission: str) -> list[dict]:
        """Filtra el catalogo local con IA para la mision actual."""
        try:
            from apps.core.tools.ai_client import AIModel, get_ai_client

            ai = get_ai_client()
            catalog_text = "\n".join(f"- {a['name']}: {a['benefit']}" for a in KNOWN_FREE_APIS)
            resp = await ai.complete(
                system="Selecciona las APIs mas relevantes para la mision. Responde JSON array de nombres exactos.",
                user=f"Mision: {mission}\n\nAPIs disponibles:\n{catalog_text}\n\n"
                "Devuelve JSON array con los 8 nombres mas relevantes.",
                model=AIModel.FAST,
            )
            if resp and resp.success:
                match = re.search(r"\[.*?\]", str(resp.content), re.DOTALL)
                if match:
                    selected = json.loads(match.group())
                    selected_lower = [n.lower() for n in selected]
                    return [a for a in KNOWN_FREE_APIS if a["name"].lower() in selected_lower]
        except Exception as exc:
            logger.warning("[APIDiscovery] filter_catalog error: %s", exc)
        return KNOWN_FREE_APIS[:8]

    async def _fetch_public_apis(self, limit: int = 15) -> list[dict]:
        """Fetches APIs de publicapis.org."""
        try:
            res = await self._http.get(
                "https://api.publicapis.org/entries",
                params={"https": "true", "cors": "yes"},
                timeout=10.0,
            )
            if res.status_code == 200:
                entries = res.json().get("entries", [])[:limit]
                return [
                    {
                        "name": e.get("API", ""),
                        "description": e.get("Description", ""),
                        "url": e.get("Link", ""),
                        "category": e.get("Category", ""),
                        "benefit": e.get("Description", ""),
                        "free_tier": e.get("Auth", "") in ("", "No", None),
                        "requires_key": e.get("Auth", "") not in ("", "No", None),
                        "source": "publicapis.org",
                    }
                    for e in entries
                    if e.get("API")
                ]
        except Exception as exc:
            logger.warning("[APIDiscovery] fetch_public_apis error: %s", exc)
        return []

    async def _rank_apis_by_relevance(self, apis: list[dict], mission: str) -> list[dict]:
        """Ordena APIs por relevancia usando IA."""
        if not apis:
            return []
        try:
            from apps.core.tools.ai_client import AIModel, get_ai_client

            ai = get_ai_client()
            apis_text = "\n".join(
                f"{i}. {a['name']}: {a.get('benefit', a.get('description', ''))}"
                for i, a in enumerate(apis)
            )
            resp = await ai.complete(
                system="Ordena APIs por relevancia. Responde JSON array de numeros de indices.",
                user=f"Mision: {mission}\n\nAPIs:\n{apis_text}\n\n"
                "Devuelve JSON array con los indices ordenados de mayor a menor relevancia (maximo 10).",
                model=AIModel.FAST,
            )
            if resp and resp.success:
                match = re.search(r"\[[\d,\s]+\]", str(resp.content))
                if match:
                    indices = json.loads(match.group())
                    ranked = []
                    for idx in indices[:10]:
                        if isinstance(idx, int) and 0 <= idx < len(apis):
                            ranked.append(apis[idx])
                    return ranked if ranked else apis[:10]
        except Exception:
            pass
        return apis[:10]

    # ══════════════════════════════════════════════════════════════
    # 2. GENERACION DE CODIGO DE INTEGRACION
    # ══════════════════════════════════════════════════════════════

    async def generate_integration_code(self, api_info: dict) -> dict[str, Any]:
        """
        Genera codigo Python real de integracion para una API.
        Usa Qwen2.5-Coder para generar el modulo completo.
        """
        api_name = api_info.get("name", "Unknown API")
        api_url = api_info.get("url", "")
        api_benefit = api_info.get("benefit", api_info.get("description", ""))
        requires_key = api_info.get("requires_key", True)

        try:
            from apps.core.tools.ai_client import AIModel, get_ai_client

            ai = get_ai_client()

            env_var_name = re.sub(r"[^A-Z0-9]", "_", api_name.upper()) + "_API_KEY"

            resp = await ai.complete(
                system=(
                    "Senior Python developer. Genera modulo de integracion completo. "
                    "Solo codigo Python, sin markdown fences, sin explicaciones. "
                    "Principio: si la API key no esta configurada, retorna error explicito — NUNCA simula."
                ),
                user=(
                    f"Genera un modulo Python completo para integrar '{api_name}'.\n\n"
                    f"URL base: {api_url}\n"
                    f"Beneficio: {api_benefit}\n"
                    f"Requiere API key: {requires_key}\n"
                    f"Variable de entorno: {env_var_name}\n\n"
                    "El modulo debe:\n"
                    f"1. Clase '{api_name.replace(' ', '').replace('/', '').replace('-', '')}Tools'\n"
                    "2. __init__ que verifique disponibilidad de la API key en settings\n"
                    "3. Metodo is_available() -> bool\n"
                    "4. 2-3 metodos utiles con httpx.AsyncClient\n"
                    "5. Manejo de errores explicito en cada metodo\n"
                    "6. Si API key falta: retornar {'success': False, 'error': '<ENV_VAR> no configurado'}\n"
                    "7. Imports: from apps.core.config import settings\n\n"
                    "IMPORTANTE: Codigo real — no simulaciones, no datos hardcodeados."
                ),
                model=AIModel.CODE,
                max_tokens=4000,
            )

            if not resp or not resp.success:
                return {
                    "success": False,
                    "error": f"IA no disponible para generar integracion de {api_name}",
                }

            code = resp.content.strip()
            for fence in ["```python\n", "```python", "```\n", "```"]:
                if code.startswith(fence):
                    code = code[len(fence) :]
            if code.endswith("```"):
                code = code[:-3]
            code = code.strip()

            # Validar sintaxis
            try:
                ast.parse(code)
            except SyntaxError as e:
                return {"success": False, "error": f"Sintaxis invalida en codigo generado: {e}"}

            if len(code.splitlines()) < 20:
                return {"success": False, "error": "Codigo generado demasiado corto — descartado"}

            file_slug = re.sub(r"[^a-z0-9]", "_", api_name.lower()).strip("_")
            target_path = f"apps/core/tools/{file_slug}_tools.py"

            return {
                "success": True,
                "api": api_name,
                "code": code,
                "target_path": target_path,
                "env_var": env_var_name,
                "requires_key": requires_key,
            }
        except Exception as exc:
            logger.error("[APIDiscovery] generate_integration_code error: %s", exc)
            return {"success": False, "error": str(exc)}

    # ══════════════════════════════════════════════════════════════
    # 3. AGREGAR INTEGRACION AL CODEBASE
    # ══════════════════════════════════════════════════════════════

    async def add_integration_to_codebase(
        self,
        api_info: dict,
        code: str,
        target_path: str | None = None,
    ) -> dict[str, Any]:
        """
        Agrega el modulo de integracion generado al codebase via GitHub API.
        Solo crea archivos nuevos — no sobreescribe archivos existentes.
        """
        if not self.is_available():
            return {
                "success": False,
                "error": "GITHUB_TOKEN no configurado — no puedo agregar integraciones al codebase",
            }
        if not self._can_push():
            return {
                "success": False,
                "error": f"Rate limit activo. Espera {self.MIN_INTEGRATION_INTERVAL_SECONDS}s entre integraciones",
            }

        api_name = api_info.get("name", "Unknown")
        if not target_path:
            file_slug = re.sub(r"[^a-z0-9]", "_", api_name.lower()).strip("_")
            target_path = f"apps/core/tools/{file_slug}_tools.py"

        try:
            # Verificar que el archivo no existe ya
            check_res = await self._http.get(
                f"{GITHUB_API}/repos/{REPO}/contents/{target_path}",
                headers=self._gh_headers,
            )
            if check_res.status_code == 200:
                return {
                    "success": False,
                    "error": f"El archivo {target_path} ya existe — no se sobreescribe",
                }

            # Crear el nuevo archivo
            commit_msg = (
                f"feat(integrations): agregar {api_name} tools\n\n"
                f"Integracion autonoma generada por ARIA API Discovery.\n"
                f"Beneficio: {api_info.get('benefit', '')[:100]}"
            )
            encoded = base64.b64encode(code.encode("utf-8")).decode("ascii")
            res = await self._http.put(
                f"{GITHUB_API}/repos/{REPO}/contents/{target_path}",
                headers=self._gh_headers,
                json={
                    "message": commit_msg,
                    "content": encoded,
                    "branch": "main",
                },
            )

            if res.status_code in (200, 201):
                APIDiscovery._last_integration_time = time.time()
                commit_sha = res.json().get("commit", {}).get("sha", "")[:8]
                logger.info(
                    "[APIDiscovery] Integracion agregada: %s → commit %s", target_path, commit_sha
                )
                return {
                    "success": True,
                    "api": api_name,
                    "file": target_path,
                    "commit_sha": commit_sha,
                    "message": f"Integracion de {api_name} agregada al codebase",
                }
            return {
                "success": False,
                "error": f"GitHub HTTP {res.status_code}: {res.text[:200]}",
            }
        except Exception as exc:
            logger.error("[APIDiscovery] add_integration error: %s", exc)
            return {"success": False, "error": str(exc)}

    # ══════════════════════════════════════════════════════════════
    # 4. FLUJO COMPLETO: DESCUBRIR → EVALUAR → INTEGRAR
    # ══════════════════════════════════════════════════════════════

    async def auto_discover_and_integrate(
        self,
        mission: str = "maximize autonomous digital revenue",
        max_integrations: int = 1,
    ) -> list[dict[str, Any]]:
        """
        Flujo completo de descubrimiento e integracion autonoma.
        Solo integra APIs gratuitas — reporta explicitamente si no puede integrar algo.
        """
        if not self.is_available():
            return [
                {
                    "success": False,
                    "error": "GITHUB_TOKEN no configurado — no puedo integrar APIs autonomamente",
                }
            ]

        candidates = await self.find_relevant_apis(mission, limit=max_integrations * 3)
        if not candidates:
            return [{"success": False, "error": "No se encontraron APIs candidatas"}]

        results = []
        for api in candidates[:max_integrations]:
            gen_result = await self.generate_integration_code(api)
            if not gen_result["success"]:
                results.append(
                    {
                        "success": False,
                        "api": api.get("name"),
                        "error": gen_result["error"],
                    }
                )
                continue

            push_result = await self.add_integration_to_codebase(
                api, gen_result["code"], gen_result.get("target_path")
            )
            results.append(
                {
                    "success": push_result["success"],
                    "api": api.get("name"),
                    "benefit": api.get("benefit"),
                    "file": gen_result.get("target_path"),
                    "commit_sha": push_result.get("commit_sha"),
                    "error": push_result.get("error"),
                }
            )

        return results


# Alias para compatibilidad
APIDiscoveryEngine = APIDiscovery
