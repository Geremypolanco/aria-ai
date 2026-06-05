"""
chloe_tools.py -- Integracion de CHLOE API para ARIA AI.

CHLOE es el asistente de IA especializado en economia circular.
Permite a ARIA:
  - Consultar recomendaciones de economia circular por sector
  - Obtener metricas de sostenibilidad y circularidad
  - Analizar cadenas de suministro
  - Validar politicas economicas del EconomicGovernorAgent

Principio: si CHLOE_API no esta configurado, retorna error explicito.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

import httpx

from apps.core.config import settings

logger = logging.getLogger("aria.chloe")


class ChloeTools:
    """Integracion con CHLOE API — IA de economia circular."""

    def __init__(self) -> None:
        self.api_key = settings.CHLOE_API
        self.base_url = settings.CHLOE_API_URL.rstrip("/")

    def _check_config(self) -> Optional[str]:
        if not self.api_key:
            return "CHLOE_API no configurado: agrega CHLOE_API como secret en Fly.io"
        return None

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "User-Agent": "ARIA-AI/2.0",
        }

    # -- CONSULTAS PRINCIPALES ------------------------------------------------

    async def get_circular_recommendations(
        self,
        sector: str,
        context: dict[str, Any],
    ) -> dict[str, Any]:
        """
        Obtiene recomendaciones de economia circular para un sector.

        Returns: recommendations: list, priority: str, impact_score: float.
        """
        err = self._check_config()
        if err:
            return {"success": False, "error": err}
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.post(
                    f"{self.base_url}/recommendations",
                    json={"sector": sector, "context": context},
                    headers=self._headers(),
                )
            if resp.status_code == 401:
                return {"success": False, "error": "CHLOE_API invalido o expirado"}
            if resp.status_code == 404:
                return {"success": False, "error": f"Endpoint no encontrado: {self.base_url}/recommendations"}
            if resp.status_code != 200:
                return {"success": False, "error": f"CHLOE HTTP {resp.status_code}: {resp.text[:200]}"}
            data = resp.json()
            return {
                "success": True,
                "sector": sector,
                "recommendations": data.get("recommendations", []),
                "priority": data.get("priority", "medium"),
                "impact_score": data.get("impact_score", 0.0),
                "metadata": data.get("metadata", {}),
            }
        except httpx.ConnectError:
            return {"success": False, "error": f"No se puede conectar a CHLOE API en {self.base_url}"}
        except Exception as exc:
            logger.error("[CHLOE] Error en get_circular_recommendations: %s", exc)
            return {"success": False, "error": str(exc)}

    async def analyze_supply_chain(
        self,
        chain_data: dict[str, Any],
        sector: str = "digital",
    ) -> dict[str, Any]:
        """
        Analiza una cadena de suministro para detectar ineficiencias circulares.

        Returns: inefficiencies, circular_opportunities, sustainability_score.
        """
        err = self._check_config()
        if err:
            return {"success": False, "error": err}
        try:
            async with httpx.AsyncClient(timeout=45.0) as client:
                resp = await client.post(
                    f"{self.base_url}/supply-chain/analyze",
                    json={"chain_data": chain_data, "sector": sector},
                    headers=self._headers(),
                )
            if resp.status_code not in (200, 201):
                return {"success": False, "error": f"CHLOE HTTP {resp.status_code}: {resp.text[:200]}"}
            data = resp.json()
            return {
                "success": True,
                "inefficiencies": data.get("inefficiencies", []),
                "circular_opportunities": data.get("circular_opportunities", []),
                "sustainability_score": data.get("sustainability_score", 0.0),
                "recommendations": data.get("recommendations", []),
            }
        except Exception as exc:
            logger.error("[CHLOE] Error en analyze_supply_chain: %s", exc)
            return {"success": False, "error": str(exc)}

    async def validate_economic_policy(
        self,
        policy: dict[str, Any],
    ) -> dict[str, Any]:
        """
        Valida una politica economica propuesta por EconomicGovernorAgent.

        Returns: approved: bool, score: float, concerns: list, suggestions: list.
        """
        err = self._check_config()
        if err:
            return {"success": False, "error": err}
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.post(
                    f"{self.base_url}/policy/validate",
                    json={"policy": policy},
                    headers=self._headers(),
                )
            if resp.status_code not in (200, 201):
                return {"success": False, "error": f"CHLOE HTTP {resp.status_code}: {resp.text[:200]}"}
            data = resp.json()
            return {
                "success": True,
                "approved": data.get("approved", False),
                "score": data.get("score", 0.0),
                "concerns": data.get("concerns", []),
                "suggestions": data.get("suggestions", []),
            }
        except Exception as exc:
            logger.error("[CHLOE] Error en validate_economic_policy: %s", exc)
            return {"success": False, "error": str(exc)}

    async def get_sustainability_metrics(
        self,
        sector: str,
        period_days: int = 30,
    ) -> dict[str, Any]:
        """
        Obtiene metricas de sostenibilidad para un sector.

        Returns: circularity_rate, waste_reduction_pct, resource_efficiency, co2_saved_kg.
        """
        err = self._check_config()
        if err:
            return {"success": False, "error": err}
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.get(
                    f"{self.base_url}/metrics/sustainability",
                    params={"sector": sector, "period_days": period_days},
                    headers=self._headers(),
                )
            if resp.status_code != 200:
                return {"success": False, "error": f"CHLOE HTTP {resp.status_code}: {resp.text[:200]}"}
            data = resp.json()
            return {
                "success": True,
                "sector": sector,
                "period_days": period_days,
                "circularity_rate": data.get("circularity_rate", 0.0),
                "waste_reduction_pct": data.get("waste_reduction_pct", 0.0),
                "resource_efficiency": data.get("resource_efficiency", 0.0),
                "co2_saved_kg": data.get("co2_saved_kg", 0.0),
                "score": data.get("overall_score", 0.0),
            }
        except Exception as exc:
            logger.error("[CHLOE] Error en get_sustainability_metrics: %s", exc)
            return {"success": False, "error": str(exc)}

    # -- ESTADO ---------------------------------------------------------------

    async def health_check(self) -> dict[str, Any]:
        """Verifica que CHLOE API esta configurado y accesible."""
        err = self._check_config()
        if err:
            return {"configured": False, "error": err}
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(
                    f"{self.base_url}/health",
                    headers=self._headers(),
                )
            return {
                "configured": True,
                "base_url": self.base_url,
                "reachable": resp.status_code == 200,
                "status": resp.json().get("status", "unknown") if resp.status_code == 200 else f"HTTP {resp.status_code}",
            }
        except Exception as exc:
            return {
                "configured": True,
                "base_url": self.base_url,
                "reachable": False,
                "error": str(exc),
            }
