"""
ARIA Agent System — Cliente Hashicorp Vault.
Autenticación vía AppRole o Token Directo (dev).
Manejo de secrets con auditoría integrada.
"""
from __future__ import annotations

import json
import logging
from typing import Any

import httpx

from core.config.settings import settings

logger = logging.getLogger("aria.vault")


class VaultClientError(Exception):
    """Error base del cliente Vault."""
    pass


class VaultAuthError(VaultClientError):
    """Error de autenticación contra Vault."""
    pass


class VaultClient:
    """
    Cliente Vault con soporte para:
    - Token auth (dev mode)
    - AppRole auth (producción)
    - KV v2 secrets engine
    - Auditoría de acceso
    """

    def __init__(self, addr: str | None = None, token: str | None = None):
        self.addr = (addr or settings.VAULT_ADDR).rstrip("/")
        self._token = token
        self._role_id = settings.VAULT_APPROLE_ROLE_ID
        self._secret_id = settings.VAULT_APPROLE_SECRET_ID
        self._client_token: str | None = None
        self._token_accessor: str | None = None
        self._http: httpx.AsyncClient | None = None

    async def __aenter__(self):
        await self._ensure_client()
        return self

    async def __aexit__(self, *args):
        await self.close()

    async def _ensure_client(self) -> None:
        if self._http is None:
            self._http = httpx.AsyncClient(
                base_url=f"{self.addr}/v1",
                timeout=10.0,
            )

    async def authenticate(self) -> str:
        """
        Autentica contra Vault.
        Retorna el token de acceso.
        """
        await self._ensure_client()

        # 1. Si ya tenemos un token directo, úsalo
        if self._token:
            self._client_token = self._token
            logger.info("Vault: usando token directo")
            return self._client_token

        # 2. Si tenemos credenciales AppRole, autentica
        if self._role_id and self._secret_id:
            return await self._auth_approle()

        # 3. Fallback: token de entorno
        env_token = settings.vault_token
        if env_token:
            self._client_token = env_token
            logger.info("Vault: usando token de entorno")
            return self._client_token

        raise VaultAuthError(
            "No hay credenciales Vault disponibles. "
            "Configura VAULT_DEV_ROOT_TOKEN_ID o VAULT_APPROLE_ROLE_ID + VAULT_APPROLE_SECRET_ID"
        )

    async def _auth_approle(self) -> str:
        """Autentica usando AppRole."""
        try:
            response = await self._http.post(
                "/auth/approle/login",
                json={
                    "role_id": self._role_id,
                    "secret_id": self._secret_id,
                },
            )
            response.raise_for_status()
            data = response.json()
            self._client_token = data["auth"]["client_token"]
            self._token_accessor = data["auth"].get("accessor")
            logger.info("Vault: autenticado vía AppRole exitosamente")
            return self._client_token
        except httpx.HTTPStatusError as e:
            raise VaultAuthError(f"Error AppRole auth: {e.response.status_code} - {e.response.text}") from e
        except Exception as e:
            raise VaultAuthError(f"Error conectando a Vault: {e}") from e

    async def _ensure_authenticated(self) -> str:
        """Asegura que estamos autenticados."""
        if self._client_token is None:
            return await self.authenticate()
        return self._client_token

    async def get_secret(self, path: str, key: str | None = None) -> Any:
        """
        Lee un secreto de Vault KV v2.
        path: ruta del secreto (ej: "secret/data/aria/shopify")
        key: clave específica (opcional, si es None retorna todo)
        """
        token = await self._ensure_authenticated()
        await self._ensure_client()

        # KV v2 requiere prefijo /data/
        full_path = f"/secret/data/{path}" if not path.startswith("secret/") else f"/{path}"
        if "/data/" not in full_path:
            full_path = full_path.replace("/secret/", "/secret/data/", 1)

        try:
            response = await self._http.get(
                full_path,
                headers={"X-Vault-Token": token},
            )
            if response.status_code == 404:
                logger.warning("Vault: secreto no encontrado en %s", path)
                return None
            response.raise_for_status()

            data = response.json()
            secret_data = data.get("data", {}).get("data", {})

            if key:
                return secret_data.get(key)
            return secret_data

        except httpx.HTTPStatusError as e:
            logger.error("Vault get error: %s - %s", e.response.status_code, e.response.text)
            raise VaultClientError(f"Error leyendo secreto {path}: {e.response.status_code}") from e

    async def set_secret(self, path: str, data: dict[str, Any], cas: int | None = None) -> bool:
        """
        Escribe un secreto en Vault KV v2.
        path: ruta del secreto
        data: dict con los valores a guardar
        cas: Check-And-Set (opcional, versión esperada)
        """
        token = await self._ensure_authenticated()
        await self._ensure_client()

        full_path = f"/secret/data/{path}" if not path.startswith("secret/") else f"/{path}"
        if "/data/" not in full_path:
            full_path = full_path.replace("/secret/", "/secret/data/", 1)

        payload: dict[str, Any] = {"data": data}
        if cas is not None:
            payload["options"] = {"cas": cas}

        try:
            response = await self._http.post(
                full_path,
                headers={"X-Vault-Token": token},
                json=payload,
            )
            response.raise_for_status()
            return True
        except httpx.HTTPStatusError as e:
            logger.error("Vault set error: %s - %s", e.response.status_code, e.response.text)
            raise VaultClientError(f"Error escribiendo secreto {path}: {e.response.status_code}") from e

    async def list_secrets(self, path: str) -> list[str] | None:
        """Lista los secretos en una ruta."""
        token = await self._ensure_authenticated()
        await self._ensure_client()

        full_path = f"/secret/metadata/{path}" if not path.startswith("secret/") else f"/{path}"
        if "/metadata/" not in full_path:
            full_path = full_path.replace("/secret/", "/secret/metadata/", 1)

        try:
            response = await self._http.request(
                "LIST",
                full_path,
                headers={"X-Vault-Token": token},
            )
            if response.status_code == 404:
                return []
            response.raise_for_status()
            return response.json().get("data", {}).get("keys", [])
        except httpx.HTTPStatusError as e:
            logger.error("Vault list error: %s", e.response.status_code)
            return None

    async def delete_secret(self, path: str) -> bool:
        """Elimina un secreto."""
        token = await self._ensure_authenticated()
        await self._ensure_client()

        full_path = f"/secret/data/{path}" if not path.startswith("secret/") else f"/{path}"
        if "/data/" not in full_path:
            full_path = full_path.replace("/secret/", "/secret/data/", 1)

        try:
            response = await self._http.delete(
                full_path,
                headers={"X-Vault-Token": token},
            )
            response.raise_for_status()
            return True
        except httpx.HTTPStatusError as e:
            logger.error("Vault delete error: %s", e.response.status_code)
            return False

    async def health(self) -> dict:
        """Verifica el estado del servidor Vault."""
        await self._ensure_client()
        try:
            resp = await self._http.get("/sys/health")
            return {
                "status": "ok" if resp.status_code == 200 else "degraded",
                "code": resp.status_code,
                "data": resp.json() if resp.status_code < 500 else {"error": "unavailable"},
            }
        except Exception as e:
            return {"status": "error", "message": str(e)}

    async def close(self) -> None:
        """Cierra el cliente HTTP."""
        if self._http:
            await self._http.aclose()
            self._http = None


# ── Instancia global ─────────────────────────────────────
_client: VaultClient | None = None


async def get_vault_client() -> VaultClient:
    """Retorna el cliente Vault (singleton)."""
    global _client
    if _client is None:
        _client = VaultClient()
        await _client.authenticate()
    return _client
