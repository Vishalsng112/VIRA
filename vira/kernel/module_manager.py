"""Module lifecycle management"""
import importlib
import pkgutil
import sys
import time
import asyncio
from loguru import logger
from pathlib import Path
from typing import Dict, List, Optional, Any, Type
from abc import ABC, abstractmethod

# logger = logging.getLogger(__name__)


class ViraModule(ABC):
    """Base interface for VIRA modules"""

    def __init__(self, name: str):
        self.name = name
        self._running = False

    @abstractmethod
    async def initialize(self) -> None:
        """Initialize module resources"""
        pass

    @abstractmethod
    async def start(self) -> None:
        """Start module operations"""
        pass

    @abstractmethod
    async def stop(self) -> None:
        """Stop module operations"""
        pass

    async def health(self) -> Dict[str, Any]:
        """Return health status"""
        return {"name": self.name, "running": self._running, "status": "healthy" if self._running else "stopped"}


class ModuleManager:
    """Loads, unloads, monitors, and restarts modules"""

    def __init__(self, modules_dir: str):
        self.modules_dir = Path(modules_dir)
        self._modules: Dict[str, ViraModule] = {}
        self._monitor_task: Optional[asyncio.Task] = None
        self._running = False
        self.metrics_manager = None

    async def start(self):
        """Start module manager and monitor"""
        self._running = True
        self._monitor_task = asyncio.create_task(self._monitor_loop())
        logger.info("ModuleManager started")

    async def stop(self):
        """Stop all modules and monitor"""
        self._running = False
        if self._monitor_task:
            self._monitor_task.cancel()
            try:
                await self._monitor_task
            except asyncio.CancelledError:
                pass

        for module_name in list(self._modules.keys()):
            await self.unload_module(module_name)
        logger.info("ModuleManager stopped")

    async def load_module(self, module_path: str) -> bool:
        start = time.time()
        try:
            if module_path.startswith(".") or "/" in module_path:
                spec = importlib.util.spec_from_file_location(module_path, module_path)
                if spec and spec.loader:
                    module = importlib.util.module_from_spec(spec)
                    spec.loader.exec_module(module)
                else:
                    return False
            else:
                module = importlib.import_module(module_path)

            for attr_name in dir(module):
                attr = getattr(module, attr_name)
                if isinstance(attr, type) and issubclass(attr, ViraModule) and attr != ViraModule:
                    module_instance = attr(attr.__name__)
                    await module_instance.initialize()
                    self._modules[module_instance.name] = module_instance
                    logger.info(f"Loaded module: {module_instance.name}")
                    # Record success
                    if self.metrics_manager:
                        duration = time.time() - start
                        self.metrics_manager.record_module_load(module_instance.name, duration)
                    return True

            logger.error(f"No ViraModule found in {module_path}")
            # Record failure as error
            if self.metrics_manager:
                self.metrics_manager.record_error("module_load_failure", module_path)
            return False
        except Exception as e:
            logger.error(f"Failed to load module {module_path}: {e}")
            if self.metrics_manager:
                self.metrics_manager.record_error("module_load_exception", module_path)
            return False
        
    async def unload_module(self, name: str) -> bool:
        """Unload a module by name"""
        if name not in self._modules:
            return False
        module = self._modules[name]
        try:
            await module.stop()
            del self._modules[name]
            logger.info(f"Unloaded module: {name}")
            return True
        except Exception as e:
            logger.error(f"Failed to unload module {name}: {e}")
            return False

    async def _monitor_loop(self):
        """Periodically check module health and restart failed ones"""
        while self._running:
            await asyncio.sleep(30)  # Check every 30 seconds
            for name, module in list(self._modules.items()):
                try:
                    health = await module.health()
                    if not health.get("running", False):
                        logger.warning(f"Module {name} not running, attempting restart")
                        await self.unload_module(name)
                        # Reload from original source - simplified: just log
                        # In production, track original import path
                except Exception as e:
                    logger.error(f"Health check failed for {name}: {e}")

    def get_module(self, name: str) -> Optional[ViraModule]:
        """Get module instance"""
        return self._modules.get(name)

    def list_modules(self) -> List[Dict[str, Any]]:
        """List all loaded modules with status"""
        return [{"name": name, "running": m._running} for name, m in self._modules.items()]

    async def load_core_modules(self):
        """Load all modules from the core modules directory"""
        if not self.modules_dir.exists():
            logger.warning(f"Modules directory not found: {self.modules_dir}")
            return

        for pyfile in self.modules_dir.glob("*.py"):
            if pyfile.name.startswith("_"):
                continue
            module_name = pyfile.stem
            await self.load_module(str(pyfile))

    def get_modules(self) -> List[ViraModule]:
        return list(self._modules.values())