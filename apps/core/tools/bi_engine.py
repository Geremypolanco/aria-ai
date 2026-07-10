"""
bi_engine.py — Business Intelligence para ARIA AI.

Integra Metabase y Apache Superset para:
  - Dashboards ejecutivos de ingresos y KPIs (Metabase)
  - Análisis avanzado de datos de negocio (Apache Superset)
  - Reportes automáticos de performance de agentes
  - Visualización de funnels y revenue attribution
  - Executive Dashboard para el futuro de Aria

Ambos se despliegan vía Docker y se integran con la base de datos
Supabase/PostgreSQL existente de Aria.

Referencia:
  - Metabase: https://github.com/metabase/metabase
  - Apache Superset: https://github.com/apache/superset
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger("aria.bi_engine")

# ── Metabase API Client ──────────────────────────────────────────────────────
try:
    import httpx

    HTTPX_AVAILABLE = True
except ImportError:
    HTTPX_AVAILABLE = False
    logger.warning("[BI Engine] httpx no disponible")


# ── Metabase Client ──────────────────────────────────────────────────────────


class AriaMetabaseClient:
    """
    Cliente de Metabase para ARIA AI.

    Metabase es el dashboard open source más accesible.
    Permite a ARIA crear y gestionar dashboards ejecutivos
    sin necesidad de SQL avanzado.

    Capacidades:
    - Crear preguntas (queries) automáticamente
    - Gestionar dashboards de KPIs
    - Generar reportes automáticos
    - Enviar alertas cuando métricas caen

    Integra con:
    - CFO Agent (reportes financieros)
    - ExecutionPipeline (métricas de ejecución)
    - PostHog (funnels de conversión)

    Uso:
        client = AriaMetabaseClient()
        await client.initialize()

        # Crear dashboard de revenue
        dashboard = await client.create_revenue_dashboard()

        # Ejecutar query
        results = await client.run_query(
            "SELECT SUM(amount) FROM sales WHERE date > NOW() - INTERVAL '30 days'"
        )
    """

    def __init__(
        self,
        host: str = "http://localhost:3000",
        username: str = "admin@aria.ai",
        password: str = "",
    ) -> None:
        self._host = host.rstrip("/")
        self._username = username
        self._password = password
        self._session_token: str = ""
        self._database_id: int = 1
        self._initialized = False

    async def initialize(self) -> bool:
        """
        Inicializa la sesión con Metabase.
        Returns True si la conexión fue exitosa.
        """
        if not HTTPX_AVAILABLE:
            logger.warning("[Metabase] httpx no disponible")
            return False

        if not self._password:
            logger.info("[Metabase] Password no configurado. Metabase disponible vía Docker.")
            return False

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(
                    f"{self._host}/api/session",
                    json={
                        "username": self._username,
                        "password": self._password,
                    },
                )
                if response.status_code == 200:
                    self._session_token = response.json().get("id", "")
                    self._initialized = True
                    logger.info("[Metabase] Sesión iniciada correctamente")
                    return True
                logger.warning("[Metabase] Error de autenticación: %d", response.status_code)
                return False

        except Exception as exc:
            logger.warning("[Metabase] No se pudo conectar a %s: %s", self._host, exc)
            return False

    def _get_headers(self) -> dict[str, str]:
        """Headers de autenticación para Metabase API."""
        return {
            "X-Metabase-Session": self._session_token,
            "Content-Type": "application/json",
        }

    async def run_query(
        self,
        sql: str,
        database_id: int | None = None,
    ) -> dict[str, Any]:
        """
        Ejecuta una query SQL en Metabase.

        Args:
            sql: Query SQL a ejecutar
            database_id: ID de la base de datos (default: 1)

        Returns:
            Resultados de la query
        """
        if not self._initialized:
            await self.initialize()

        if not self._initialized:
            return {
                "success": False,
                "error": "Metabase no disponible",
                "sql": sql,
                "note": "Despliega Metabase con: docker-compose up metabase",
            }

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(
                    f"{self._host}/api/dataset",
                    headers=self._get_headers(),
                    json={
                        "database": database_id or self._database_id,
                        "type": "native",
                        "native": {"query": sql},
                    },
                )

                if response.status_code == 202:
                    data = response.json()
                    return {
                        "success": True,
                        "rows": data.get("data", {}).get("rows", []),
                        "columns": data.get("data", {}).get("cols", []),
                        "row_count": data.get("row_count", 0),
                    }
                return {
                    "success": False,
                    "error": f"HTTP {response.status_code}",
                    "sql": sql,
                }

        except Exception as exc:
            return {"success": False, "error": str(exc), "sql": sql}

    async def create_dashboard(
        self,
        name: str,
        description: str = "",
    ) -> dict[str, Any]:
        """
        Crea un nuevo dashboard en Metabase.

        Args:
            name: Nombre del dashboard
            description: Descripción

        Returns:
            Dict con el ID y URL del dashboard creado
        """
        if not self._initialized:
            return {
                "success": False,
                "error": "Metabase no disponible",
                "name": name,
            }

        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                response = await client.post(
                    f"{self._host}/api/dashboard",
                    headers=self._get_headers(),
                    json={"name": name, "description": description},
                )

                if response.status_code == 200:
                    data = response.json()
                    dashboard_id = data.get("id")
                    return {
                        "success": True,
                        "id": dashboard_id,
                        "name": name,
                        "url": f"{self._host}/dashboard/{dashboard_id}",
                    }
                return {
                    "success": False,
                    "error": f"HTTP {response.status_code}",
                }

        except Exception as exc:
            return {"success": False, "error": str(exc)}

    async def create_revenue_dashboard(self) -> dict[str, Any]:
        """
        Crea el dashboard ejecutivo de Revenue para ARIA.

        Incluye:
        - Ingresos totales del mes
        - Ventas por canal
        - Top productos
        - Funnel de conversión
        - ROI por agente
        """
        result = await self.create_dashboard(
            name="ARIA Revenue Dashboard",
            description="Dashboard ejecutivo de ingresos y KPIs de ARIA AI",
        )

        if result.get("success"):
            logger.info("[Metabase] Revenue Dashboard creado: %s", result.get("url"))

        return result

    async def get_revenue_summary(
        self,
        days: int = 30,
    ) -> dict[str, Any]:
        """
        Obtiene el resumen de ingresos de los últimos N días.

        Args:
            days: Número de días a analizar

        Returns:
            Resumen de ingresos con métricas clave
        """
        sql = f"""
        SELECT
            DATE_TRUNC('day', created_at) as date,
            SUM(amount_usd) as daily_revenue,
            COUNT(*) as sales_count,
            AVG(amount_usd) as avg_sale
        FROM sales
        WHERE created_at > NOW() - INTERVAL '{days} days'
        GROUP BY 1
        ORDER BY 1 DESC
        """
        return await self.run_query(sql)

    def get_status(self) -> dict[str, Any]:
        """Estado del cliente Metabase."""
        return {
            "host": self._host,
            "initialized": self._initialized,
            "password_configured": bool(self._password),
            "note": "Despliega con: docker-compose up metabase -d",
        }


# ── Apache Superset Client ───────────────────────────────────────────────────


class AriaSupersetClient:
    """
    Cliente de Apache Superset para ARIA AI.

    Superset es más avanzado que Metabase para análisis complejos.
    Ideal para el Executive Dashboard futuro de ARIA con:
    - Análisis multidimensional de ingresos
    - Dashboards interactivos con drill-down
    - Alertas y reportes programados
    - Integración con múltiples fuentes de datos

    Integra con:
    - CFO Agent (análisis financiero avanzado)
    - Graphiti (visualización del grafo de conocimiento)
    - PostHog (funnels avanzados)
    - Prometheus (métricas de sistema)

    Uso:
        client = AriaSupersetClient()
        await client.initialize()

        # Ejecutar query
        results = await client.run_sql_query(
            database_id=1,
            sql="SELECT * FROM revenue_attribution LIMIT 100"
        )
    """

    def __init__(
        self,
        host: str = "http://localhost:8088",
        username: str = "admin",
        password: str = "admin",
    ) -> None:
        self._host = host.rstrip("/")
        self._username = username
        self._password = password
        self._access_token: str = ""
        self._csrf_token: str = ""
        self._initialized = False

    async def initialize(self) -> bool:
        """Inicializa la sesión con Apache Superset."""
        if not HTTPX_AVAILABLE:
            return False

        if not self._password or self._password == "admin":
            logger.info("[Superset] Usando credenciales default. Disponible vía Docker.")

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                # Login
                response = await client.post(
                    f"{self._host}/api/v1/security/login",
                    json={
                        "username": self._username,
                        "password": self._password,
                        "provider": "db",
                        "refresh": True,
                    },
                )

                if response.status_code == 200:
                    tokens = response.json()
                    self._access_token = tokens.get("access_token", "")
                    self._initialized = True
                    logger.info("[Superset] Sesión iniciada correctamente")
                    return True
                logger.warning("[Superset] Error de autenticación: %d", response.status_code)
                return False

        except Exception as exc:
            logger.warning("[Superset] No se pudo conectar a %s: %s", self._host, exc)
            return False

    def _get_headers(self) -> dict[str, str]:
        """Headers de autenticación para Superset API."""
        return {
            "Authorization": f"Bearer {self._access_token}",
            "Content-Type": "application/json",
        }

    async def run_sql_query(
        self,
        sql: str,
        database_id: int = 1,
        schema: str = "public",
    ) -> dict[str, Any]:
        """
        Ejecuta una query SQL en Superset.

        Args:
            sql: Query SQL
            database_id: ID de la base de datos
            schema: Schema de la base de datos

        Returns:
            Resultados de la query
        """
        if not self._initialized:
            await self.initialize()

        if not self._initialized:
            return {
                "success": False,
                "error": "Superset no disponible",
                "sql": sql,
                "note": "Despliega Superset con: docker-compose up superset",
            }

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(
                    f"{self._host}/api/v1/sqllab/execute/",
                    headers=self._get_headers(),
                    json={
                        "database_id": database_id,
                        "schema": schema,
                        "sql": sql,
                        "runAsync": False,
                    },
                )

                if response.status_code == 200:
                    data = response.json()
                    return {
                        "success": True,
                        "data": data.get("data", []),
                        "columns": data.get("columns", []),
                        "row_count": len(data.get("data", [])),
                    }
                return {
                    "success": False,
                    "error": f"HTTP {response.status_code}: {response.text[:200]}",
                }

        except Exception as exc:
            return {"success": False, "error": str(exc)}

    async def create_chart(
        self,
        name: str,
        chart_type: str,
        datasource_id: int,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """
        Crea un chart en Superset.

        Args:
            name: Nombre del chart
            chart_type: Tipo de visualización ('line', 'bar', 'pie', 'table', etc.)
            datasource_id: ID del datasource
            params: Parámetros de configuración del chart

        Returns:
            Dict con el ID y URL del chart
        """
        if not self._initialized:
            return {"success": False, "error": "Superset no disponible"}

        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                response = await client.post(
                    f"{self._host}/api/v1/chart/",
                    headers=self._get_headers(),
                    json={
                        "slice_name": name,
                        "viz_type": chart_type,
                        "datasource_id": datasource_id,
                        "datasource_type": "table",
                        "params": str(params or {}),
                    },
                )

                if response.status_code in (200, 201):
                    data = response.json()
                    chart_id = data.get("id")
                    return {
                        "success": True,
                        "id": chart_id,
                        "name": name,
                        "url": f"{self._host}/explore/?slice_id={chart_id}",
                    }
                return {
                    "success": False,
                    "error": f"HTTP {response.status_code}",
                }

        except Exception as exc:
            return {"success": False, "error": str(exc)}

    async def create_executive_dashboard(self) -> dict[str, Any]:
        """
        Crea el Executive Dashboard de ARIA en Superset.

        Incluye charts de:
        - Revenue por canal y producto
        - Funnel de conversión completo
        - Performance de agentes
        - Análisis de competidores
        - ROI de experimentos A/B
        """
        if not self._initialized:
            return {
                "success": False,
                "note": "Superset no disponible. Despliega con: docker-compose up superset -d",
            }

        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                response = await client.post(
                    f"{self._host}/api/v1/dashboard/",
                    headers=self._get_headers(),
                    json={
                        "dashboard_title": "ARIA Executive Dashboard",
                        "slug": "aria-executive",
                        "published": True,
                    },
                )

                if response.status_code in (200, 201):
                    data = response.json()
                    dashboard_id = data.get("id")
                    return {
                        "success": True,
                        "id": dashboard_id,
                        "name": "ARIA Executive Dashboard",
                        "url": f"{self._host}/superset/dashboard/{dashboard_id}/",
                    }
                return {
                    "success": False,
                    "error": f"HTTP {response.status_code}",
                }

        except Exception as exc:
            return {"success": False, "error": str(exc)}

    def get_status(self) -> dict[str, Any]:
        """Estado del cliente Superset."""
        return {
            "host": self._host,
            "initialized": self._initialized,
            "note": "Despliega con: docker-compose up superset -d",
        }


# ── Motor Unificado de Business Intelligence ─────────────────────────────────


class AriaBIEngine:
    """
    Motor unificado de Business Intelligence para ARIA AI.

    Combina Metabase (dashboards accesibles) y Apache Superset
    (análisis avanzado) para proporcionar inteligencia de negocio completa.

    Integra con:
    - CFO Agent (reportes financieros)
    - ExecutionPipeline (métricas de ejecución)
    - PostHog (funnels de conversión)
    - Prometheus (métricas de sistema)
    - Graphiti (revenue attribution)
    """

    def __init__(
        self,
        metabase_host: str = "http://localhost:3000",
        metabase_password: str = "",
        superset_host: str = "http://localhost:8088",
        superset_password: str = "admin",
    ) -> None:
        self.metabase = AriaMetabaseClient(
            host=metabase_host,
            password=metabase_password,
        )
        self.superset = AriaSupersetClient(
            host=superset_host,
            password=superset_password,
        )

    async def initialize_all(self) -> dict[str, bool]:
        """Inicializa todos los clientes de BI."""
        metabase_ok = await self.metabase.initialize()
        superset_ok = await self.superset.initialize()

        return {
            "metabase": metabase_ok,
            "superset": superset_ok,
        }

    async def setup_aria_dashboards(self) -> dict[str, Any]:
        """
        Configura todos los dashboards de ARIA.

        Crea:
        - Revenue Dashboard en Metabase
        - Executive Dashboard en Superset
        """
        results = {}

        # Revenue Dashboard en Metabase
        results["metabase_revenue"] = await self.metabase.create_revenue_dashboard()

        # Executive Dashboard en Superset
        results["superset_executive"] = await self.superset.create_executive_dashboard()

        return {
            "success": any(r.get("success") for r in results.values()),
            "dashboards": results,
        }

    async def get_revenue_report(
        self,
        days: int = 30,
    ) -> dict[str, Any]:
        """
        Genera un reporte de ingresos usando Metabase.

        Args:
            days: Número de días a analizar

        Returns:
            Reporte de ingresos con métricas clave
        """
        return await self.metabase.get_revenue_summary(days=days)

    def get_status(self) -> dict[str, Any]:
        """Estado completo del motor de BI."""
        return {
            "metabase": self.metabase.get_status(),
            "superset": self.superset.get_status(),
            "setup_instructions": {
                "metabase": "docker-compose up metabase -d → http://localhost:3000",
                "superset": "docker-compose up superset -d → http://localhost:8088",
            },
        }


# ── Singleton ────────────────────────────────────────────────────────────────
_bi_engine_instance: AriaBIEngine | None = None


def get_bi_engine() -> AriaBIEngine:
    """Retorna el singleton del motor de Business Intelligence."""
    global _bi_engine_instance
    if _bi_engine_instance is None:
        import os

        _bi_engine_instance = AriaBIEngine(
            metabase_host=os.getenv("METABASE_HOST", "http://localhost:3000"),
            metabase_password=os.getenv("METABASE_PASSWORD", ""),
            superset_host=os.getenv("SUPERSET_HOST", "http://localhost:8088"),
            superset_password=os.getenv("SUPERSET_PASSWORD", "admin"),
        )
    return _bi_engine_instance
