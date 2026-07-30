"""Settings for the Lingua language-learning app — fully independent from apps/core.

Reads from the environment (or a local .env in language-app/) so this app can be
deployed and run without any dependency on ARIA's own settings module.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

_BASE_DIR = Path(__file__).resolve().parent.parent


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

    @property
    def hf_configured(self) -> bool:
        return bool(self.hf_token)


settings = Settings()
