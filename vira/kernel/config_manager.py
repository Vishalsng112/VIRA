"""Centralized configuration management"""
import os
import yaml
import copy
from loguru import logger
from pathlib import Path
from typing import Dict, Any, Optional

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
        """Get configuration value by dot-separated key"""
        parts = key.split(".")
        target = self._config
        for part in parts:
            if isinstance(target, dict) and part in target:
                target = target[part]
            else:
                return default
        return target

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
        """Get entire configuration"""
        return copy.deepcopy(self._config)

    def save(self, config: Dict[str, Any]) -> None:
        """Persist a complete configuration and make it the active configuration."""
        path = Path(self._config_path or "config.yaml")
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path = path.with_suffix(f"{path.suffix}.tmp")
        with temporary_path.open("w", encoding="utf-8") as config_file:
            yaml.safe_dump(config, config_file, sort_keys=False, default_flow_style=False)
        temporary_path.replace(path)
        self._config = copy.deepcopy(config)
        logger.info("Saved config to {}", path)

    async def reload(self) -> None:
        """Reload configuration from file"""
        if self._config_path:
            await self.initialize(self._config_path)