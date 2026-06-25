from .kernel import Kernel
from .event_bus import EventBus, Event, EventPriority
from .service_registry import ServiceRegistry
from .module_manager import ModuleManager, ViraModule   # <-- add ViraModule
from .scheduler import Scheduler
from .state_manager import StateManager
from .config_manager import ConfigManager
from .security_manager import SecurityManager
from .metrics_manager import MetricsManager
from .context_manager import ContextManager
from .event_pipeline import EventPipeline, EventEnvelope

__all__ = [
    "Kernel",
    "EventBus",
    "Event",
    "EventPriority",
    "ServiceRegistry",
    "ModuleManager",
    "ViraModule",
    "Scheduler",
    "StateManager",
    "ConfigManager",
    "SecurityManager",
    "MetricsManager",
    "ContextManager",
    "EventPipeline",
    "EventEnvelope",
]