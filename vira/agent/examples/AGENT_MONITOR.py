# vira/agent/examples/load_monitor_agent.py
from loguru import logger
from typing import Dict, Any, List, Optional
from vira.agent.base import BaseAgent
from vira.agent_orchestration.registry import AgentCapability
from vira.agent_runtime.runtime import AgentContext
from mcp.types import CallToolResult, TextContent  # adding for type clarity
class LoadMonitorAgent(BaseAgent):
    """
    Listens for hardware state events, checks CPU/memory load,
    and reacts if the system is under or over a threshold.
    """

    def __init__(self, runtime, 
                 cpu_threshold: float = 80.0,
                 memory_threshold: float = 80.0,
                 subscribed_events: List[str] = None,
                 llm_model: Optional[str] = None):
        super().__init__("LoadMonitorAgent", runtime=runtime)
        self.cpu_threshold = cpu_threshold
        self.memory_threshold = memory_threshold
        self.llm_model = llm_model
        self._subscribed_events = subscribed_events or ["sensor.hardware.state"]
        self._capabilities = [
            AgentCapability(
                name="monitor_load",
                description="Monitors system load and alerts"
            )
        ]
        # self._interval_seconds = 30.0

    async def start(self):
        """Override to log available tools."""
        await super().start()
        if self.runtime and self.runtime.tool_executor:
            tool_names = self.runtime.tool_executor.list_tools()   # use list_tools()
            logger.info(f"[{self.name}] Available tools: {tool_names}")
        else:
            logger.warning(f"[{self.name}] Tool executor not available.")

    async def think(self, context: AgentContext, **kwargs) -> Dict:
        """
        Extract CPU and memory usage from the event data.
        """
        logger.debug(f"[THINK] Received context: {context}, kwargs: {kwargs}")
        event = kwargs.get("event")
        if not event or not event.data:
            logger.warning(f"{self.name}: received event without data")
            return {"intent": "idle"}

        data = event.data
        cpu = data.get("cpu_percent", 90.0)
        memory = data.get("memory_percent", 95.0)
        logger.info(f"{self.name}: CPU={cpu}%, Memory={memory}%")

        # Determine if under or over load
        status = "normal"
        if cpu > self.cpu_threshold or memory > self.memory_threshold:
            status = "overload"
        elif cpu < 20 and memory < 20:
            status = "underload"

        return {
            "intent": "evaluate_load",
            "cpu": cpu,
            "memory": memory,
            "status": status
        }

    async def plan(self, thought: Dict, **kwargs) -> List[Dict]:
        logger.debug(f"[PLAN] Thought: {thought}")
        status = thought.get("status")
        plans = []

        if status == "overload":
            plans.append({
                "action": "alert",
                "params": {"message": f"System overloaded! CPU={thought['cpu']}%, Memory={thought['memory']}%"}
            })
            # Add LLM summary action
            plans.append({
                "action": "llm_summary",
                "params": {"cpu": thought['cpu'], "memory": thought['memory']}
            })
        elif status == "underload":
            plans.append({
                "action": "log",
                "params": {"message": f"System underutilised. CPU={thought['cpu']}%, Memory={thought['memory']}%"}
            })
        else:
            plans.append({
                "action": "log",
                "params": {"message": "System load is normal"}
            })

        # Optionally add web_browse only if the tool exists
        if self.runtime and self.runtime.tool_executor:
            if "web_browse" in self.runtime.tool_executor.list_tools():
                plans.append({"action": "web_browse", "params": {"url": "http://localhost:8080/status"}})

        return plans


        
    async def act(self, plan: List[Dict], **kwargs) -> Any:
        logger.debug(f"[ACT] Executing plan: {plan}")
        results = []
        for step in plan:
            action = step["action"]
            params = step.get("params", {})

            if action == "alert":
                msg = params["message"]
                logger.info(f"ALERT: {msg}")
                await self.runtime.memory_operation(
                    self.agent_id, "store",
                    content=msg,
                    metadata={"type": "load_alert"}
                )
                results.append({"alert": msg})

            elif action == "log":
                msg = params["message"]
                logger.info(f"LOG: {msg}")
                results.append({"logged": msg})

            elif action == "web_browse":
                url = params.get("url")
                if not url:
                    logger.warning(f"{self.name}: web_browse action missing URL")
                    continue
                try:
                    logger.info(f"{self.name}: Fetching URL via web_browse: {url}")
                    result = await self.runtime.tool_executor.execute("web_browse", url=url)
                    # (Handle CallToolResult as before)
                    # ... (your existing web_browse handling code)
                except Exception as e:
                    logger.error(f"{self.name}: web_browse failed: {e}")
                    results.append({"web_browse_error": str(e)})

            elif action == "llm_summary":
                cpu = params.get("cpu")
                memory = params.get("memory")
                prompt = (
                    f"System load is high: CPU={cpu}%, Memory={memory}%. "
                    "Suggest possible causes and actions to reduce the load."
                )
                try:
                    response = await self.runtime.call_llm(
                        self.agent_id,
                        prompt,
                        model=self.llm_model
                    )
                    text = response.text
                    logger.info(f"LLM suggestion: {text}")
                    await self.runtime.memory_operation(
                        self.agent_id,
                        "store",
                        content=text,
                        metadata={"type": "llm_suggestion"}
                    )
                    results.append({"llm_summary": text})
                except Exception as e:
                    logger.error(f"LLM call failed: {e}")
                    results.append({"llm_summary_error": str(e)})

            else:
                logger.warning(f"{self.name}: Unknown action '{action}'")

        return results

    async def reflect(self, result: Any, **kwargs) -> Dict:
        """
        Optionally store the outcome in memory for future decisions.
        """
        # Could store summary or status
        return {"status": "processed", "result": result}