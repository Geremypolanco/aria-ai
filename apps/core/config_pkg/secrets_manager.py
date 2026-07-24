"""
secrets_manager.py — Secrets and Environment Configuration Manager for ARIA.

Provides:
- Secure storage of credentials and API keys
- Environment variable management
- Secret encryption and decryption
- Secret access auditing
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from cryptography.fernet import Fernet

logger = logging.getLogger("aria.secrets")


class SecretsManager:
    """Centralized manager for secrets and configuration."""

    def __init__(self, secrets_dir: str = ".aria/secrets"):
        self.secrets_dir = Path(secrets_dir)
        self.secrets_dir.mkdir(parents=True, exist_ok=True)

        # Generate or load the encryption key
        self.key_file = self.secrets_dir / ".key"
        self.cipher = self._load_or_create_cipher()

        # In-memory store (cache)
        self._secrets_cache: dict[str, str] = {}
        self._access_log: list = []

        # Load existing secrets
        self._load_secrets()

    def _load_or_create_cipher(self) -> Fernet:
        """Loads or creates a Fernet encryption key.

        Precedence: ``ARIA_SECRETS_KEY`` env var, then the on-disk key file,
        else generate + persist a fresh one. The on-disk path is gitignored
        (``.aria/``) and must never be committed — a key that ever lands in
        version control must be treated as compromised, since anyone with
        repo/history access could then decrypt everything it protects.
        """
        import os as _os

        env_key = _os.environ.get("ARIA_SECRETS_KEY")
        if env_key:
            return Fernet(env_key.encode())

        if self.key_file.exists():
            key = self.key_file.read_bytes()
        else:
            key = Fernet.generate_key()
            self.key_file.write_bytes(key)
            self.key_file.chmod(0o600)  # Owner read-only
            logger.warning(
                "[Secrets] New encryption key generated at %s — back it up (or set "
                "ARIA_SECRETS_KEY) before relying on this for anything persistent; "
                "losing it makes any stored secrets unrecoverable.",
                self.key_file,
            )

        return Fernet(key)

    def _load_secrets(self):
        """Loads secrets from persistent storage."""
        secrets_file = self.secrets_dir / "secrets.enc"
        if secrets_file.exists():
            try:
                encrypted_data = secrets_file.read_bytes()
                decrypted_data = self.cipher.decrypt(encrypted_data)
                self._secrets_cache = json.loads(decrypted_data.decode())
                logger.info(f"[Secrets] Loaded {len(self._secrets_cache)} secrets")
            except Exception as exc:
                logger.error(f"[Secrets] Error loading secrets: {exc}")

    def _save_secrets(self):
        """Saves secrets to encrypted persistent storage."""
        try:
            secrets_file = self.secrets_dir / "secrets.enc"
            json_data = json.dumps(self._secrets_cache)
            encrypted_data = self.cipher.encrypt(json_data.encode())
            secrets_file.write_bytes(encrypted_data)
            secrets_file.chmod(0o600)
            logger.debug("[Secrets] Secrets saved")
        except Exception as exc:
            logger.error(f"[Secrets] Error saving secrets: {exc}")

    def set_secret(self, key: str, value: str, tags: list = None) -> bool:
        """Sets a secret."""
        try:
            self._secrets_cache[key] = value
            self._save_secrets()

            # Log to audit trail
            self._log_access("set", key, tags or [])

            logger.info(f"[Secrets] Secret set: {key}")
            return True
        except Exception as exc:
            logger.error(f"[Secrets] Error setting secret: {exc}")
            return False

    def get_secret(self, key: str) -> str | None:
        """Retrieves a secret."""
        try:
            value = self._secrets_cache.get(key)
            if value:
                self._log_access("get", key)
                logger.debug(f"[Secrets] Secret retrieved: {key}")
                return value
            logger.warning(f"[Secrets] Secret not found: {key}")
            return None
        except Exception as exc:
            logger.error(f"[Secrets] Error retrieving secret: {exc}")
            return None

    def delete_secret(self, key: str) -> bool:
        """Deletes a secret."""
        try:
            if key in self._secrets_cache:
                del self._secrets_cache[key]
                self._save_secrets()
                self._log_access("delete", key)
                logger.info(f"[Secrets] Secret deleted: {key}")
                return True
            logger.warning(f"[Secrets] Secret not found to delete: {key}")
            return False
        except Exception as exc:
            logger.error(f"[Secrets] Error deleting secret: {exc}")
            return False

    def list_secrets(self, pattern: str = None) -> dict[str, str]:
        """Lists secrets (without showing values)."""
        secrets = {}
        for key in self._secrets_cache:
            if pattern is None or pattern.lower() in key.lower():
                secrets[key] = "***"  # Mask values
        return secrets

    def _log_access(self, action: str, key: str, tags: list = None):
        """Logs secret access for auditing."""
        self._access_log.append(
            {
                "timestamp": datetime.now(UTC).isoformat(),
                "action": action,
                "key": key,
                "tags": tags or [],
            }
        )

    def get_audit_log(self) -> list:
        """Retrieves the audit log."""
        return self._access_log


class EnvironmentManager:
    """Manager for environment variables and configuration."""

    def __init__(self, config_dir: str = ".aria/config"):
        self.config_dir = Path(config_dir)
        self.config_dir.mkdir(parents=True, exist_ok=True)
        self.environments: dict[str, dict[str, str]] = {}
        self.current_environment = "default"
        self._load_environments()

    def _load_environments(self):
        """Loads environment configurations from files."""
        for env_file in self.config_dir.glob("*.env"):
            env_name = env_file.stem
            self.environments[env_name] = self._parse_env_file(env_file)
            logger.info(f"[Env] Environment loaded: {env_name}")

    def _parse_env_file(self, file_path: Path) -> dict[str, str]:
        """Parses a .env file."""
        env_vars = {}
        try:
            with open(file_path) as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#") and "=" in line:
                        key, value = line.split("=", 1)
                        env_vars[key.strip()] = value.strip()
        except Exception as exc:
            logger.error(f"[Env] Error parsing {file_path}: {exc}")
        return env_vars

    def create_environment(self, name: str, variables: dict[str, str]) -> bool:
        """Creates a new environment."""
        try:
            self.environments[name] = variables
            self._save_environment(name)
            logger.info(f"[Env] Environment created: {name}")
            return True
        except Exception as exc:
            logger.error(f"[Env] Error creating environment: {exc}")
            return False

    def _save_environment(self, name: str):
        """Saves an environment to a file."""
        try:
            env_file = self.config_dir / f"{name}.env"
            with open(env_file, "w") as f:
                for key, value in self.environments[name].items():
                    f.write(f"{key}={value}\n")
            env_file.chmod(0o600)
        except Exception as exc:
            logger.error(f"[Env] Error saving environment: {exc}")

    def set_environment(self, name: str) -> bool:
        """Sets the current environment."""
        if name in self.environments:
            self.current_environment = name
            logger.info(f"[Env] Environment set: {name}")
            return True
        logger.warning(f"[Env] Environment not found: {name}")
        return False

    def get_variable(self, key: str, default: str = None) -> str | None:
        """Retrieves a variable from the current environment."""
        env_vars = self.environments.get(self.current_environment, {})
        return env_vars.get(key, default)

    def set_variable(self, key: str, value: str, environment: str = None) -> bool:
        """Sets a variable in an environment."""
        env_name = environment or self.current_environment
        if env_name not in self.environments:
            self.environments[env_name] = {}

        self.environments[env_name][key] = value
        self._save_environment(env_name)
        logger.info(f"[Env] Variable set: {key} in {env_name}")
        return True

    def get_environment_variables(self, environment: str = None) -> dict[str, str]:
        """Retrieves all variables from an environment."""
        env_name = environment or self.current_environment
        return self.environments.get(env_name, {})

    def list_environments(self) -> list:
        """Lists all available environments."""
        return list(self.environments.keys())


class ConfigurationManager:
    """Centralized configuration manager."""

    def __init__(self):
        self.secrets = SecretsManager()
        self.env = EnvironmentManager()
        self.config_cache: dict[str, Any] = {}

    def load_config_file(self, file_path: str) -> dict[str, Any]:
        """Loads a JSON configuration file."""
        try:
            with open(file_path) as f:
                config = json.load(f)
            self.config_cache.update(config)
            logger.info(f"[Config] Configuration loaded from {file_path}")
            return config
        except Exception as exc:
            logger.error(f"[Config] Error loading configuration: {exc}")
            return {}

    def get_config(self, key: str, default: Any = None) -> Any:
        """Retrieves a configuration value."""
        return self.config_cache.get(key, default)

    def set_config(self, key: str, value: Any) -> None:
        """Sets a configuration value."""
        self.config_cache[key] = value


# Global instances
secrets_manager = SecretsManager()
env_manager = EnvironmentManager()
config_manager = ConfigurationManager()
