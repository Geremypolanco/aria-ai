"""
cloudinary_tools.py -- Integracion de Cloudinary para ARIA AI.

Permite a todos los agentes:
  - Subir imagenes, videos y archivos desde URL o bytes
  - Transformar y optimizar media (resize, webp, auto-quality)
  - Generar URLs con transformaciones
  - Registrar cada asset en Supabase (media_assets)
  - Gestionar carpetas y tags por agente/sector

Principio: si Cloudinary no esta configurado, retorna error explicito.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

import httpx

from apps.core.config import settings

logger = logging.getLogger("aria.cloudinary")


class CloudinaryTools:
    """Herramienta de gestion de media assets via Cloudinary REST API."""

    UPLOAD_URL = "https://api.cloudinary.com/v1_1/{cloud}/{resource_type}/upload"
    ADMIN_URL = "https://api.cloudinary.com/v1_1/{cloud}"

    def __init__(self) -> None:
        self.cloud = settings.CLOUDINARY_CLOUD_NAME
        self.api_key = settings.CLOUDINARY_API_KEY
        self.api_secret = settings.CLOUDINARY_API_SECRET

    def _check_config(self) -> Optional[str]:
        if not self.cloud or not self.api_key or not self.api_secret:
            return (
                "Cloudinary no configurado: falta CLOUDINARY_CLOUD_NAME, "
                "CLOUDINARY_API_KEY o CLOUDINARY_API_SECRET"
            )
        return None

    def _sign(self, params: dict) -> str:
        import hashlib
        sorted_params = "&".join(f"{k}={v}" for k, v in sorted(params.items()))
        return hashlib.sha1(f"{sorted_params}{self.api_secret}".encode()).hexdigest()

    # -- SUBIDA ---------------------------------------------------------------

    async def upload_from_url(
        self,
        url: str,
        folder: str = "aria",
        tags: Optional[list[str]] = None,
        resource_type: str = "image",
        agent_id: str = "system",
    ) -> dict[str, Any]:
        """Sube un archivo desde una URL publica a Cloudinary."""
        err = self._check_config()
        if err:
            return {"success": False, "error": err}

        try:
            import time
            timestamp = str(int(time.time()))
            folder_clean = folder.strip("/") or "aria"

            sign_params: dict = {"folder": folder_clean, "timestamp": timestamp}
            if tags:
                sign_params["tags"] = ",".join(tags)

            form_data = {
                "file": url,
                "folder": folder_clean,
                "timestamp": timestamp,
                "api_key": self.api_key,
                "signature": self._sign(sign_params),
            }
            if tags:
                form_data["tags"] = ",".join(tags)

            upload_url = self.UPLOAD_URL.format(cloud=self.cloud, resource_type=resource_type)
            async with httpx.AsyncClient(timeout=60.0) as client:
                resp = await client.post(upload_url, data=form_data)

            if resp.status_code not in (200, 201):
                return {"success": False, "error": f"Cloudinary HTTP {resp.status_code}: {resp.text[:200]}"}

            data = resp.json()
            if "error" in data:
                return {"success": False, "error": data["error"].get("message", str(data["error"]))}

            asset = {
                "success": True,
                "public_id": data.get("public_id", ""),
                "url": data.get("url", ""),
                "secure_url": data.get("secure_url", ""),
                "resource_type": resource_type,
                "format": data.get("format", ""),
                "bytes": data.get("bytes", 0),
                "width": data.get("width"),
                "height": data.get("height"),
                "agent_id": agent_id,
                "tags": tags or [],
                "metadata": {"original_url": url, "folder": folder_clean},
            }

            try:
                from apps.core.memory.supabase_client import get_db
                await get_db().record_media_asset(asset)
            except Exception as db_exc:
                logger.warning("No se pudo registrar asset en Supabase: %s", db_exc)

            logger.info("[Cloudinary] Asset subido: %s (%s bytes)", asset["public_id"], asset["bytes"])
            return asset

        except Exception as exc:
            logger.error("[Cloudinary] Error subiendo desde URL: %s", exc)
            return {"success": False, "error": str(exc)}

    async def upload_bytes(
        self,
        data: bytes,
        filename: str,
        folder: str = "aria",
        resource_type: str = "image",
        tags: Optional[list[str]] = None,
        agent_id: str = "system",
    ) -> dict[str, Any]:
        """Sube bytes directamente a Cloudinary."""
        err = self._check_config()
        if err:
            return {"success": False, "error": err}

        try:
            import base64, mimetypes, time
            timestamp = str(int(time.time()))
            folder_clean = folder.strip("/") or "aria"

            sign_params: dict = {"folder": folder_clean, "timestamp": timestamp}
            if tags:
                sign_params["tags"] = ",".join(tags)

            mime = mimetypes.guess_type(filename)[0] or "application/octet-stream"
            b64 = base64.b64encode(data).decode()
            data_uri = f"data:{mime};base64,{b64}"

            form_data = {
                "file": data_uri,
                "folder": folder_clean,
                "timestamp": timestamp,
                "api_key": self.api_key,
                "signature": self._sign(sign_params),
            }
            if tags:
                form_data["tags"] = ",".join(tags)

            upload_url = self.UPLOAD_URL.format(cloud=self.cloud, resource_type=resource_type)
            async with httpx.AsyncClient(timeout=120.0) as client:
                resp = await client.post(upload_url, data=form_data)

            if resp.status_code not in (200, 201):
                return {"success": False, "error": f"Cloudinary HTTP {resp.status_code}: {resp.text[:200]}"}

            res_data = resp.json()
            if "error" in res_data:
                return {"success": False, "error": res_data["error"].get("message", str(res_data["error"]))}

            asset = {
                "success": True,
                "public_id": res_data.get("public_id", ""),
                "url": res_data.get("url", ""),
                "secure_url": res_data.get("secure_url", ""),
                "resource_type": resource_type,
                "format": res_data.get("format", ""),
                "bytes": res_data.get("bytes", 0),
                "agent_id": agent_id,
                "tags": tags or [],
                "metadata": {"filename": filename, "folder": folder_clean},
            }

            try:
                from apps.core.memory.supabase_client import get_db
                await get_db().record_media_asset(asset)
            except Exception:
                pass

            return asset

        except Exception as exc:
            logger.error("[Cloudinary] Error subiendo bytes: %s", exc)
            return {"success": False, "error": str(exc)}

    # -- TRANSFORMACIONES -----------------------------------------------------

    def build_transform_url(
        self,
        public_id: str,
        width: Optional[int] = None,
        height: Optional[int] = None,
        crop: str = "fill",
        quality: str = "auto",
        format: str = "webp",
        resource_type: str = "image",
    ) -> str:
        """Construye una URL de Cloudinary con transformaciones."""
        if not self.cloud:
            return ""
        transforms = []
        if width:
            transforms.append(f"w_{width}")
        if height:
            transforms.append(f"h_{height}")
        if width or height:
            transforms.append(f"c_{crop}")
        transforms.append(f"q_{quality}")
        transforms.append(f"f_{format}")
        transform_str = ",".join(transforms)
        return f"https://res.cloudinary.com/{self.cloud}/{resource_type}/upload/{transform_str}/{public_id}"

    # -- LISTADO --------------------------------------------------------------

    async def list_assets(
        self,
        folder: str = "aria",
        resource_type: str = "image",
        max_results: int = 50,
    ) -> dict[str, Any]:
        """Lista assets en una carpeta de Cloudinary."""
        err = self._check_config()
        if err:
            return {"success": False, "error": err}
        try:
            url = f"{self.ADMIN_URL.format(cloud=self.cloud)}/resources/{resource_type}"
            params = {"prefix": folder, "max_results": max_results, "type": "upload"}
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.get(url, params=params, auth=(self.api_key, self.api_secret))
            if resp.status_code != 200:
                return {"success": False, "error": f"HTTP {resp.status_code}: {resp.text[:200]}"}
            data = resp.json()
            return {"success": True, "assets": data.get("resources", []), "count": len(data.get("resources", []))}
        except Exception as exc:
            return {"success": False, "error": str(exc)}

    async def delete_asset(self, public_id: str, resource_type: str = "image") -> dict[str, Any]:
        """Elimina un asset de Cloudinary por su public_id."""
        err = self._check_config()
        if err:
            return {"success": False, "error": err}
        try:
            import time
            timestamp = str(int(time.time()))
            sign_params = {"public_id": public_id, "timestamp": timestamp}
            url = f"{self.ADMIN_URL.format(cloud=self.cloud)}/resources/{resource_type}/upload"
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.delete(url, params={
                    "public_ids[]": public_id, "timestamp": timestamp,
                    "api_key": self.api_key, "signature": self._sign(sign_params),
                })
            data = resp.json()
            return {"success": True, "deleted": data.get("deleted", {})}
        except Exception as exc:
            return {"success": False, "error": str(exc)}

    # -- ESTADO ---------------------------------------------------------------

    async def health_check(self) -> dict[str, Any]:
        """Verifica que Cloudinary esta configurado y accesible."""
        err = self._check_config()
        if err:
            return {"configured": False, "error": err}
        try:
            url = f"{self.ADMIN_URL.format(cloud=self.cloud)}/ping"
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(url, auth=(self.api_key, self.api_secret))
            return {
                "configured": True,
                "cloud": self.cloud,
                "reachable": resp.status_code == 200,
                "status": resp.json().get("status", "unknown") if resp.status_code == 200 else f"HTTP {resp.status_code}",
            }
        except Exception as exc:
            return {"configured": True, "cloud": self.cloud, "reachable": False, "error": str(exc)}
