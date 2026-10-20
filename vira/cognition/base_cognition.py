"""Replaceable cognition layer interface"""
from abc import ABC, abstractmethod


class BaseCognition(ABC):
    """Base interface for AI/cognition providers"""

    @abstractmethod
    async def process(self, input_data: dict, context: dict) -> dict:
        """Process input with context and return decision"""
        pass

    @abstractmethod
    async def train(self, examples: list) -> None:
        """Train or fine-tune the cognition model"""
        pass