# vira/agent_orchestration/planner.py
from typing import List, Dict, Any, Optional
from loguru import logger
from .registry import AgentRegistry, AgentMetadata
from .workflow import Workflow, WorkflowStep


class Planner:
    """
    Decomposes high‑level goals into a sequence of tasks (workflow)
    by selecting appropriate agents based on their capabilities.
    """

    def __init__(self, registry: AgentRegistry, capability_registry: "CapabilityRegistry"):
        self._registry = registry
        self._cap_registry = capability_registry

    async def create_plan(self, goal: str, context: Dict[str, Any] = None) -> Workflow:
        """
        Given a natural language goal, produce a Workflow.
        This is a high‑level planning method; in practice it may call an LLM.
        """
        # Simplified: identify required capabilities and select agents
        # For a real implementation, use an LLM to decompose goal into steps.
        # Here we simulate with a dummy decomposition.

        # 1. Parse goal (using LLM) into tasks with required capabilities.
        tasks = await self._decompose_goal(goal, context)

        # 2. For each task, find an agent with matching capability.
        steps = []
        for idx, task in enumerate(tasks):
            capability = task.get("capability")
            if not capability:
                continue
            agents = await self._registry.find_by_capability(capability)
            if not agents:
                raise ValueError(f"No agent found for capability {capability}")
            # Pick the first available agent (or use load balancing)
            agent_meta = agents[0]
            step = WorkflowStep(
                id=f"step_{idx}",
                name=task.get("name", f"Task {idx}"),
                agent_id=agent_meta.agent_id,
                input=task.get("input", {}),
                depends_on=task.get("depends_on", [])
            )
            steps.append(step)

        # 3. Build workflow
        workflow = Workflow(
            id=f"plan_{int(time.time())}",
            name=f"Plan for: {goal[:50]}",
            steps=steps,
            context=context or {}
        )
        return workflow

    async def _decompose_goal(self, goal: str, context: Dict) -> List[Dict]:
        """Use LLM to break goal into tasks. Stub for demo."""
        # In production, call LLM provider with a planning prompt.
        # Return list of dicts with keys: name, capability, input, depends_on.
        # Example:
        return [
            {"name": "Research topic", "capability": "web_search", "input": {"query": goal}},
            {"name": "Summarize findings", "capability": "summarize", "input": {"text": "{{ results.step_0 }}"}, "depends_on": ["step_0"]}
        ]