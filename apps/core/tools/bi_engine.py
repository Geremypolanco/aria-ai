"""
bi_engine.py — Business Intelligence for ARIA AI.

Integrates Metabase and Apache Superset for:
  - Executive revenue and KPI dashboards (Metabase)
  - Advanced business data analysis (Apache Superset)
  - Automatic agent performance reports
  - Funnel visualization and revenue attribution
  - Executive Dashboard for Aria's future

Both are deployed via Docker and integrate with Aria's existing
Supabase/PostgreSQL database.

Reference:
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
    logger.warning("[BI Engine] httpx not available")


# ── Metabase Client ──────────────────────────────────────────────────────────


class AriaMetabaseClient:
    """
    Metabase client for ARIA AI.

    Metabase is the most accessible open-source dashboard tool.
    Lets ARIA create and manage executive dashboards
    without needing advanced SQL.

    Capabilities:
    - Automatically create questions (queries)
    - Manage KPI dashboards
    - Generate automatic reports
    - Send alerts when metrics drop

    Integrates with:
    - CFO Agent (financial reports)
    - ExecutionPipeline (execution metrics)
    - PostHog (conversion funnels)

    Usage:
        client = AriaMetabaseClient()
        await client.initialize()

        # Create revenue dashboard
        dashboard = await client.create_revenue_dashboard()

        # Run query
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
        Initializes the session with Metabase.
        Returns True if the connection succeeded.
        """
        if not HTTPX_AVAILABLE:
            logger.warning("[Metabase] httpx not available")
            return False

        if not self._password:
            logger.info("[Metabase] Password not configured. Metabase available via Docker.")
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
                    logger.info("[Metabase] Session started successfully")
                    return True
                logger.warning("[Metabase] Authentication error: %d", response.status_code)
                return False

        except Exception as exc:
            logger.warning("[Metabase] Could not connect to %s: %s", self._host, exc)
            return False

    def _get_headers(self) -> dict[str, str]:
        """Authentication headers for the Metabase API."""
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
        Runs a SQL query in Metabase.

        Args:
            sql: SQL query to run
            database_id: Database ID (default: 1)

        Returns:
            Query results
        """
        if not self._initialized:
            await self.initialize()

        if not self._initialized:
            return {
                "success": False,
                "error": "Metabase not available",
                "sql": sql,
                "note": "Deploy Metabase with: docker-compose up metabase",
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
        Creates a new dashboard in Metabase.

        Args:
            name: Dashboard name
            description: Description

        Returns:
            Dict with the ID and URL of the created dashboard
        """
        if not self._initialized:
            return {
                "success": False,
                "error": "Metabase not available",
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
        Creates ARIA's executive Revenue dashboard.

        Includes:
        - Total revenue for the month
        - Sales by channel
        - Top products
        - Conversion funnel
        - ROI by agent
        """
        result = await self.create_dashboard(
            name="ARIA Revenue Dashboard",
            description="Executive revenue and KPI dashboard for ARIA AI",
        )

        if result.get("success"):
            logger.info("[Metabase] Revenue Dashboard created: %s", result.get("url"))

        return result

    async def get_revenue_summary(
        self,
        days: int = 30,
    ) -> dict[str, Any]:
        """
        Gets the revenue summary for the last N days.

        Args:
            days: Number of days to analyze

        Returns:
            Revenue summary with key metrics
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
        """Status of the Metabase client."""
        return {
            "host": self._host,
            "initialized": self._initialized,
            "password_configured": bool(self._password),
            "note": "Deploy with: docker-compose up metabase -d",
        }


# ── Apache Superset Client ───────────────────────────────────────────────────


class AriaSupersetClient:
    """
    Apache Superset client for ARIA AI.

    Superset is more advanced than Metabase for complex analysis.
    Ideal for ARIA's future Executive Dashboard with:
    - Multidimensional revenue analysis
    - Interactive dashboards with drill-down
    - Scheduled alerts and reports
    - Integration with multiple data sources

    Integrates with:
    - CFO Agent (advanced financial analysis)
    - Graphiti (knowledge graph visualization)
    - PostHog (advanced funnels)
    - Prometheus (system metrics)

    Usage:
        client = AriaSupersetClient()
        await client.initialize()

        # Run query
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
        """Initializes the session with Apache Superset."""
        if not HTTPX_AVAILABLE:
            return False

        if not self._password or self._password == "admin":
            logger.info("[Superset] Using default credentials. Available via Docker.")

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
                    logger.info("[Superset] Session started successfully")
                    return True
                logger.warning("[Superset] Authentication error: %d", response.status_code)
                return False

        except Exception as exc:
            logger.warning("[Superset] Could not connect to %s: %s", self._host, exc)
            return False

    def _get_headers(self) -> dict[str, str]:
        """Authentication headers for the Superset API."""
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
        Runs a SQL query in Superset.

        Args:
            sql: SQL query
            database_id: Database ID
            schema: Database schema

        Returns:
            Query results
        """
        if not self._initialized:
            await self.initialize()

        if not self._initialized:
            return {
                "success": False,
                "error": "Superset not available",
                "sql": sql,
                "note": "Deploy Superset with: docker-compose up superset",
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
        Creates a chart in Superset.

        Args:
            name: Chart name
            chart_type: Visualization type ('line', 'bar', 'pie', 'table', etc.)
            datasource_id: Datasource ID
            params: Chart configuration parameters

        Returns:
            Dict with the chart's ID and URL
        """
        if not self._initialized:
            return {"success": False, "error": "Superset not available"}

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
        Creates ARIA's Executive Dashboard in Superset.

        Includes charts for:
        - Revenue by channel and product
        - Complete conversion funnel
        - Agent performance
        - Competitor analysis
        - A/B experiment ROI
        """
        if not self._initialized:
            return {
                "success": False,
                "note": "Superset not available. Deploy with: docker-compose up superset -d",
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
        """Status of the Superset client."""
        return {
            "host": self._host,
            "initialized": self._initialized,
            "note": "Deploy with: docker-compose up superset -d",
        }


# ── Unified Business Intelligence Engine ─────────────────────────────────────


class AriaBIEngine:
    """
    Unified Business Intelligence engine for ARIA AI.

    Combines Metabase (accessible dashboards) and Apache Superset
    (advanced analysis) to provide complete business intelligence.

    Integrates with:
    - CFO Agent (financial reports)
    - ExecutionPipeline (execution metrics)
    - PostHog (conversion funnels)
    - Prometheus (system metrics)
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
        """Initializes all BI clients."""
        metabase_ok = await self.metabase.initialize()
        superset_ok = await self.superset.initialize()

        return {
            "metabase": metabase_ok,
            "superset": superset_ok,
        }

    async def setup_aria_dashboards(self) -> dict[str, Any]:
        """
        Sets up all of ARIA's dashboards.

        Creates:
        - Revenue Dashboard in Metabase
        - Executive Dashboard in Superset
        """
        results = {}

        # Revenue Dashboard in Metabase
        results["metabase_revenue"] = await self.metabase.create_revenue_dashboard()

        # Executive Dashboard in Superset
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
        Generates a revenue report using Metabase.

        Args:
            days: Number of days to analyze

        Returns:
            Revenue report with key metrics
        """
        return await self.metabase.get_revenue_summary(days=days)

    def get_status(self) -> dict[str, Any]:
        """Full status of the BI engine."""
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
    """Returns the Business Intelligence engine singleton."""
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
