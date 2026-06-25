"""Action execution interface"""
from abc import ABC, abstractmethod


class BaseAction(ABC):
    """Base interface for executable actions"""

    @abstractmethod
    async def execute(self, params: dict) -> dict:
        """Execute the action with given parameters"""
        pass

    @abstractmethod
    async def validate(self, params: dict) -> bool:
        """Validate action parameters before execution"""
        pass