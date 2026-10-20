"""Base sensor abstraction"""
from abc import ABC, abstractmethod


class BaseSensor(ABC):
    """Base class for all sensors"""

    def __init__(self, name: str):
        self.name = name
        self._running = False

    @abstractmethod
    async def start(self) -> None:
        """Start the sensor"""
        pass

    @abstractmethod
    async def stop(self) -> None:
        """Stop the sensor"""
        pass

    @abstractmethod
    async def read(self):
        """Read sensor data"""
        pass