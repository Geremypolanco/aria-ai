"""Settings for the Lingua language-learning app — fully independent from apps/core.

Reads from the environment (or a local .env in language-app/) so this app can be
deployed and run without any dependency on ARIA's own settings module.
"""

from __future__ import annotations

import os
import secrets
from dataclasses import dataclass, field
from pathlib import Path

_BASE_DIR = Path(__file__).resolve().parent.parent

# Generated once per process if LINGUA_SESSION_SECRET isn't set. Sessions won't
# survive a restart or work across multiple instances in that case — fine for
# local dev, not for a real multi-machine deploy (set the env var there).
_EPHEMERAL_SESSION_SECRET = secrets.token_hex(32)


def _load_dotenv() -> None:
    env_path = _BASE_DIR / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip())


_load_dotenv()


@dataclass(frozen=True)
class Settings:
    hf_token: str = field(default_factory=lambda: os.environ.get("HF_TOKEN", "") or os.environ.get("HF_API_KEY", ""))

    # Model choices — overridable via env, defaulting to models known to be served
    # on HF's free Inference Providers tier.
    chat_model: str = field(default_factory=lambda: os.environ.get("LINGUA_CHAT_MODEL", "Qwen/Qwen2.5-7B-Instruct"))
    image_model: str = field(
        default_factory=lambda: os.environ.get("LINGUA_IMAGE_MODEL", "black-forest-labs/FLUX.1-schnell")
    )
    stt_model: str = field(default_factory=lambda: os.environ.get("LINGUA_STT_MODEL", "openai/whisper-large-v3"))
    tts_model_prefix: str = field(
        default_factory=lambda: os.environ.get("LINGUA_TTS_MODEL_PREFIX", "facebook/mms-tts")
    )

    hf_chat_endpoint: str = "https://api-inference.huggingface.co/v1/chat/completions"
    hf_models_endpoint: str = "https://api-inference.huggingface.co/models"

    db_path: str = field(default_factory=lambda: os.environ.get("LINGUA_DB_PATH", str(_BASE_DIR / "data" / "lingua.db")))
    cache_dir: str = field(default_factory=lambda: os.environ.get("LINGUA_CACHE_DIR", str(_BASE_DIR / "data" / "media_cache")))

    host: str = field(default_factory=lambda: os.environ.get("LINGUA_HOST", "0.0.0.0"))
    port: int = field(default_factory=lambda: int(os.environ.get("LINGUA_PORT", "8100")))

    request_timeout_s: float = 60.0

    # ── Google Sign-In ───────────────────────────────────────────────────
    # A dedicated OAuth client for Lingua — deliberately not shared with
    # ARIA's own Google OAuth client/credentials. Register the redirect URI
    # printed by `python -m backend.main` (or see README.md) in this client.
    google_client_id: str = field(default_factory=lambda: os.environ.get("GOOGLE_CLIENT_ID", ""))
    google_client_secret: str = field(default_factory=lambda: os.environ.get("GOOGLE_CLIENT_SECRET", ""))

    # Public origin this app is served from — drives the OAuth redirect_uri.
    # Defaults to the Fly domain declared in fly.toml; override for local dev
    # (e.g. http://localhost:8100) or a custom domain.
    public_base_url: str = field(
        default_factory=lambda: os.environ.get(
            "LINGUA_PUBLIC_BASE_URL", f"http://localhost:{os.environ.get('LINGUA_PORT', '8100')}"
        ).rstrip("/")
    )

    session_secret: str = field(
        default_factory=lambda: os.environ.get("LINGUA_SESSION_SECRET", "") or _EPHEMERAL_SESSION_SECRET
    )

    # Lets you sign in locally/in tests without real Google credentials —
    # mirrors this app's "runs without HF_TOKEN too" demo-mode philosophy.
    # Auto-disabled the moment real Google credentials are configured, unless
    # explicitly re-enabled (a real deploy shouldn't ship an auth bypass by
    # accident).
    _dev_login_override: str = field(default_factory=lambda: os.environ.get("LINGUA_ALLOW_DEV_LOGIN", ""))

    @property
    def hf_configured(self) -> bool:
        return bool(self.hf_token)

    @property
    def google_configured(self) -> bool:
        return bool(self.google_client_id and self.google_client_secret)

    @property
    def cookie_secure(self) -> bool:
        return self.public_base_url.startswith("https://")

    @property
    def dev_login_enabled(self) -> bool:
        if self._dev_login_override:
            return self._dev_login_override == "1"
        return not self.google_configured


settings = Settings()
