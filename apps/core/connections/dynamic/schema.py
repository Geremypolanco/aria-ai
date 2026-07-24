"""
The JSON Schema for a connector spec — the data shape that replaces writing a
Python class per API. One ConnectorSpec (one JSON file under specs/) fully
describes how to authenticate against and call a given service.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class AuthSpec(BaseModel):
    """How this connector authenticates. `oauth2` reuses the token already
    stored by the existing OAuth system (apps.core.connectors.oauth_hub) —
    the dynamic engine is a second consumer of that one token store, not a
    third place tokens live."""

    type: Literal["oauth2", "api_key", "basic", "none"] = "none"

    # oauth2 — `service_id` is the provider id under which oauth_hub already
    # stores the token (defaults to the connector's own id).
    service_id: str | None = None

    # api_key
    in_: Literal["header", "query"] = Field("header", alias="in")
    header_name: str = "Authorization"
    query_param: str = "api_key"
    value_prefix: str = ""
    # Name of the attribute on apps.core.config.settings holding the secret
    # (e.g. "STRIPE_SECRET_KEY"). Never the secret value itself.
    settings_key: str | None = None

    # basic — real HTTP Basic Auth (base64("user:pass")), two separate secrets.
    username_settings_key: str | None = None
    password_settings_key: str | None = None

    model_config = {"populate_by_name": True}


class RetrySpec(BaseModel):
    """Exponential backoff policy, applied only to the status codes/errors
    that are actually safe to retry (rate limits, transient 5xx, network
    errors) — never to 4xx client errors like bad auth or bad payload."""

    max_attempts: int = 4
    base_delay_seconds: float = 0.5
    max_delay_seconds: float = 8.0
    retry_on_status: list[int] = Field(default_factory=lambda: [429, 500, 502, 503, 504])


class EndpointSpec(BaseModel):
    """One callable operation on the connector (e.g. "list_contacts")."""

    method: Literal["GET", "POST", "PUT", "PATCH", "DELETE"]
    # May contain {placeholders} — resolved from the caller's variables at
    # call time. Missing placeholders fail fast, before any network call.
    path: str
    # Which of the caller's variables become query-string params / JSON body
    # fields. Everything else is assumed to be a path placeholder.
    query_params: list[str] = Field(default_factory=list)
    body_params: list[str] = Field(default_factory=list)
    # Most APIs take a JSON body; some (Stripe's legacy endpoints) expect
    # application/x-www-form-urlencoded — this is the one non-uniform detail
    # per-endpoint enough to earn a field instead of an assumption.
    body_encoding: Literal["json", "form"] = "json"
    # Optional dotted path to unwrap in the response, e.g. "data.items".
    response_path: str | None = None
    timeout_seconds: float = 20.0


class ConnectorSpec(BaseModel):
    id: str
    name: str
    category: str = "other"
    # May itself contain {placeholders} resolved from the stored OAuth token
    # (e.g. Salesforce's per-org "{instance_url}/services/data/v59.0").
    base_url: str
    auth: AuthSpec = AuthSpec()
    default_headers: dict[str, str] = Field(default_factory=dict)
    retry: RetrySpec = RetrySpec()
    endpoints: dict[str, EndpointSpec]
