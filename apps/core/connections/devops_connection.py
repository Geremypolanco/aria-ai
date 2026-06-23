"""
DevOps connection para ARIA AI.
Soporta Netlify, Cloudflare, Firebase (Google), AWS S3.
Todos usan API tokens/keys.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

import httpx

logger = logging.getLogger("aria.connections.devops")


class NetlifyConnection:
    """Netlify via Personal Access Token."""

    API = "https://api.netlify.com/api/v1"

    def _token(self) -> Optional[str]:
        from apps.core.config import settings
        return getattr(settings, "NETLIFY_TOKEN", None)

    def _h(self) -> dict:
        tok = self._token() or ""
        return {"Authorization": f"Bearer {tok}", "Accept": "application/json"}

    async def list_sites(self) -> list[dict]:
        token = self._token()
        if not token:
            return [{"error": "NETLIFY_TOKEN no configurado"}]
        async with httpx.AsyncClient(timeout=15.0) as http:
            r = await http.get(f"{self.API}/sites", headers=self._h())
            r.raise_for_status()
            return [
                {
                    "id": s.get("id"),
                    "name": s.get("name"),
                    "url": s.get("url"),
                    "state": s.get("state"),
                    "updated_at": s.get("updated_at"),
                }
                for s in r.json()
            ]

    async def get_deploys(self, site_id: str, limit: int = 10) -> list[dict]:
        token = self._token()
        if not token:
            return [{"error": "NETLIFY_TOKEN no configurado"}]
        async with httpx.AsyncClient(timeout=15.0) as http:
            r = await http.get(
                f"{self.API}/sites/{site_id}/deploys",
                headers=self._h(),
                params={"per_page": limit},
            )
            r.raise_for_status()
            return [
                {
                    "id": d.get("id"),
                    "state": d.get("state"),
                    "branch": d.get("branch"),
                    "deploy_url": d.get("deploy_url"),
                    "created_at": d.get("created_at"),
                    "error_message": d.get("error_message"),
                }
                for d in r.json()
            ]

    async def trigger_deploy(self, site_id: str) -> dict:
        token = self._token()
        if not token:
            return {"error": "NETLIFY_TOKEN no configurado"}
        async with httpx.AsyncClient(timeout=15.0) as http:
            r = await http.post(f"{self.API}/sites/{site_id}/builds", headers=self._h())
            return {"success": r.status_code in (200, 201), "id": r.json().get("id")}

    async def get_env_vars(self, site_id: str) -> list[dict]:
        token = self._token()
        if not token:
            return [{"error": "NETLIFY_TOKEN no configurado"}]
        async with httpx.AsyncClient(timeout=15.0) as http:
            r = await http.get(f"{self.API}/sites/{site_id}/env", headers=self._h())
            r.raise_for_status()
            return [{"key": k, "values": v} for k, v in r.json().items()]


class CloudflareConnection:
    """Cloudflare via API Token."""

    API = "https://api.cloudflare.com/client/v4"

    def _token(self) -> Optional[str]:
        from apps.core.config import settings
        return getattr(settings, "CLOUDFLARE_API_TOKEN", None)

    def _account_id(self) -> Optional[str]:
        from apps.core.config import settings
        return getattr(settings, "CLOUDFLARE_ACCOUNT_ID", None)

    def _h(self) -> dict:
        tok = self._token() or ""
        return {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}

    async def list_zones(self) -> list[dict]:
        token = self._token()
        if not token:
            return [{"error": "CLOUDFLARE_API_TOKEN no configurado"}]
        async with httpx.AsyncClient(timeout=15.0) as http:
            r = await http.get(f"{self.API}/zones", headers=self._h())
            r.raise_for_status()
            return [
                {
                    "id": z.get("id"),
                    "name": z.get("name"),
                    "status": z.get("status"),
                    "type": z.get("type"),
                    "nameservers": z.get("name_servers", []),
                }
                for z in r.json().get("result", [])
            ]

    async def get_analytics(self, zone_id: str, since: str = "-10080") -> dict:
        token = self._token()
        if not token:
            return {"error": "CLOUDFLARE_API_TOKEN no configurado"}
        async with httpx.AsyncClient(timeout=15.0) as http:
            r = await http.get(
                f"{self.API}/zones/{zone_id}/analytics/dashboard",
                headers=self._h(),
                params={"since": since, "until": "0"},
            )
            r.raise_for_status()
            return r.json().get("result", {}).get("totals", {})

    async def list_dns_records(self, zone_id: str) -> list[dict]:
        token = self._token()
        if not token:
            return [{"error": "CLOUDFLARE_API_TOKEN no configurado"}]
        async with httpx.AsyncClient(timeout=15.0) as http:
            r = await http.get(f"{self.API}/zones/{zone_id}/dns_records", headers=self._h())
            r.raise_for_status()
            return [
                {"id": rec.get("id"), "type": rec.get("type"), "name": rec.get("name"), "content": rec.get("content")}
                for rec in r.json().get("result", [])
            ]

    async def purge_cache(self, zone_id: str, files: list[str] = []) -> dict:
        token = self._token()
        if not token:
            return {"error": "CLOUDFLARE_API_TOKEN no configurado"}
        payload = {"files": files} if files else {"purge_everything": True}
        async with httpx.AsyncClient(timeout=15.0) as http:
            r = await http.post(
                f"{self.API}/zones/{zone_id}/purge_cache",
                headers=self._h(),
                json=payload,
            )
            return {"success": r.json().get("success"), "id": r.json().get("result", {}).get("id")}


class FirebaseConnection:
    """Firebase via Google Service Account / OAuth token."""

    def _project_id(self) -> Optional[str]:
        from apps.core.config import settings
        return getattr(settings, "FIREBASE_PROJECT_ID", None)

    def _token(self) -> Optional[str]:
        from apps.core.config import settings
        return getattr(settings, "FIREBASE_SERVICE_ACCOUNT_TOKEN", None)

    def _h(self) -> dict:
        token = self._token() or ""
        return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

    async def list_collections(self, document_path: str = "") -> list[str]:
        project_id = self._project_id()
        token = self._token()
        if not project_id or not token:
            return ["FIREBASE_PROJECT_ID / FIREBASE_SERVICE_ACCOUNT_TOKEN no configurados"]
        base = f"https://firestore.googleapis.com/v1/projects/{project_id}/databases/(default)/documents"
        path = f"{base}/{document_path}:listCollectionIds" if document_path else f"{base}:listCollectionIds"
        async with httpx.AsyncClient(timeout=15.0) as http:
            r = await http.post(path, headers=self._h(), json={})
            r.raise_for_status()
            return r.json().get("collectionIds", [])

    async def get_document(self, collection: str, doc_id: str) -> dict:
        project_id = self._project_id()
        token = self._token()
        if not project_id or not token:
            return {"error": "FIREBASE_PROJECT_ID / FIREBASE_SERVICE_ACCOUNT_TOKEN no configurados"}
        url = f"https://firestore.googleapis.com/v1/projects/{project_id}/databases/(default)/documents/{collection}/{doc_id}"
        async with httpx.AsyncClient(timeout=15.0) as http:
            r = await http.get(url, headers=self._h())
            r.raise_for_status()
            return r.json()

    async def list_documents(self, collection: str, limit: int = 20) -> list[dict]:
        project_id = self._project_id()
        token = self._token()
        if not project_id or not token:
            return [{"error": "FIREBASE_PROJECT_ID / FIREBASE_SERVICE_ACCOUNT_TOKEN no configurados"}]
        url = f"https://firestore.googleapis.com/v1/projects/{project_id}/databases/(default)/documents/{collection}"
        async with httpx.AsyncClient(timeout=15.0) as http:
            r = await http.get(url, headers=self._h(), params={"pageSize": limit})
            r.raise_for_status()
            return r.json().get("documents", [])


class AWSS3Connection:
    """AWS S3 via Access Key + Secret — list buckets and objects."""

    def _creds(self) -> tuple[str, str, str]:
        from apps.core.config import settings
        key = getattr(settings, "AWS_ACCESS_KEY_ID", "") or ""
        secret = getattr(settings, "AWS_SECRET_ACCESS_KEY", "") or ""
        region = getattr(settings, "AWS_REGION", "us-east-1") or "us-east-1"
        return key, secret, region

    async def list_buckets(self) -> list[dict]:
        """Lists S3 buckets using AWS SDK-style signed request."""
        key, secret, region = self._creds()
        if not key or not secret:
            return [{"error": "AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY no configurados"}]
        import hmac
        import hashlib
        import datetime
        now = datetime.datetime.utcnow()
        date_str = now.strftime("%Y%m%d")
        time_str = now.strftime("%Y%m%dT%H%M%SZ")
        host = "s3.amazonaws.com"
        headers_str = f"host:{host}\nx-amz-date:{time_str}\n"
        signed_headers = "host;x-amz-date"
        canonical = f"GET\n/\n\n{headers_str}\n{signed_headers}\ne3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
        str_to_sign = f"AWS4-HMAC-SHA256\n{time_str}\n{date_str}/{region}/s3/aws4_request\n{hashlib.sha256(canonical.encode()).hexdigest()}"
        def sign(key_bytes: bytes, msg: str) -> bytes:
            return hmac.new(key_bytes, msg.encode(), hashlib.sha256).digest()
        signing_key = sign(sign(sign(sign(f"AWS4{secret}".encode(), date_str), region), "s3"), "aws4_request")
        signature = hmac.new(signing_key, str_to_sign.encode(), hashlib.sha256).hexdigest()
        auth = f"AWS4-HMAC-SHA256 Credential={key}/{date_str}/{region}/s3/aws4_request, SignedHeaders={signed_headers}, Signature={signature}"
        try:
            async with httpx.AsyncClient(timeout=15.0) as http:
                r = await http.get(
                    f"https://{host}/",
                    headers={"Authorization": auth, "x-amz-date": time_str, "host": host},
                )
                r.raise_for_status()
                import xml.etree.ElementTree as ET
                root = ET.fromstring(r.text)
                ns = {"s3": "http://s3.amazonaws.com/doc/2006-03-01/"}
                return [
                    {"name": b.findtext("s3:Name", namespaces=ns), "created": b.findtext("s3:CreationDate", namespaces=ns)}
                    for b in root.findall("s3:Buckets/s3:Bucket", namespaces=ns)
                ]
        except Exception as exc:
            logger.warning("[AWS S3] list_buckets error: %s", exc)
            return [{"error": str(exc)}]

    async def list_objects(self, bucket: str, prefix: str = "", max_keys: int = 50) -> list[dict]:
        key, secret, region = self._creds()
        if not key or not secret:
            return [{"error": "AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY no configurados"}]
        try:
            import boto3
            s3 = boto3.client("s3", aws_access_key_id=key, aws_secret_access_key=secret, region_name=region)
            params: dict[str, Any] = {"Bucket": bucket, "MaxKeys": max_keys}
            if prefix:
                params["Prefix"] = prefix
            response = s3.list_objects_v2(**params)
            return [
                {"key": o.get("Key"), "size": o.get("Size"), "modified": str(o.get("LastModified"))}
                for o in response.get("Contents", [])
            ]
        except ImportError:
            return [{"error": "boto3 no instalado — pip install boto3"}]
        except Exception as exc:
            return [{"error": str(exc)}]
