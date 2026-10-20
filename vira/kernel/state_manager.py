"""Checkpointing and recovery"""
import asyncio
import pickle
import json
from loguru import logger
from pathlib import Path
from typing import Dict, Any, Optional
from datetime import datetime

# logger = logging.getLogger(__name__)


class StateManager:
    """Manages state persistence, checkpointing and recovery"""

    def __init__(self, checkpoint_dir: str):
        self.checkpoint_dir = Path(checkpoint_dir)
        self.checkpoint_dir.mkdir(parents=True, exist_ok=True)
        self._state: Dict[str, Any] = {}
        self._running = False
        self._auto_save_task: Optional[asyncio.Task] = None

    async def start(self):
        """Start state manager and auto-save loop"""
        self._running = True
        await self.load_state()  # Load last known state
        self._auto_save_task = asyncio.create_task(self._auto_save_loop())
        logger.info(f"StateManager started, checkpoint dir: {self.checkpoint_dir}")

    async def stop(self):
        """Stop state manager and save final state"""
        self._running = False
        if self._auto_save_task:
            self._auto_save_task.cancel()
            try:
                await self._auto_save_task
            except asyncio.CancelledError:
                pass
        await self.save_state()
        logger.info("StateManager stopped")

    async def save_state(self, checkpoint_name: str = "latest") -> bool:
        """Save current state to disk"""
        state_data = {
            "timestamp": datetime.now().isoformat(),
            "state": self._state,
        }
        checkpoint_file = self.checkpoint_dir / f"{checkpoint_name}.json"
        try:
            with open(checkpoint_file, "w") as f:
                json.dump(state_data, f, indent=2, default=str)
            logger.debug(f"State saved to {checkpoint_file}")
            return True
        except Exception as e:
            logger.error(f"Failed to save state: {e}")
            return False

    async def load_state(self, checkpoint_name: str = "latest") -> bool:
        """Load state from disk"""
        checkpoint_file = self.checkpoint_dir / f"{checkpoint_name}.json"
        if not checkpoint_file.exists():
            logger.info(f"No checkpoint found at {checkpoint_file}, starting fresh")
            return False

        try:
            with open(checkpoint_file, "r") as f:
                state_data = json.load(f)
            self._state = state_data.get("state", {})
            logger.info(f"State loaded from {checkpoint_file}, timestamp: {state_data.get('timestamp')}")
            return True
        except Exception as e:
            logger.error(f"Failed to load state: {e}")
            return False

    def update_state(self, key: str, value: Any) -> None:
        """Update a state key"""
        self._state[key] = value

    def get_state(self, key: str, default: Any = None) -> Any:
        """Get state value"""
        return self._state.get(key, default)

    def get_all_state(self) -> Dict[str, Any]:
        """Get full state dictionary"""
        return self._state.copy()

    async def restore_runtime(self) -> None:
        """Restore runtime state after recovery"""
        # Placeholder for restoring module contexts, etc.
        logger.info("Runtime restoration complete")

    async def _auto_save_loop(self):
        """Auto-save state periodically"""
        while self._running:
            await asyncio.sleep(30)  # Save every 30 seconds
            await self.save_state()