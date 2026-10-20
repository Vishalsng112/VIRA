# vira/kernel/plugin_manager.py
import importlib
from loguru import logger
from pathlib import Path
from typing import Dict, Any, List
from abc import ABC, abstractmethod

# logger = logging.getLogger(__name__)

class ViraPlugin(ABC):
    """Base interface for VIRA plugins (lightweight extensions)"""
    def __init__(self, name: str):
        self.name = name

    @abstractmethod
    async def start(self) -> None: pass

    @abstractmethod
    async def stop(self) -> None: pass

class PluginManager:
    def __init__(self, plugins_dir: str):
        self.plugins_dir = Path(plugins_dir)
        self._plugins: Dict[str, ViraPlugin] = {}

    async def load_plugins(self):
        if not self.plugins_dir.exists():
            logger.warning(f"Plugins directory not found: {self.plugins_dir}")
            return
        for pyfile in self.plugins_dir.glob("*.py"):
            if pyfile.name.startswith("_"):
                continue
            try:
                module_name = pyfile.stem
                spec = importlib.util.spec_from_file_location(module_name, pyfile)
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)
                for attr_name in dir(module):
                    attr = getattr(module, attr_name)
                    if isinstance(attr, type) and issubclass(attr, ViraPlugin) and attr != ViraPlugin:
                        instance = attr(attr.__name__)
                        await instance.start()
                        self._plugins[instance.name] = instance
                        logger.info(f"Loaded plugin: {instance.name}")
            except Exception as e:
                logger.error(f"Failed to load plugin {pyfile}: {e}")

    async def stop_all(self):
        for plugin in self._plugins.values():
            await plugin.stop()