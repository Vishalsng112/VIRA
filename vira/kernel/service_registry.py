"""Service Registry for dependency discovery"""
from loguru import logger
from typing import Dict, Type, TypeVar, Any, Optional

# logger = logging.getLogger(__name__)

T = TypeVar('T')


class ServiceRegistry:
    """Central service registry for loose coupling"""

    def __init__(self):
        self._services: Dict[str, Any] = {}
        self._lock = False

    def register(self, name: str, service: Any) -> None:
        """Register a service instance"""
        if name in self._services:
            logger.warning(f"Overwriting service: {name}")
        self._services[name] = service
        logger.debug(f"Registered service: {name}")

    def get(self, name: str) -> Any:
        """Get a registered service"""
        if name not in self._services:
            raise KeyError(f"Service not found: {name}")
        return self._services[name]

    def get_or_default(self, name: str, default: Any = None) -> Any:
        """Get service or return default"""
        return self._services.get(name, default)

    def remove(self, name: str) -> bool:
        """Remove a service"""
        if name in self._services:
            del self._services[name]
            logger.debug(f"Removed service: {name}")
            return True
        return False

    def list_services(self) -> list:
        """List all registered service names"""
        return list(self._services.keys())

    def has(self, name: str) -> bool:
        """Check if service exists"""
        return name in self._services