"""
DynamicConnectorEngine — a data-driven SDK. Instead of writing a Python class
per API, each of the 300 target connectors is a JSON file under specs/
(base_url, auth, endpoints). This module is the only code that ever runs;
adding connector #300 means dropping a new JSON file in specs/, nothing here
changes.

    engine = get_engine("hubspot")
    contacts = await engine.call("list_contacts", email=user_email, limit=10)

Handles, uniformly for every connector: auth injection (OAuth2 bearer reusing
the existing token store, API key, or Basic), exponential-backoff retries on
transient failures only, and a small typed error hierarchy so callers can
tell "not connected yet" apart from "the API rejected the request" apart from
"the API is having an outage".
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

import httpx
from tenacity import AsyncRetrying, retry_if_exception_type, stop_after_attempt, wait_exponential

from apps.core.connections.dynamic.schema import ConnectorSpec, EndpointSpec

logger = logging.getLogger("aria.connections.dynamic")

SPECS_DIR = Path(__file__).parent / "specs"


# ── errors ──────────────────────────────────────────────────────────────
class ConnectorError(Exception):
    """Base error for the dynamic engine."""


class ConnectorConfigError(ConnectorError):
    """The spec or the call itself is wrong: unknown endpoint, missing a
    required path variable, unknown auth type. Never caused by the remote
    API — fails before any network call."""


class ConnectorAuthError(ConnectorError):
    """No usable credentials: OAuth token not connected yet, or a required
    API key setting is unset."""


class ConnectorHTTPError(ConnectorError):
    """The remote API returned a non-retryable error (a 4xx, or a 5xx/429
    that exhausted all retry attempts)."""

    def __init__(self, status_code: int, body: str):
        self.status_code = status_code
        self.body = body
        super().__init__(f"HTTP {status_code}: {body[:300]}")


class _RetryableHTTPError(Exception):
    """Internal signal: this status code is in the spec's retry_on_status."""

    def __init__(self, status_code: int, body: str):
        self.status_code = status_code
        self.body = body
        super().__init__(f"HTTP {status_code} (retryable): {body[:200]}")


# ── spec loading (auto-discovery — the "no core changes" mechanism) ──────
def load_spec(path: Path) -> ConnectorSpec:
    return ConnectorSpec.model_validate(json.loads(path.read_text()))


def load_all_specs(directory: Path = SPECS_DIR) -> dict[str, ConnectorSpec]:
    """Every *.json file under `directory` becomes an available connector.
    A malformed file is skipped (logged), not fatal to the other 299."""
    specs: dict[str, ConnectorSpec] = {}
    for f in sorted(directory.glob("*.json")):
        try:
            spec = load_spec(f)
        except Exception as exc:  # noqa: BLE001
            logger.warning("[dynamic-connectors] failed to load %s: %s", f.name, exc)
            continue
        if spec.id in specs:
            logger.warning("[dynamic-connectors] duplicate id '%s' in %s", spec.id, f.name)
        specs[spec.id] = spec
    return specs


_SPECS_CACHE: dict[str, ConnectorSpec] | None = None


def _specs() -> dict[str, ConnectorSpec]:
    global _SPECS_CACHE
    if _SPECS_CACHE is None:
        _SPECS_CACHE = load_all_specs()
    return _SPECS_CACHE


def available_connectors() -> list[str]:
    return sorted(_specs())


def get_engine(connector_id: str, transport: httpx.BaseTransport | None = None) -> DynamicConnectorEngine:
    spec = _specs().get(connector_id)
    if spec is None:
        raise ConnectorConfigError(
            f"No spec registered for '{connector_id}' (available: {available_connectors()})"
        )
    return DynamicConnectorEngine(spec, transport=transport)


def _dig(obj, dotted_path: str):
    cur = obj
    for part in dotted_path.split("."):
        if not isinstance(cur, dict):
            return None
        cur = cur.get(part)
    return cur


