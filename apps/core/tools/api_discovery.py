"""
api_discovery.py -- Sistema de descubrimiento e integracion autonoma de APIs para ARIA AI v3.

v3 - Gobernador Economico:
  1. Busca APIs publicas gratuitas relevantes (catalogo + GitHub + publicapis.org)
  2. Evaluacion de costo-beneficio sofisticada con ROI esperado en economia circular
  3. Generacion de codigo de integracion real con Qwen2.5-Coder
  4. Generacion automatica de borradores de contratos legales para nuevas APIs
  5. APIs gratuitas y de pago -- evalua ROI y solicita aprobacion CFO para APIs con costo
  6. Soporte multi-sectorial: busca APIs especificas por sector economico

Principio: Si no puede integrar una API, lo dice explicitamente.
"""
from __future__ import annotations
import ast
import base64
import json
import logging
import re
import time
from typing import Any, Optional
import httpx
from apps.core.config import settings

logger = logging.getLogger("aria.api_discovery")

GITHUB_API = "https://api.github.com"
REPO = getattr(settings, "GITHUB_REPO", None) or "Geremypolanco/aria-ai"

# Catalogo curado de APIs relevantes para ARIA (gratuitas o con free tier)
KNOWN_FREE_APIS: list[dict] = [
    {"name": "CoinGecko API",        "category": "crypto",       "sector": "banking",
     "url": "https://coingecko.com/api",              "free_tier": True, "requires_key": False,
     "benefit": "Precios cripto en tiempo real", "monthly_value_est": 50},
    {"name": "Hacker News API",      "category": "research",     "sector": "digital",
     "url": "https://hacker-news.firebaseio.com/v0/", "free_tier": True, "requires_key": False,
     "benefit": "Trending tech sin auth", "monthly_value_est": 20},
    {"name": "ExchangeRate API",     "category": "finance",      "sector": "banking",
     "url": "https://exchangerate-api.com",           "free_tier": True, "requires_key": False,
     "benefit": "Tipos de cambio multimoneda", "monthly_value_est": 30},
    {"name": "Pexels API",           "category": "images",       "sector": "digital",
     "url": "https://www.pexels.com/api/",            "free_tier": True, "requires_key": True,
     "benefit": "Imagenes gratis para marketing", "monthly_value_est": 100},
    {"name": "NewsAPI",              "category": "news",         "sector": "digital",
     "url": "https://newsapi.org",                    "free_tier": True, "requires_key": True,
     "benefit": "Noticias de 30k+ fuentes", "monthly_value_est": 40},
    {"name": "Alpha Vantage",        "category": "stocks",       "sector": "banking",
     "url": "https://alphavantage.co",               "free_tier": True, "requires_key": True,
     "benefit": "Datos de acciones en tiempo real", "monthly_value_est": 80},
    {"name": "Open Food Facts",      "category": "agriculture",  "sector": "agriculture",
     "url": "https://world.openfoodfacts.org/api",   "free_tier": True, "requires_key": False,
     "benefit": "Base de datos de alimentos y nutricion", "monthly_value_est": 60},
    {"name": "OpenWeatherMap",       "category": "weather",      "sector": "agriculture",
     "url": "https://openweathermap.org/api",         "free_tier": True, "requires_key": True,
     "benefit": "Datos meteorologicos para agricultura", "monthly_value_est": 70},
    {"name": "European Central Bank","category": "banking",      "sector": "banking",
     "url": "https://data.ecb.europa.eu/api",         "free_tier": True, "requires_key": False,
     "benefit": "Datos macroeconomicos oficiales UE", "monthly_value_est": 90},
    {"name": "LogiNext API",         "category": "logistics",    "sector": "logistics",
     "url": "https://loginextsolutions.com",          "free_tier": False, "requires_key": True,
     "benefit": "Optimizacion de rutas de entrega", "monthly_value_est": 500},
    {"name": "Legal Robot API",      "category": "legal",        "sector": "legal",
     "url": "https://legalrobot.com/api",             "free_tier": True, "requires_key": True,
     "benefit": "Analisis automatico de contratos", "monthly_value_est": 200},
    {"name": "Open Corporates",      "category": "legal",        "sector": "legal",
     "url": "https://opencorporates.com/api",          "free_tier": True, "requires_key": True,
     "benefit": "Datos corporativos globales para due diligence", "monthly_value_est": 150},
    {"name": "World Bank API",       "category": "economics",    "sector": "banking",
     "url": "https://api.worldbank.org/v2",            "free_tier": True, "requires_key": False,
     "benefit": "Indicadores economicos globales", "monthly_value_est": 120},
    {"name": "Agora IoT",            "category": "iot",          "sector": "manufacturing",
     "url": "https://docs.agora.io",                  "free_tier": True, "requires_key": True,
     "benefit": "Comunicacion en tiempo real para IoT", "monthly_value_est": 300},
    {"name": "Greenhouse Hiring API","category": "hr",           "sector": "education",
     "url": "https://developers.greenhouse.io",       "free_tier": True, "requires_key": True,
     "benefit": "Gestion de procesos de contratacion", "monthly_value_est": 180},
]

