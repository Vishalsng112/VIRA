"""Working memory and current activity context"""
from loguru import logger
import asyncio
from typing import Dict, Any, Optional, List
from datetime import datetime
from collections import deque

# logger = logging.getLogger(__name__)


class ContextManager:
    """Maintains current working memory and context state"""

    def __init__(self, max_history: int = 100):
        self._current_context: Dict[str, Any] = {}
        self._context_history: deque = deque(maxlen=max_history)
        self._lock = asyncio.Lock()

    async def start(self):
        """Start context manager"""
        logger.info("ContextManager started")

    async def stop(self):
        """Stop context manager"""
        logger.info("ContextManager stopped")

    async def update_context(self, updates: Dict[str, Any]) -> Dict[str, Any]:
        """Update current context with new values"""
        async with self._lock:
            # Save snapshot to history before update
            if self._current_context:
                self._context_history.append({
                    "timestamp": datetime.now().isoformat(),
                    "context": self._current_context.copy(),
                })

            # Apply updates
            for key, value in updates.items():
                self._current_context[key] = value

            logger.debug(f"Context updated: {list(updates.keys())}")
            return self._current_context.copy()

    async def get_current_context(self) -> Dict[str, Any]:
        """Get current context snapshot"""
        async with self._lock:
            return self._current_context.copy()

    async def get_context_value(self, key: str, default: Any = None) -> Any:
        """Get a specific context value"""
        async with self._lock:
            return self._current_context.get(key, default)

    async def clear_context(self) -> None:
        """Clear all context"""
        async with self._lock:
            self._current_context.clear()
            logger.debug("Context cleared")

    async def get_context_history(self, limit: int = 10) -> List[Dict[str, Any]]:
        """Get recent context history"""
        async with self._lock:
            return list(self._context_history)[-limit:]

    async def set_session_metadata(self, key: str, value: Any) -> None:
        """Set session-level metadata"""
        if "_session" not in self._current_context:
            self._current_context["_session"] = {}
        self._current_context["_session"][key] = value