# ── the engine ─────────────────────────────────────────────────────────
class DynamicConnectorEngine:
    """Executes one named endpoint of a ConnectorSpec against the real API."""

    def __init__(self, spec: ConnectorSpec, transport: httpx.BaseTransport | None = None):
        self.spec = spec
        # `transport` is a test seam (httpx.MockTransport) — production
        # leaves it None and httpx picks its normal transport.
        self._transport = transport

    async def call(
        self,
        endpoint_name: str,
        *,
        email: str = "",
        token: dict | None = None,
        **variables,
    ) -> dict | list | None:
        """Execute `endpoint_name`. `variables` supplies path placeholders
        plus whatever the endpoint's `query_params`/`body_params` declare.

        `email` looks up a stored OAuth token for `oauth2`-auth connectors;
        pass `token` directly to skip that lookup (e.g. tests, or a token
        already fetched by the caller).
        """
        ep = self.spec.endpoints.get(endpoint_name)
        if ep is None:
            raise ConnectorConfigError(
                f"'{self.spec.id}' has no endpoint '{endpoint_name}' "
                f"(available: {sorted(self.spec.endpoints)})"
            )

        # Resolve the path first — a malformed call (missing path variable)
        # should fail before we ever try to authenticate or touch the network.
        try:
            path = ep.path.format(**variables)
        except KeyError as exc:
            raise ConnectorConfigError(
                f"'{self.spec.id}.{endpoint_name}' needs variable {exc} — got {sorted(variables)}"
            ) from exc

        headers = dict(self.spec.default_headers)
        query: dict = {}
        resolved_token = await self._resolve_auth(email, headers, query, token)

        try:
            base_url = self.spec.base_url.format(**{**resolved_token, **variables})
        except KeyError as exc:
            raise ConnectorConfigError(
                f"'{self.spec.id}' base_url needs {exc}, not present in the token or variables"
            ) from exc

        declared_query = {name: variables[name] for name in ep.query_params if name in variables}
        auth_query_param = (
            self.spec.auth.query_param
            if (self.spec.auth.type == "api_key" and self.spec.auth.in_ == "query")
            else None
        )
        if auth_query_param and auth_query_param in declared_query:
            raise ConnectorConfigError(
                f"'{self.spec.id}.{endpoint_name}': '{auth_query_param}' is reserved for "
                "auth and cannot be passed as a call variable"
            )
        query.update(declared_query)
        body = {name: variables[name] for name in ep.body_params if name in variables}

        url = base_url.rstrip("/") + path
        return await self._execute_with_retry(ep, url, headers, query, body)

    async def _resolve_auth(
        self, email: str, headers: dict, query: dict, token_hint: dict | None
    ) -> dict:
        """Injects credentials into headers/query. Returns the token dict
        (used for base_url templating, e.g. Salesforce's instance_url)."""
        auth = self.spec.auth

        if auth.type == "none":
            return token_hint or {}

        if auth.type == "oauth2":
            token = token_hint
            if token is None:
                from apps.core.connectors import oauth_hub

                token = await oauth_hub.get_token(email, auth.service_id or self.spec.id)
            if not token or not token.get("access_token"):
                raise ConnectorAuthError(
                    f"'{self.spec.id}' isn't connected for {email or '(no email)'} — "
                    "no stored OAuth token."
                )
            headers["Authorization"] = f"Bearer {token['access_token']}"
            return token

        if auth.type == "api_key":
            from apps.core.config import settings

            value = getattr(settings, auth.settings_key, None) if auth.settings_key else None
            if not value:
                raise ConnectorAuthError(
                    f"'{self.spec.id}' requires {auth.settings_key} to be configured."
                )
            if auth.in_ == "query":
                query[auth.query_param] = value
            else:
                headers[auth.header_name] = f"{auth.value_prefix}{value}"
            return {}

        if auth.type == "basic":
            import base64

            from apps.core.config import settings

            user = getattr(settings, auth.username_settings_key, None) if auth.username_settings_key else None
            pwd = getattr(settings, auth.password_settings_key, None) if auth.password_settings_key else None
            if not user or not pwd:
                raise ConnectorAuthError(
                    f"'{self.spec.id}' requires {auth.username_settings_key}/"
                    f"{auth.password_settings_key} to be configured."
                )
            b64 = base64.b64encode(f"{user}:{pwd}".encode()).decode()
            headers["Authorization"] = f"Basic {b64}"
            return {}

        raise ConnectorConfigError(f"Unknown auth type '{auth.type}' for '{self.spec.id}'")

    async def _execute_with_retry(
        self, ep: EndpointSpec, url: str, headers: dict, query: dict, body: dict
    ):
        retry_cfg = self.spec.retry
        kwargs = {"data": body or None} if ep.body_encoding == "form" else {"json": body or None}
        try:
            # One client for every attempt — retries reuse the connection pool
            # instead of paying a fresh TCP/TLS handshake per attempt.
            async with httpx.AsyncClient(
                timeout=ep.timeout_seconds, transport=self._transport
            ) as client:
                async for attempt in AsyncRetrying(
                    stop=stop_after_attempt(retry_cfg.max_attempts),
                    wait=wait_exponential(
                        multiplier=retry_cfg.base_delay_seconds, max=retry_cfg.max_delay_seconds
                    ),
                    retry=retry_if_exception_type((_RetryableHTTPError, httpx.TransportError)),
                    reraise=True,
                ):
                    with attempt:
                        r = await client.request(
                            ep.method, url, headers=headers, params=query or None, **kwargs
                        )
                        if r.status_code in retry_cfg.retry_on_status:
                            raise _RetryableHTTPError(r.status_code, r.text)
                        if r.status_code >= 400:
                            raise ConnectorHTTPError(r.status_code, r.text)
                        try:
                            data = r.json() if r.content else None
                        except ValueError as exc:
                            raise ConnectorHTTPError(
                                r.status_code, f"non-JSON response: {r.text[:200]}"
                            ) from exc
                        if ep.response_path and data is not None:
                            return _dig(data, ep.response_path)
                        return data
        except _RetryableHTTPError as exc:
            raise ConnectorHTTPError(exc.status_code, exc.body) from exc
        except httpx.TransportError as exc:
            raise ConnectorError(
                f"'{self.spec.id}' network failure after {retry_cfg.max_attempts} attempts: {exc}"
            ) from exc
