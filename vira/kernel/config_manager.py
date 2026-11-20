"""Centralized configuration management"""
import os
import re
import yaml
import copy
from loguru import logger
from pathlib import Path
from typing import Dict, Any, Optional

from vira.secrets import decrypt_text, encrypt_text

_SENSITIVE_KEY = re.compile(r'(api_key|secret|secret_key|password|token|private_key)$', re.IGNORECASE)

# logger = logging.getLogger(__name__)


class ConfigManager:
    """Manages configuration with YAML and environment overrides"""

    def __init__(self, config_path: Optional[str] = None):
        self._config: Dict[str, Any] = {}
        self._config_path = config_path

    async def initialize(self, config_path: Optional[str] = None):
        """Load configuration from file"""
        path = config_path or self._config_path or "config.yaml"
        config_file = Path(path)

        if config_file.exists():
            with open(config_file, "r") as f:
                self._config = yaml.safe_load(f) or {}
            logger.info(f"Loaded config from {config_file}")
        else:
            logger.warning(f"Config file not found: {config_file}, using defaults")
            self._config = {}

        self._apply_env_overrides()
        return self

    def _apply_env_overrides(self):
        """Override config with environment variables (VIRA_* pattern)"""
        for key, value in os.environ.items():
            if key.startswith("VIRA_"):
                config_key = key[5:].lower().replace("_", ".")
                self._set_nested_config(config_key, value)

    def _set_nested_config(self, key: str, value: str):
        """Set nested config value using dot notation"""
        parts = key.split(".")
        target = self._config
        for part in parts[:-1]:
            if part not in target:
                target[part] = {}
            target = target[part]
        target[parts[-1]] = value

    def get(self, key: str, default: Any = None) -> Any:
        """Get configuration value by dot-separated key (decrypting secrets)."""
        parts = key.split(".")
        target = self._config
        for part in parts:
            if isinstance(target, dict) and part in target:
                target = target[part]
            else:
                return default
        return self._decrypt_value(target)

    def set(self, key: str, value: Any) -> None:
        """Set configuration value"""
        parts = key.split(".")
        target = self._config
        for part in parts[:-1]:
            if part not in target:
                target[part] = {}
            target = target[part]
        target[parts[-1]] = value

    def get_all(self) -> Dict[str, Any]:
        """Get the full configuration with secret values decrypted for internal use."""
        return self._decrypt_tree(copy.deepcopy(self._config))

    def save(self, config: Dict[str, Any]) -> None:
        """Persist config, encrypting sensitive values at rest."""
        path = Path(self._config_path or "config.yaml")
        path.parent.mkdir(parents=True, exist_ok=True)
        persisted = self._encrypt_tree(copy.deepcopy(config))
        temporary_path = path.with_suffix(f"{path.suffix}.tmp")
        with temporary_path.open("w", encoding="utf-8") as config_file:
            yaml.safe_dump(persisted, config_file, sort_keys=False, default_flow_style=False)
        temporary_path.replace(path)
        self._config = self._decrypt_tree(copy.deepcopy(persisted))
        logger.info("Saved config to {}", path)

    def _decrypt_value(self, value: Any) -> Any:
        if isinstance(value, str) and value.startswith("enc:v1:"):
            return decrypt_text(value)
        if isinstance(value, dict):
            return {key: self._decrypt_value(item) for key, item in value.items()}
        if isinstance(value, list):
            return [self._decrypt_value(item) for item in value]
        return value

    def _decrypt_tree(self, value: Any) -> Any:
        return self._decrypt_value(value)

    def _encrypt_tree(self, value: Any, key: str = "") -> Any:
        if isinstance(value, dict):
            return {item_key: self._encrypt_tree(item, item_key) for item_key, item in value.items()}
        if isinstance(value, list):
            return [self._encrypt_tree(item, key) for item in value]
        if isinstance(value, str) and _SENSITIVE_KEY.search(key) and value and not value.startswith("enc:v1:"):
            return encrypt_text(value)
        return value

    async def reload(self) -> None:
        """Reload configuration from file"""
        if self._config_path:
            await self.initialize(self._config_path)