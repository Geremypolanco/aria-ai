"""
secrets_manager.py — Gestor de Secretos y Configuración de Entornos para ARIA.

Proporciona:
- Almacenamiento seguro de credenciales y API keys
- Gestión de variables de entorno
- Encriptación y descifrado de secretos
- Auditoría de acceso a secretos
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
    """Gestor centralizado de secretos y configuración."""

    def __init__(self, secrets_dir: str = ".aria/secrets"):
        self.secrets_dir = Path(secrets_dir)
        self.secrets_dir.mkdir(parents=True, exist_ok=True)

        # Generar o cargar clave de encriptación
        self.key_file = self.secrets_dir / ".key"
        self.cipher = self._load_or_create_cipher()

        # Almacén en memoria (caché)
        self._secrets_cache: dict[str, str] = {}
        self._access_log: list = []

        # Cargar secretos existentes
        self._load_secrets()

    def _load_or_create_cipher(self) -> Fernet:
        """Carga o crea una clave de encriptación Fernet."""
        if self.key_file.exists():
            key = self.key_file.read_bytes()
        else:
            key = Fernet.generate_key()
            self.key_file.write_bytes(key)
            self.key_file.chmod(0o600)  # Solo lectura para el propietario
            logger.info("[Secrets] Clave de encriptación generada")

        return Fernet(key)

    def _load_secrets(self):
        """Carga secretos del almacenamiento persistente."""
        secrets_file = self.secrets_dir / "secrets.enc"
        if secrets_file.exists():
            try:
                encrypted_data = secrets_file.read_bytes()
                decrypted_data = self.cipher.decrypt(encrypted_data)
                self._secrets_cache = json.loads(decrypted_data.decode())
                logger.info(f"[Secrets] Cargados {len(self._secrets_cache)} secretos")
            except Exception as exc:
                logger.error(f"[Secrets] Error cargando secretos: {exc}")

    def _save_secrets(self):
        """Guarda secretos en almacenamiento persistente encriptado."""
        try:
            secrets_file = self.secrets_dir / "secrets.enc"
            json_data = json.dumps(self._secrets_cache)
            encrypted_data = self.cipher.encrypt(json_data.encode())
            secrets_file.write_bytes(encrypted_data)
            secrets_file.chmod(0o600)
            logger.debug("[Secrets] Secretos guardados")
        except Exception as exc:
            logger.error(f"[Secrets] Error guardando secretos: {exc}")

    def set_secret(self, key: str, value: str, tags: list = None) -> bool:
        """Establece un secreto."""
        try:
            self._secrets_cache[key] = value
            self._save_secrets()

            # Registrar en auditoría
            self._log_access("set", key, tags or [])

            logger.info(f"[Secrets] Secreto establecido: {key}")
            return True
        except Exception as exc:
            logger.error(f"[Secrets] Error estableciendo secreto: {exc}")
            return False

    def get_secret(self, key: str) -> str | None:
        """Obtiene un secreto."""
        try:
            value = self._secrets_cache.get(key)
            if value:
                self._log_access("get", key)
                logger.debug(f"[Secrets] Secreto obtenido: {key}")
                return value
            logger.warning(f"[Secrets] Secreto no encontrado: {key}")
            return None
        except Exception as exc:
            logger.error(f"[Secrets] Error obteniendo secreto: {exc}")
            return None

    def delete_secret(self, key: str) -> bool:
        """Elimina un secreto."""
        try:
            if key in self._secrets_cache:
                del self._secrets_cache[key]
                self._save_secrets()
                self._log_access("delete", key)
                logger.info(f"[Secrets] Secreto eliminado: {key}")
                return True
            logger.warning(f"[Secrets] Secreto no encontrado para eliminar: {key}")
            return False
        except Exception as exc:
            logger.error(f"[Secrets] Error eliminando secreto: {exc}")
            return False

    def list_secrets(self, pattern: str = None) -> dict[str, str]:
        """Lista secretos (sin mostrar valores)."""
        secrets = {}
        for key in self._secrets_cache:
            if pattern is None or pattern.lower() in key.lower():
                secrets[key] = "***"  # Enmascarar valores
        return secrets

    def _log_access(self, action: str, key: str, tags: list = None):
        """Registra acceso a secretos para auditoría."""
        self._access_log.append(
            {
                "timestamp": datetime.now(UTC).isoformat(),
                "action": action,
                "key": key,
                "tags": tags or [],
            }
        )

    def get_audit_log(self) -> list:
        """Obtiene el registro de auditoría."""
        return self._access_log


class EnvironmentManager:
    """Gestor de variables de entorno y configuración."""

    def __init__(self, config_dir: str = ".aria/config"):
        self.config_dir = Path(config_dir)
        self.config_dir.mkdir(parents=True, exist_ok=True)
        self.environments: dict[str, dict[str, str]] = {}
        self.current_environment = "default"
        self._load_environments()

    def _load_environments(self):
        """Carga configuraciones de entorno desde archivos."""
        for env_file in self.config_dir.glob("*.env"):
            env_name = env_file.stem
            self.environments[env_name] = self._parse_env_file(env_file)
            logger.info(f"[Env] Entorno cargado: {env_name}")

    def _parse_env_file(self, file_path: Path) -> dict[str, str]:
        """Parsea un archivo .env."""
        env_vars = {}
        try:
            with open(file_path) as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#") and "=" in line:
                        key, value = line.split("=", 1)
                        env_vars[key.strip()] = value.strip()
        except Exception as exc:
            logger.error(f"[Env] Error parseando {file_path}: {exc}")
        return env_vars

    def create_environment(self, name: str, variables: dict[str, str]) -> bool:
        """Crea un nuevo entorno."""
        try:
            self.environments[name] = variables
            self._save_environment(name)
            logger.info(f"[Env] Entorno creado: {name}")
            return True
        except Exception as exc:
            logger.error(f"[Env] Error creando entorno: {exc}")
            return False

    def _save_environment(self, name: str):
        """Guarda un entorno en archivo."""
        try:
            env_file = self.config_dir / f"{name}.env"
            with open(env_file, "w") as f:
                for key, value in self.environments[name].items():
                    f.write(f"{key}={value}\n")
            env_file.chmod(0o600)
        except Exception as exc:
            logger.error(f"[Env] Error guardando entorno: {exc}")

    def set_environment(self, name: str) -> bool:
        """Establece el entorno actual."""
        if name in self.environments:
            self.current_environment = name
            logger.info(f"[Env] Entorno establecido: {name}")
            return True
        logger.warning(f"[Env] Entorno no encontrado: {name}")
        return False

    def get_variable(self, key: str, default: str = None) -> str | None:
        """Obtiene una variable del entorno actual."""
        env_vars = self.environments.get(self.current_environment, {})
        return env_vars.get(key, default)

    def set_variable(self, key: str, value: str, environment: str = None) -> bool:
        """Establece una variable en un entorno."""
        env_name = environment or self.current_environment
        if env_name not in self.environments:
            self.environments[env_name] = {}

        self.environments[env_name][key] = value
        self._save_environment(env_name)
        logger.info(f"[Env] Variable establecida: {key} en {env_name}")
        return True

    def get_environment_variables(self, environment: str = None) -> dict[str, str]:
        """Obtiene todas las variables de un entorno."""
        env_name = environment or self.current_environment
        return self.environments.get(env_name, {})

    def list_environments(self) -> list:
        """Lista todos los entornos disponibles."""
        return list(self.environments.keys())


class ConfigurationManager:
    """Gestor centralizado de configuración."""

    def __init__(self):
        self.secrets = SecretsManager()
        self.env = EnvironmentManager()
        self.config_cache: dict[str, Any] = {}

    def load_config_file(self, file_path: str) -> dict[str, Any]:
        """Carga un archivo de configuración JSON."""
        try:
            with open(file_path) as f:
                config = json.load(f)
            self.config_cache.update(config)
            logger.info(f"[Config] Configuración cargada desde {file_path}")
            return config
        except Exception as exc:
            logger.error(f"[Config] Error cargando configuración: {exc}")
            return {}

    def get_config(self, key: str, default: Any = None) -> Any:
        """Obtiene un valor de configuración."""
        return self.config_cache.get(key, default)

    def set_config(self, key: str, value: Any) -> None:
        """Establece un valor de configuración."""
        self.config_cache[key] = value


# Instancias globales
secrets_manager = SecretsManager()
env_manager = EnvironmentManager()
config_manager = ConfigurationManager()
