"""Main Kernel orchestrator - the nervous system of VIRA"""
import asyncio
from loguru import logger
import signal
from typing import Optional, Dict, Any, Callable

from vira.kernel.plugin_manager import PluginManager

from .event_bus import EventBus, Event, EventPriority
from .service_registry import ServiceRegistry
from .module_manager import ModuleManager
from .scheduler import Scheduler
from .state_manager import StateManager
from .config_manager import ConfigManager
from .security_manager import SecurityManager
from .metrics_manager import MetricsManager
from .context_manager import ContextManager
from .event_pipeline import EventPipeline
from .event_dispatcher import EventDispatcher
# from .agent_manager import AgentManager

# logger = logging.getLogger(__name__)

# current states of kernel: INIT, LOADING_CONFIG, STARTING_EVENT_BUS, SERVICE_REGISTRY, STARTING_STATE_MANAGER, STARTING_SCHEDULER, LOADING_CORE_MODULES, LOADING_PLUGINS, STARTING_SENSORS, RUNNING, SHUTDOWN
class Kernel:
    """Core kernel that integrates all subsystems"""

    # Sensor registry: maps sensor name -> factory function
    # Factory signature: (config: dict, event_bus, dispatcher, metrics_manager) -> Sensor instance
    _sensor_factories: Dict[str, Callable] = {}

    @classmethod
    def register_sensor(cls, name: str, factory: Callable):
        """Register a sensor factory."""
        cls._sensor_factories[name] = factory
        logger.debug(f"Sensor factory registered: {name}")

    def __init__(self, config_path: Optional[str] = None):
        self.config_manager = ConfigManager(config_path)
        self.service_registry = ServiceRegistry()
        self.event_bus = EventBus()
        self.scheduler = Scheduler()
        self.state_manager = None
        self.dispatcher = None
        self.module_manager = None
        self.plugin_manager = None
        self.security_manager = SecurityManager()
        self.metrics_manager = MetricsManager()
        self.context_manager = ContextManager()
        self.event_pipeline = EventPipeline()

        self._running = False
        self._state = "INIT"
        self._sensors = []

        # Register built-in sensors (could also be done via entry points or auto-discovery)
        self._register_builtin_sensors()

    def _register_builtin_sensors(self):
        """Register all built-in sensor factories."""
        # Import sensor classes here to avoid circular imports
        from vira.sensors.system_sensor import SystemSensor
        from vira.sensors.hardware_sensor import HardwareSensor
        from vira.sensors.process_sensor import ProcessSensor
        from vira.sensors.network_sensor import NetworkSensor
        from vira.sensors.workspace_sensor import WorkspaceSensor
        from vira.sensors.project_sensor import ProjectSensor
        from vira.sensors.activity_sensor import ActivitySensor
        from vira.sensors.user_activity_sensor import UserActivitySensor
        from vira.sensors.filesystem_sensor import FileSystemSensor

        # Define factories that capture the required dependencies
        self.register_sensor("system_sensor", lambda cfg, eb, disp, mm: SystemSensor(
            interval=cfg.get("interval", 5.0),
            event_bus=eb,
            dispatcher=disp
        ))
        self.register_sensor("hardware_sensor", lambda cfg, eb, disp, mm: HardwareSensor(
            interval=cfg.get("interval", 5.0),
            event_bus=eb,
            dispatcher=disp
        ))
        self.register_sensor("process_sensor", lambda cfg, eb, disp, mm: ProcessSensor(
            interval=cfg.get("interval", 10.0),
            event_bus=eb,
            dispatcher=disp
        ))
        self.register_sensor("network_sensor", lambda cfg, eb, disp, mm: NetworkSensor(
            interval=cfg.get("interval", 5.0),
            event_bus=eb,
            dispatcher=disp
        ))
        self.register_sensor("workspace_sensor", lambda cfg, eb, disp, mm: WorkspaceSensor(
            interval=cfg.get("interval", 2.0),
            event_bus=eb,
            dispatcher=disp
        ))
        self.register_sensor("project_sensor", lambda cfg, eb, disp, mm: ProjectSensor(
            interval=cfg.get("interval", 5.0),
            event_bus=eb,
            dispatcher=disp
        ))
        self.register_sensor("activity_sensor", lambda cfg, eb, disp, mm: ActivitySensor(
            interval=cfg.get("interval", 5.0),
            event_bus=eb,
            dispatcher=disp
        ))
        self.register_sensor("user_activity_sensor", lambda cfg, eb, disp, mm: UserActivitySensor(
            interval=cfg.get("interval", 10.0),
            event_bus=eb,
            dispatcher=disp
        ))
        self.register_sensor("filesystem_sensor", lambda cfg, eb, disp, mm: FileSystemSensor(
            watch_path=cfg.get("watch_path"),
            event_bus=eb,
            dispatcher=disp,
            metrics_manager=mm,
            recursive=cfg.get("recursive", True),
            event_types=cfg.get("event_types"),
            include_patterns=cfg.get("include_patterns", ["*.pdf", "*.docx", "*.txt", "*.jpg", "*.png"]),
            ignore_patterns=cfg.get("ignore_patterns", []),
        ))

    async def boot(self) -> None:
        """Execute the boot sequence"""
        logger.info("=== VIRA Kernel Booting ===")

        # 1. Load Configuration
        self._state = "LOADING_CONFIG"
        await self.config_manager.initialize()
        logger.info("✓ Configuration loaded")

        # Setup state manager with checkpoint dir
        checkpoint_dir = self.config_manager.get("kernel.checkpoint_dir", "./data/checkpoints")
        self.state_manager = StateManager(checkpoint_dir)

        # Setup module manager
        modules_dir = self.config_manager.get("kernel.modules_dir", "./vira/modules/core")
        self.module_manager = ModuleManager(modules_dir)

        # Register core services
        self.service_registry.register("config_manager", self.config_manager)
        self.service_registry.register("event_bus", self.event_bus)
        self.service_registry.register("scheduler", self.scheduler)
        self.service_registry.register("security_manager", self.security_manager)
        self.service_registry.register("metrics_manager", self.metrics_manager)
        self.service_registry.register("context_manager", self.context_manager)
        self.service_registry.register("event_pipeline", self.event_pipeline)

        # Create dispatcher after all dependencies are available
        self.dispatcher = EventDispatcher(
            event_bus=self.event_bus,
            pipeline=self.event_pipeline,
            security=self.security_manager,
            metrics_manager=self.metrics_manager,
        )

        # 2. Start Event Bus
        self._state = "STARTING_EVENT_BUS"
        await self.event_bus.start()
        logger.info("✓ Event Bus started")

        # [DEBUG] Subscribe to all events for logging
        async def log_event(event: Event):
            # logger.debug(f"=====[EVENT]=====")
            # print("Keys:", event.data.keys())
            logger.debug(f"[Event]: {event.type}")  # Print the entire event object
            # print("-----")
            # print(event)
            # print("-----")
            # logger.debug("==================")
        self.event_bus.subscribe_all(log_event)

        # 3. Initialize Service Registry (already done)
        self._state = "SERVICE_REGISTRY"
        logger.info("✓ Service Registry ready")

        # 4. Start State Manager
        self._state = "STARTING_STATE_MANAGER"
        await self.state_manager.start()
        logger.info("✓ State Manager started")

        # 5. Start Scheduler
        self._state = "STARTING_SCHEDULER"
        await self.scheduler.start()
        logger.info("✓ Scheduler started")

        # Initialize security
        default_perms = self.config_manager.get("security.default_permissions", [])
        await self.security_manager.initialize(default_perms)

        # Start metrics
        await self.metrics_manager.start()

        # Start context manager
        await self.context_manager.start()

        # Start event pipeline
        await self.event_pipeline.start()

        # Register default pipeline stages
        self.event_pipeline.register_enricher(EventPipeline.default_timestamp_enricher())
        self.event_pipeline.register_prioritizer(EventPipeline.default_priority_classifier())

        # 6. Load Core Modules
        self._state = "LOADING_CORE_MODULES"
        await self.module_manager.start()
        await self.module_manager.load_core_modules()
        logger.info("✓ Core modules loaded")

        # --- Inject dependencies and start modules ---
        for module in self.module_manager.get_modules():
            if hasattr(module, 'set_event_bus'):
                module.set_event_bus(self.event_bus)
            if hasattr(module, 'set_dispatcher'):
                module.set_dispatcher(self.dispatcher)
            if hasattr(module, 'set_scheduler'):
                module.set_scheduler(self.scheduler)
            if hasattr(module, 'set_context_manager'):
                module.set_context_manager(self.context_manager)
            if hasattr(module, 'set_security_manager'):
                module.set_security_manager(self.security_manager)
            if hasattr(module, 'set_config_manager'):
                module.set_config_manager(self.config_manager)
            await module.start()
            logger.info(f"Started module: {module.name}")

        # 7. Load Plugins
        self._state = "LOADING_PLUGINS"
        plugins_dir = self.config_manager.get("kernel.plugins_dir", "./vira/plugins")
        self.plugin_manager = PluginManager(plugins_dir)
        await self.plugin_manager.load_plugins()
        logger.info("✓ Plugins loaded")

        # 8. Start Sensors (using the registry)
        self._state = "STARTING_SENSORS"
        sensors_config = self.config_manager.get("sensors", [])
        if sensors_config is None:
            sensors_config = []
        for sensor_cfg in sensors_config:
            if sensor_cfg.get("enabled", False):
                await self._start_sensor(sensor_cfg)
        logger.info("✓ Sensors started")

        # 10. Enter RUNNING State
        self._state = "RUNNING"
        self._running = True
        logger.info("=== VIRA Kernel Running ===")

        # Publish kernel ready event via dispatcher
        await self.dispatcher.publish(Event(
            type="kernel.ready",
            data={"state": self._state},
            source="kernel"
        ))


        # Grab the agent orchestrator module for later health checks
        self.agent_orchestrator = None
        for module in self.module_manager.get_modules():
            if module.name == "AgentOrchestratorModule":
                self.agent_orchestrator = module
                logger.info(f"✅ Agent orchestrator assigned: {module.name}")
                break        

    async def _start_sensor(self, sensor_config: Dict[str, Any]) -> None:
        """Start a sensor using the registry."""
        sensor_name = sensor_config.get("name")
        if not sensor_name:
            logger.error("Sensor config missing 'name'")
            return

        factory = self._sensor_factories.get(sensor_name)
        if not factory:
            logger.warning(f"Unknown sensor: {sensor_name}")
            return

        try:
            # Create sensor instance using the registered factory
            sensor = factory(
                sensor_config,
                self.event_bus,
                self.dispatcher,
                self.metrics_manager
            )
            await sensor.start()
            self._sensors.append(sensor)
            logger.info(f"Sensor started: {sensor_name}")
        except Exception as e:
            logger.error(f"Failed to start sensor {sensor_name}: {e}")

    async def shutdown(self) -> None:
        """Graceful shutdown of all subsystems"""
        logger.info("=== Shutting down VIRA Kernel ===")
        self._running = False
        self._state = "SHUTDOWN"

        # Stop sensors
        for sensor in self._sensors:
            try:
                await sensor.stop()
            except Exception as e:
                logger.error(f"Error stopping sensor: {e}")

        # Stop plugins
        if self.plugin_manager:
            await self.plugin_manager.stop_all()

        # Stop modules
        if self.module_manager:
            await self.module_manager.stop()

        # Stop scheduler
        await self.scheduler.stop()

        # Stop state manager (saves state)
        if self.state_manager:
            await self.state_manager.stop()

        # Stop event pipeline
        await self.event_pipeline.stop()

        # Stop context manager
        await self.context_manager.stop()

        # Stop metrics
        await self.metrics_manager.stop()

        # Stop event bus last
        await self.event_bus.stop()

        logger.info("=== VIRA Kernel Shutdown Complete ===")

    def get_state(self) -> str:
        """Get current kernel state"""
        return self._state

    def is_running(self) -> bool:
        """Check if kernel is running"""
        return self._running

    # async def health_check(self) -> Dict[str, Any]:
    #     """Comprehensive health check of all subsystems"""
    #     return {
    #         "kernel_state": self._state,
    #         "running": self._running,
    #         "services": self.service_registry.list_services(),
    #         "modules": self.module_manager.list_modules() if self.module_manager else [],
    #         "scheduled_tasks": self.scheduler.list_tasks() if self.scheduler else [],
    #     }

    async def health_check(self) -> Dict[str, Any]:
        """Comprehensive health check of all subsystems."""
        base = {
            "kernel_state": self._state,
            "running": self._running,
            "services": self.service_registry.list_services(),
            "modules": [],
            "scheduled_tasks": self.scheduler.list_tasks() if self.scheduler else [],
            "event_bus": {
                "subscribers": len(self.event_bus._subscribers) if hasattr(self.event_bus, '_subscribers') else 0,
                "pending_events": self.event_bus.pending_events() if hasattr(self.event_bus, 'pending_events') else 0,
            },
            "dispatcher": {
                "pipeline_stages": len(self.event_pipeline._enrichers) + len(self.event_pipeline._prioritizers) if self.event_pipeline else 0,
            },
            "context_manager": {
                "size": len(self.context_manager._context) if hasattr(self.context_manager, '_context') else 0,
            },
            "AgentOrchestratorModule": None,  # will be filled if orchestrator is present
        }

        # Module details
        if self.module_manager:
            for module in self.module_manager.get_modules():
                base["modules"].append({
                    "name": module.name,
                    "running": getattr(module, '_running', False),
                    "type": module.__class__.__name__,
                })

        # Agent orchestrator status
        if self.agent_orchestrator and hasattr(self.agent_orchestrator, 'get_status'):
            base["AgentOrchestratorModule"] = await self.agent_orchestrator.get_status()

        return base