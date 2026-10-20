# vira/agent/base.py
from abc import ABC, abstractmethod
from typing import List, Optional, Dict, Any, Callable, Awaitable
import time
import uuid
from vira.agent_runtime.runtime import AgentRuntime, AgentContext
from .registry import AgentCapability, AgentState

class BaseAgent(ABC):
    """
    Abstract base class for all agents.
    Lifecycle: INITIALIZED → READY → RUNNING → (WAITING/FAILED) → TERMINATED
    """

    def __init__(self, 
                 name: str,
                 description: str = "",
                 runtime: Optional[AgentRuntime] = None,
                 agent_id: Optional[str] = None):
        self.agent_id = agent_id or str(uuid.uuid4())
        self.name = name
        self.description = description
        self.runtime = runtime
        self.state = AgentState.INITIALIZED
        self._capabilities: List[AgentCapability] = []
        self._subscribed_events: List[str] = []
        self._interval_seconds: Optional[float] = None
        self._context: Optional[AgentContext] = None

    @property
    def capabilities(self) -> List[AgentCapability]:
        return self._capabilities

    @property
    def subscribed_events(self) -> List[str]:
        return self._subscribed_events

    @property
    def interval_seconds(self) -> Optional[float]:
        return self._interval_seconds

    async def initialize(self):
        """Called once after registration. Set up resources."""
        self.state = AgentState.INITIALIZED

    async def start(self):
        """Transition to READY."""
        self.state = AgentState.READY

    async def stop(self):
        """Transition to TERMINATED; clean up."""
        self.state = AgentState.TERMINATED

    async def can_handle(self, event) -> bool:
        """Override to provide custom event filtering."""
        return True

    async def handle(self, event):
        """
        Event‑driven entry point. 
        Usually calls think/plan/act/reflect based on event.
        """
        self.state = AgentState.RUNNING
        try:
            # Refresh context
            self._context = await self.runtime.get_context(self.agent_id)
            # Process event
            await self._process_event(event)
        except Exception as e:
            self.state = AgentState.FAILED
            raise
        finally:
            if self.state != AgentState.FAILED:
                self.state = AgentState.READY

    async def run(self, input_data: Dict = None):
        """
        Task‑based entry point (used by workflows).
        """
        self.state = AgentState.RUNNING
        try:
            self._context = await self.runtime.get_context(self.agent_id)
            result = await self._execute(input_data or {})
            return result
        except Exception as e:
            self.state = AgentState.FAILED
            raise
        finally:
            if self.state != AgentState.FAILED:
                self.state = AgentState.READY

    # Core agent methods to implement
    @abstractmethod
    async def think(self, context: AgentContext, **kwargs) -> Dict:
        """Analyze context and determine next action."""
        pass

    @abstractmethod
    async def plan(self, thought: Dict, **kwargs) -> List[Dict]:
        """Create a sequence of actions based on thought."""
        pass

    @abstractmethod
    async def act(self, plan: List[Dict], **kwargs) -> Any:
        """Execute the plan using tools and/or LLM."""
        pass

    @abstractmethod
    async def reflect(self, result: Any, **kwargs) -> Dict:
        """Evaluate result and update internal state."""
        pass

    # Internal orchestration
    async def _process_event(self, event):
        thought = await self.think(self._context, event=event)
        plan = await self.plan(thought, event=event)
        result = await self.act(plan, event=event)
        reflection = await self.reflect(result, event=event)
        # Optionally store reflection in memory
        return reflection

    async def _execute(self, input_data: Dict):
        thought = await self.think(self._context, input=input_data)
        plan = await self.plan(thought, input=input_data)
        result = await self.act(plan, input=input_data)
        reflection = await self.reflect(result, input=input_data)
        return result