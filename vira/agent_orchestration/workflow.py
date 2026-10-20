# vira/agent_orchestration/workflow.py
from typing import List, Dict, Any, Optional, Callable, Awaitable
from enum import Enum
import asyncio
import time
from pydantic import BaseModel, Field

class WorkflowStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"

class WorkflowStep(BaseModel):
    id: str
    name: str
    agent_id: str  # which agent to invoke
    input: Dict[str, Any] = {}
    depends_on: List[str] = []  # step IDs that must complete first
    retry_policy: Optional[Dict] = None  # e.g., {"max_retries": 3, "delay": 1}
    compensation: Optional[str] = None  # step ID for compensation

class Workflow(BaseModel):
    id: str
    name: str
    steps: List[WorkflowStep]
    status: WorkflowStatus = WorkflowStatus.PENDING
    context: Dict[str, Any] = {}
    created_at: float = Field(default_factory=time.time)
    completed_at: Optional[float] = None

class WorkflowEngine:
    """
    Orchestrates execution of workflows (DAG of steps).
    Supports sequential, parallel, and conditional branching.
    """

    def __init__(self, runtime_scheduler: "RuntimeScheduler", registry: "AgentRegistry"):
        self._scheduler = runtime_scheduler
        self._registry = registry
        self._running_workflows: Dict[str, asyncio.Task] = {}

    async def execute(self, workflow: Workflow) -> Workflow:
        """Start execution of a workflow."""
        if workflow.id in self._running_workflows:
            raise ValueError(f"Workflow {workflow.id} already running")
        workflow.status = WorkflowStatus.RUNNING
        task = asyncio.create_task(self._run_workflow(workflow))
        self._running_workflows[workflow.id] = task
        return workflow

    async def _run_workflow(self, workflow: Workflow):
        """Internal execution of steps respecting dependencies."""
        try:
            # Build dependency graph
            step_map = {step.id: step for step in workflow.steps}
            completed = set()
            results = {}

            # Topological execution (simplified)
            while len(completed) < len(step_map):
                ready = [s for s in step_map.values() 
                         if s.id not in completed and all(d in completed for d in s.depends_on)]
                if not ready:
                    raise RuntimeError("Cyclic dependency or unresolved steps")

                # Execute ready steps in parallel
                tasks = []
                for step in ready:
                    tasks.append(self._execute_step(step, workflow, results))
                step_results = await asyncio.gather(*tasks, return_exceptions=True)

                for step, result in zip(ready, step_results):
                    if isinstance(result, Exception):
                        # Apply retry or compensation
                        handled = await self._handle_step_failure(step, workflow, result)
                        if not handled:
                            workflow.status = WorkflowStatus.FAILED
                            return
                    else:
                        results[step.id] = result
                        completed.add(step.id)

            workflow.status = WorkflowStatus.COMPLETED
            workflow.completed_at = time.time()
        except Exception as e:
            workflow.status = WorkflowStatus.FAILED
            logger.error(f"Workflow {workflow.id} failed: {e}")
        finally:
            if workflow.id in self._running_workflows:
                del self._running_workflows[workflow.id]

    async def _execute_step(self, step: WorkflowStep, workflow: Workflow, results: Dict) -> Any:
        """Invoke an agent for a step."""
        agent = await self._registry.get_instance(step.agent_id)
        if not agent:
            raise ValueError(f"Agent {step.agent_id} not found")
        # Prepare input from workflow context and previous results
        input_data = self._resolve_input(step.input, workflow.context, results)
        # Schedule agent execution (non‑event, task‑based)
        output = await self._scheduler.run_agent(agent, input_data=input_data)
        return output

    def _resolve_input(self, input_spec: Dict, context: Dict, results: Dict) -> Dict:
        # Resolve placeholders like {{ context.foo }}, {{ results.step_id }}
        # Implementation omitted for brevity
        return input_spec

    async def _handle_step_failure(self, step: WorkflowStep, workflow: Workflow, error: Exception) -> bool:
        # Retry logic; if fails, invoke compensation step if defined
        # Simple implementation: retry up to max_retries
        max_retries = step.retry_policy.get("max_retries", 0) if step.retry_policy else 0
        delay = step.retry_policy.get("delay", 1) if step.retry_policy else 1
        for attempt in range(max_retries):
            await asyncio.sleep(delay)
            try:
                result = await self._execute_step(step, workflow, {})
                return True
            except Exception:
                continue
        # Compensation
        if step.compensation:
            comp_step = next((s for s in workflow.steps if s.id == step.compensation), None)
            if comp_step:
                await self._execute_step(comp_step, workflow, {})
                # Could mark step as compensated
        return False