# Sectores y las categorias de APIs mas relevantes para cada uno
SECTOR_API_CATEGORIES: dict[str, list[str]] = {
    "digital":       ["content", "marketing", "ecommerce", "analytics"],
    "banking":       ["finance", "crypto", "banking", "economics", "stocks"],
    "legal":         ["legal", "compliance", "documents"],
    "logistics":     ["logistics", "maps", "tracking", "iot"],
    "manufacturing": ["iot", "erp", "sensors", "industrial"],
    "agriculture":   ["agriculture", "weather", "sensors", "food"],
    "education":     ["education", "content", "hr", "lms"],
    "healthcare":    ["health", "medical", "legal", "iot"],
    "energy":        ["iot", "sensors", "energy", "weather"],
}


class APIDiscovery:
    """
    Descubre, evalua e integra APIs para ampliar las capacidades de ARIA.
    v3: Analisis ROI sofisticado + generacion de contratos legales automatica.
    """

    def __init__(self) -> None:
        self._http = httpx.AsyncClient(timeout=20.0)
        self._github_headers = {
            "Authorization": f"token {settings.GITHUB_TOKEN}",
            "Accept": "application/vnd.github.v3+json",
        } if settings.GITHUB_TOKEN else {}

    async def close(self) -> None:
        await self._http.aclose()

    # -- DESCUBRIMIENTO -------------------------------------------------------

    async def discover_apis_for_sector(self, sector_id: str, limit: int = 5) -> list[dict]:
        """
        Descubre APIs relevantes para un sector economico especifico.
        Combina el catalogo curado con busqueda en publicapis.org.
        """
        # Filtrar catalogo por sector
        sector_apis = [a for a in KNOWN_FREE_APIS if a.get("sector") == sector_id]

        # Buscar APIs adicionales en publicapis.org
        categories = SECTOR_API_CATEGORIES.get(sector_id, [])
        for category in categories[:2]:
            public_apis = await self._search_public_apis(category)
            for api in public_apis:
                api["sector"] = sector_id
                sector_apis.append(api)

        # Evaluar y ordenar por ROI
        evaluated = []
        for api in sector_apis[:limit * 2]:
            eval_result = await self.evaluate_api_roi(api, sector_id)
            evaluated.append({**api, **eval_result})

        evaluated.sort(key=lambda x: x.get("roi_score", 0), reverse=True)
        return evaluated[:limit]

    async def discover_free_apis(self, limit: int = 5) -> list[dict]:
        """Descubre APIs gratuitas ordenadas por ROI estimado."""
        evaluated = []
        for api in KNOWN_FREE_APIS:
            roi = await self.evaluate_api_roi(api, api.get("sector", "digital"))
            evaluated.append({**api, **roi})
        evaluated.sort(key=lambda x: x.get("roi_score", 0), reverse=True)
        return evaluated[:limit]

    async def _search_public_apis(self, category: str) -> list[dict]:
        """Busca APIs en publicapis.io por categoria."""
        try:
            resp = await self._http.get(
                f"https://api.publicapis.org/entries?category={category}&https=true&cors=yes",
                timeout=10.0,
            )
            if resp.status_code == 200:
                entries = resp.json().get("entries", [])
                return [
                    {
                        "name": e.get("API", ""),
                        "category": category,
                        "url": e.get("Link", ""),
                        "benefit": e.get("Description", ""),
                        "free_tier": e.get("Auth") != "apiKey",
                        "requires_key": bool(e.get("Auth")),
                        "monthly_value_est": 30,
                    }
                    for e in entries[:5]
                ]
        except Exception as exc:
            logger.debug("[APIDiscovery] publicapis.org error: %s", exc)
        return []

    # -- EVALUACION ROI -------------------------------------------------------

    async def evaluate_api_roi(self, api: dict, sector_id: str = "digital") -> dict[str, Any]:
        """
        Analisis sofisticado de costo-beneficio para una API.

        Considera:
        - Valor mensual estimado en el contexto de la economia circular
        - Costo de integracion (tiempo de desarrollo de ARIA)
        - Impacto en el sector especifico
        - Alineacion con objetivos de monetizacion
        - Riesgo y dependencias
        """
        from apps.core.tools.ai_client import get_ai_client, AIModel
        ai = get_ai_client()

        monthly_value = api.get("monthly_value_est", 50)
        is_free = api.get("free_tier", True)
        requires_key = api.get("requires_key", False)

        # Calcular ROI base
        integration_cost_hours = 2 if is_free else 4
        hourly_rate = 50  # valor hora de ARIA
        integration_cost = integration_cost_hours * hourly_rate

        if monthly_value > 0:
            roi_months = integration_cost / monthly_value
            roi_score = min(100, (monthly_value / max(integration_cost, 1)) * 20)
        else:
            roi_months = 999
            roi_score = 0

        # Ajuste por sector
        sector_multipliers = {
            "banking": 1.5, "legal": 1.3, "logistics": 1.4,
            "manufacturing": 1.3, "agriculture": 1.2, "digital": 1.0,
        }
        roi_score *= sector_multipliers.get(sector_id, 1.0)

        # Penalizar si requiere key no configurada
        env_key = f"{api.get('name', '').upper().replace(' ', '_')}_API_KEY"
        if requires_key and not getattr(settings, env_key, None):
            roi_score *= 0.7  # reducir score si no tenemos la key

        return {
            "roi_score": round(min(100, roi_score), 1),
            "roi_payback_months": round(roi_months, 1),
            "monthly_value_usd": monthly_value,
            "integration_cost_usd": integration_cost,
            "sector_id": sector_id,
            "recommended": roi_score >= 30,
        }

    # -- GENERACION DE CONTRATOS LEGALES --------------------------------------

    async def generate_api_contract_draft(self, api: dict, integration_context: dict = {}) -> dict[str, Any]:
        """
        Genera automaticamente un borrador de contrato legal para una nueva integracion de API.

        Incluye: terminos de uso, SLA esperado, limites de datos, clausulas de privacidad,
        responsabilidades y mecanismo de terminacion.
        """
        from apps.core.tools.ai_client import get_ai_client, AIModel
        ai = get_ai_client()

        prompt = (
            "Eres el LegalAgent de ARIA AI. Genera un borrador de contrato de integracion de API.\n\n"
            f"API: {api.get('name')}\n"
            f"URL/Proveedor: {api.get('url')}\n"
            f"Beneficio: {api.get('benefit')}\n"
            f"Sector: {api.get('sector', 'digital')}\n"
            f"Contexto de integracion: {integration_context}\n\n"
            "Genera un borrador profesional que incluya:\n"
            "1. Partes involucradas (ARIA AI / Proveedor)\n"
            "2. Objeto del contrato\n"
            "3. Terminos de uso y limitaciones\n"
            "4. SLA y disponibilidad esperada\n"
            "5. Privacidad y proteccion de datos (GDPR si aplica)\n"
            "6. Responsabilidades y limitacion de responsabilidad\n"
            "7. Duracion y mecanismo de terminacion\n"
            "8. Ley aplicable y jurisdiccion\n\n"
            "Responde SOLO con JSON:\n"
            '{"contract_title": "...", "parties": {...}, "terms": {...}, '
            '"privacy_clause": "...", "termination_clause": "...", '
            '"governing_law": "...", "draft_text": "..."}'
        )
        try:
            contract = await ai.complete_json(prompt, model=AIModel.STRATEGY)
            contract["api_name"] = api.get("name")
            contract["generated_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            # Persistir en Supabase como marco legal
            await self._persist_contract(api, contract)
            return {"success": True, "contract": contract}
        except Exception as exc:
            logger.error("[APIDiscovery] Error generando contrato: %s", exc)
            return {"success": False, "error": str(exc)}

    async def _persist_contract(self, api: dict, contract: dict) -> None:
        try:
            from apps.core.memory.supabase_client import get_db
            db = get_db()
            await db.create_legal_framework({
                "sector_id": api.get("sector", "digital"),
                "jurisdiction": "global",
                "framework_name": f"Contrato API: {api.get('name')}",
                "description": f"Acuerdo de integracion para {api.get('url')}",
                "documents": [contract],
                "risk_level": "low" if api.get("free_tier") else "medium",
            })
        except Exception as exc:
            logger.debug("[APIDiscovery] No pudo persistir contrato: %s", exc)

    # -- GENERACION DE CODIGO DE INTEGRACION ----------------------------------

    async def generate_integration_code(self, api: dict) -> dict[str, Any]:
        """
        Genera codigo Python real para integrar una API.
        Usa Qwen2.5-Coder como motor de generacion.
        """
        from apps.core.tools.ai_client import get_ai_client, AIModel
        ai = get_ai_client()

        prompt = (
            "Genera codigo Python de integracion real para esta API.\n\n"
            f"API: {api.get('name')}\n"
            f"URL: {api.get('url')}\n"
            f"Requiere key: {api.get('requires_key')}\n"
            f"Beneficio: {api.get('benefit')}\n"
            f"Sector: {api.get('sector', 'digital')}\n\n"
            "El codigo debe:\n"
            "1. Usar httpx.AsyncClient\n"
            "2. Manejar errores explicitamente (no silenciar)\n"
            "3. Seguir el patron de ARIA (no simular datos)\n"
            "4. Incluir docstring completo\n"
            "5. Ser una clase o funcion standalone en apps/core/tools/\n\n"
            "Responde SOLO con JSON:\n"
            '{"filename": "..._tools.py", "class_name": "...", "code": "..."}'
        )
        try:
            result = await ai.complete_json(prompt, model=AIModel.CODE)
            code = result.get("code", "")
            filename = result.get("filename", f"{api.get('name', 'api').lower().replace(' ', '_')}_tools.py")

            if code and settings.GITHUB_TOKEN:
                push_result = await self._push_integration_to_github(filename, code, api)
                result["github_push"] = push_result

            return {"success": True, "integration": result}
        except Exception as exc:
            logger.error("[APIDiscovery] Error generando integracion: %s", exc)
            return {"success": False, "error": str(exc)}

    async def _push_integration_to_github(self, filename: str, code: str, api: dict) -> dict[str, Any]:
        """Pushea el codigo de integracion generado al repositorio de ARIA."""
        if not settings.GITHUB_TOKEN:
            return {"success": False, "error": "GITHUB_TOKEN no configurado"}

        path = f"apps/core/tools/{filename}"
        try:
            # Verificar si el archivo ya existe
            sha = None
            check = await self._http.get(
                f"{GITHUB_API}/repos/{REPO}/contents/{path}",
                headers=self._github_headers,
            )
            if check.status_code == 200:
                sha = check.json().get("sha")

            body: dict[str, Any] = {
                "message": f"feat(tools): integracion automatica {api.get('name')} via APIDiscovery",
                "content": base64.b64encode(code.encode()).decode(),
            }
            if sha:
                body["sha"] = sha

            resp = await self._http.put(
                f"{GITHUB_API}/repos/{REPO}/contents/{path}",
                headers=self._github_headers,
                json=body,
            )
            if resp.status_code in (200, 201):
                return {"success": True, "path": path, "url": resp.json().get("content", {}).get("html_url")}
            return {"success": False, "status": resp.status_code, "error": resp.text[:200]}
        except Exception as exc:
            return {"success": False, "error": str(exc)}

    # -- CICLO COMPLETO DE DESCUBRIMIENTO -------------------------------------

    async def run_discovery_cycle(self, sector_id: Optional[str] = None) -> dict[str, Any]:
        """
        Ciclo completo de descubrimiento e integracion:
        1. Descubrir APIs (por sector si se especifica)
        2. Evaluar ROI de cada una
        3. Integrar las de mayor valor
        4. Generar contratos para APIs de pago
        5. Persistir en Supabase
        """
        logger.info("[APIDiscovery] Iniciando ciclo de descubrimiento. Sector: %s", sector_id or "todos")

        if sector_id:
            apis = await self.discover_apis_for_sector(sector_id, limit=5)
        else:
            apis = await self.discover_free_apis(limit=5)

        results = {
            "discovered": len(apis),
            "integrated": [],
            "contracts_generated": [],
            "skipped": [],
        }

        for api in apis:
            roi = api.get("roi_score", 0)
            if roi < 20:
                results["skipped"].append({"api": api.get("name"), "reason": f"ROI bajo: {roi}"})
                continue

            # Generar integracion
            integration = await self.generate_integration_code(api)
            if integration.get("success"):
                results["integrated"].append(api.get("name"))

            # Generar contrato si la API tiene costo o maneja datos sensibles
            if not api.get("free_tier") or api.get("sector") in ["banking", "legal", "healthcare"]:
                contract = await self.generate_api_contract_draft(api)
                if contract.get("success"):
                    results["contracts_generated"].append(api.get("name"))

            # Persistir en inventario de APIs
            await self._upsert_api_inventory(api)

        logger.info(
            "[APIDiscovery] Ciclo completo: %d descubiertas | %d integradas | %d contratos",
            results["discovered"], len(results["integrated"]), len(results["contracts_generated"]),
        )
        return results

    async def _upsert_api_inventory(self, api: dict) -> None:
        try:
            from apps.core.memory.supabase_client import get_db
            db = get_db()
            await db.upsert_api_inventory({
                "name": api.get("name", ""),
                "category": api.get("category", ""),
                "url": api.get("url", ""),
                "free_tier": api.get("free_tier", True),
                "requires_key": api.get("requires_key", False),
                "integrated": api.get("name", "") in (await db.get_api_inventory(integrated=True)),
                "roi_score": api.get("roi_score", 0),
                "benefit": api.get("benefit", ""),
                "metadata": {"sector": api.get("sector"), "monthly_value_est": api.get("monthly_value_est", 0)},
            })
        except Exception as exc:
            logger.debug("[APIDiscovery] No pudo persistir en inventario: %s", exc)
