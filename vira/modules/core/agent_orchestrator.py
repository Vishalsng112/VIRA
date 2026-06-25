# vira/modules/core/agent_orchestrator.py
import importlib
import asyncio
from loguru import logger
from vira.agent_orchestration.message_bus import AgentMessageBus
from vira.kernel.module_manager import ViraModule
from vira.agent_orchestration.registry import AgentRegistry
from vira.agent_orchestration.router import EventRouter
from vira.agent_orchestration.scheduler import RuntimeScheduler
from vira.agent_runtime.runtime import AgentRuntime
from vira.memory.manager import MemoryManager
from vira.llm.manager import LLMManager
from vira.tools.executor import ToolExecutor
from vira.tools.registry import ToolRegistry
from vira.tools.connection import MCPServerConnection
from vira.tools.base import ToolPermission

try:
    from mcp import ClientSession
    from mcp.client.stdio import stdio_client, StdioServerParameters
    MCP_AVAILABLE = True
except (ImportError, AttributeError) as e:
    MCP_AVAILABLE = False
    logger.warning(f"MCP SDK not available: {e}. MCP tools disabled.")


class AgentOrchestratorModule(ViraModule):
    def __init__(self, name="agent_orchestrator"):
        super().__init__(name)
        # Injected dependencies
        self._event_bus = None
        self._dispatcher = None
        self._scheduler = None
        self._context_manager = None
        self._security_manager = None
        self._config_manager = None

        # Own components
        self.registry = None
        self.router = None
        self.runtime_scheduler = None
        self.runtime = None

        # Tool components
        self.tool_registry = None
        self.tool_executor = None

        # MCP connections (managed by the registry)
        self._mcp_connections = []

    # ---- Setter methods for dependency injection ----
    def set_event_bus(self, event_bus):
        self._event_bus = event_bus

    def set_dispatcher(self, dispatcher):
        self._dispatcher = dispatcher

    def set_scheduler(self, scheduler):
        self._scheduler = scheduler

    def set_context_manager(self, context_manager):
        self._context_manager = context_manager

    def set_security_manager(self, security_manager):
        self._security_manager = security_manager

    def set_config_manager(self, config_manager):
        self._config_manager = config_manager

    # ---- ViraModule lifecycle ----
    async def initialize(self):
        pass

    async def start(self):
        # Ensure dependencies are present
        if not all([self._event_bus, self._context_manager, self._security_manager, self._config_manager]):
            logger.error("Missing required dependencies for AgentOrchestratorModule")
            self._running = False
            return

        try:
            # Create tool registry and executor
            self.tool_registry = ToolRegistry()
            self.tool_executor = ToolExecutor(self.tool_registry, self._security_manager)

            # --- MCP Connection with enhanced logging ---
            mcp_config = self._config_manager.get("mcp_server", {}) or {}

            if MCP_AVAILABLE and mcp_config and "command" in mcp_config:
                logger.info("Attempting to connect to MCP server...")
                try:
                    command = mcp_config["command"]
                    args = mcp_config.get("args", [])
                    if isinstance(command, list):
                        cmd = command[0]
                        args = command[1:] + args
                    else:
                        cmd = command

                    connection = MCPServerConnection.stdio(
                        name="mcp_server",
                        command=cmd,
                        args=args,
                        env=mcp_config.get("env")
                    )

                    perm_actions = mcp_config.get("permissions", ["read", "execute"])
                    default_perms = ToolPermission(actions=perm_actions)

                    registered = await self.tool_registry.register_mcp_server(
                        connection=connection,
                        default_permissions=default_perms
                    )
                    self._mcp_connections.append(connection)
                    logger.info(f"Registered MCP tools: {registered}")

                except Exception as e:
                    logger.error(f"Failed to connect to MCP server: {e}")
                    # Continue without MCP tools
            else:
                logger.warning(
                    "MCP not available or no 'mcp_server' config. "
                    "Only local tools (if any) will be available."
                )
            # After registration, log the final registry state
            logger.info(f"Final tool registry: {self.tool_registry.list()}")

            self.agent_message_bus = AgentMessageBus()  # Create the agent message bus

            try:
                # Create core services
                memory_manager = MemoryManager()
                llm_manager = LLMManager()   # create before tool_registry?
                # tool_registry = ToolRegistry()
                # tool_executor = ToolExecutor(tool_registry, self._security_manager)

                # Set tool registry in LLM manager
                llm_manager.set_tool_registry(self.tool_registry)

                # Load LLM configuration
                llm_config = self._config_manager.get("llm", {})
                logger.debug(f"LLM configuration: {llm_config}")
                if llm_config:
                    default_model = llm_config.get("default_model")
                    for model_cfg in llm_config.get("models", []):
                        provider_name = model_cfg.get("provider")
                        if not provider_name:
                            continue
                        # Create provider using factory
                        from vira.llm.factory import create_provider
                        provider = create_provider(model_cfg)
                        # Register provider with the models it supports (list or single)
                        # Actually, we want to map the logical model name (e.g., "gpt-4") to the provider.
                        # In the config, the "name" field is the logical name, and "model" is the actual model string.
                        logical_name = model_cfg.get("name") or model_cfg["model"]
                        llm_manager.register_provider(provider_name, provider, [logical_name])
                        # Also register with actual model string as alias
                        # llm_manager.register_provider(provider_name, provider, [model_cfg["model"]])
                    # Set default model in manager (maybe store separately)
                    llm_manager.default_model = default_model
                else:
                    logger.warning("No LLM configuration found; agents will not be able to call LLM.")
            except Exception as e:
                logger.error(f"Failed to initialize LLM Manager: {e}")
                raise

            # Continue with runtime creation, now passing llm_manager
            self.runtime = AgentRuntime(
                memory_manager=memory_manager,
                llm_manager=llm_manager,   # already set
                tool_executor=self.tool_executor,
                security_manager=self._security_manager,
                context_manager=self._context_manager,
                agent_message_bus=self.agent_message_bus
            )

            # Create orchestrator components
            self.registry = AgentRegistry()
            self.runtime_scheduler = RuntimeScheduler(self.registry, max_concurrent=10)
            self.router = EventRouter(
                self._event_bus, 
                self.registry, 
                scheduler=self.runtime_scheduler, 
                agent_message_bus=self.agent_message_bus)

            await self.router.start()

            # Load agents from config (now tools are already registered)
            agents_cfg = self._config_manager.get("agents", []) or []
            logger.info(f"Loaded agents config: {agents_cfg}")  # See what's really there
            for cfg in agents_cfg:
                logger.debug(f"Loading agent: {cfg.get('name')} with module {cfg.get('module')} and class {cfg.get('class')}")
                if not cfg.get("enabled", True):
                    logger.info(f"Skipping disabled AGENT: {cfg.get('name')}")
                    continue
                
                try:
                    module_name = cfg["module"]
                    class_name = cfg["class"]
                    module = importlib.import_module(module_name)
                    agent_class = getattr(module, class_name)
                    agent_config = cfg.get("config", {})
                    agent = agent_class(self.runtime, **agent_config)
                    await agent.initialize()
                    await agent.start()
                    await self.registry.register(agent)
                    logger.info(f"Agent loaded: {cfg['name']} (ID: {agent.agent_id})")
                except Exception as e:
                    logger.error(f"Failed to load agent {cfg.get('name')}: {e}")
            # print(1/0)
            self._running = True
            logger.info("Agent Orchestrator Module started")



        except Exception as e:
            logger.error(f"Failed to start Agent Orchestrator Module: {e}")
            self._running = False
            raise

    async def stop(self):
        self._running = False

        # Stop router and unregister agents
        if self.router:
            await self.router.stop()
        if self.registry:
            for meta in await self.registry.list_agents():
                await self.registry.unregister(meta.agent_id)

        # Close all MCP connections via the registry (this will also close the sessions)
        if self.tool_registry:
            await self.tool_registry.close_all()

        # Clear references
        self._mcp_connections.clear()
        self.tool_registry = None
        self.tool_executor = None

        logger.info("Agent Orchestrator Module stopped")


    async def get_status(self) -> dict:
        """Return detailed status of the orchestrator and its agents."""
        status = {
            "running": self._running,
            "agents": [],
            "scheduler": {
                "max_concurrent": 0,
                "running_tasks": 0,
                "pending_tasks": 0,
            },
            "runtime": {
                "memory_manager": "initialized" if self.runtime and self.runtime.memory_manager else "not_available",
                "llm_manager": "initialized" if self.runtime and self.runtime.llm_manager else "not_available",
            },
            "tools": {
                "total": 0,
                "mcp_connections": len(self._mcp_connections),
            }
        }

        if self.registry:
            agent_metas = await self.registry.list_agents()
            for meta in agent_metas:
                status["agents"].append({
                    "id": meta.agent_id,
                    "name": meta.name,
                    "status": getattr(meta, 'status', 'unknown'),
                    "capabilities": getattr(meta, 'capabilities', []),
                })

        if self.runtime_scheduler:
            status["scheduler"]["max_concurrent"] = self.runtime_scheduler.max_concurrent
            status["scheduler"]["running_tasks"] = len(getattr(self.runtime_scheduler, '_running', []))
            status["scheduler"]["pending_tasks"] = len(getattr(self.runtime_scheduler, '_pending', []))

        if self.tool_registry:
            status["tools"]["total"] = len(self.tool_registry.list())

        return status