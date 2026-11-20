"""Durable, resumable agent workflows (DAG of steps)."""
import asyncio
import json
import re
import time
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional

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
    agent_id: str
    input: Dict[str, Any] = {}
    depends_on: List[str] = []
    retry_policy: Optional[Dict[str, Any]] = None
    compensation: Optional[str] = None
    status: str = "pending"
    attempts: int = 0
    result: Any = None
    error: Optional[str] = None
    started_at: Optional[str] = None
    completed_at: Optional[str] = None


class Workflow(BaseModel):
    id: str
    name: str
    steps: List[WorkflowStep]
    status: WorkflowStatus = WorkflowStatus.PENDING
    context: Dict[str, Any] = {}
    created_by_user_id: Optional[int] = None
    organization_id: Optional[str] = None
    error: Optional[str] = None
    created_at: float = Field(default_factory=time.time)
    completed_at: Optional[float] = None


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class WorkflowEngine:
    """Persists every step transition; completed steps never run again.

    After a restart ``resume_all`` reloads pending/running workflows and
    continues from persisted step results.  The API process owns the runtime
    and scheduler, so this engine is instantiated by the agent orchestrator.
    """

    def __init__(self, runtime_scheduler, registry):
        self._scheduler = runtime_scheduler
        self._registry = registry
        self._running: Dict[str, asyncio.Task] = {}

    async def create(self, workflow: Workflow, user_id: Optional[int] = None) -> Workflow:
        from . import workflow_store as store
        store.create(workflow, user_id)
        return workflow

    async def start(self, workflow_id: str) -> Workflow:
        from . import workflow_store as store
        workflow = store.load(workflow_id)
        if workflow is None:
            raise ValueError("workflow not found")
        if workflow.status in (WorkflowStatus.COMPLETED, WorkflowStatus.CANCELLED):
            return workflow
        if workflow_id not in self._running:
            self._running[workflow_id] = asyncio.create_task(self._run(workflow_id))
        return workflow

    async def resume(self, workflow_id: str, retry_failed: bool = False) -> Workflow:
        from . import workflow_store as store
        workflow = store.load(workflow_id)
        if workflow is None:
            raise ValueError("workflow not found")
        if workflow.status == WorkflowStatus.COMPLETED:
            return workflow
        store.reset_running(workflow_id)
        if retry_failed:
            store.reset_failed(workflow_id)
        workflow.status = WorkflowStatus.RUNNING
        workflow.error = None
        store.save_workflow(workflow)
        store.append_event(workflow_id, "workflow.resumed")
        return await self.start(workflow_id)

    async def resume_all(self) -> int:
        from . import workflow_store as store
        ids = store.list_active_ids()
        for workflow_id in ids:
            store.reset_running(workflow_id)
            workflow = store.load(workflow_id)
            if workflow:
                workflow.status = WorkflowStatus.RUNNING
                store.save_workflow(workflow)
            await self.start(workflow_id)
        return len(ids)

    async def cancel(self, workflow_id: str) -> bool:
        from . import workflow_store as store
        task = self._running.pop(workflow_id, None)
        if task:
            task.cancel()
        workflow = store.load(workflow_id)
        if not workflow:
            return False
        workflow.status = WorkflowStatus.CANCELLED
        workflow.completed_at = time.time()
        workflow.error = "cancelled"
        store.save_workflow(workflow)
        store.append_event(workflow_id, "workflow.cancelled")
        return True

    async def _run(self, workflow_id: str) -> None:
        from . import workflow_store as store
        try:
            workflow = store.load(workflow_id)
            if workflow is None:
                return
            workflow.status = WorkflowStatus.RUNNING
            store.save_workflow(workflow)
            store.append_event(workflow_id, "workflow.started")
            while True:
                workflow = store.load(workflow_id)
                if workflow is None or workflow.status == WorkflowStatus.CANCELLED:
                    return
                terminal = {"completed", "skipped"}
                if all(step.status in terminal for step in workflow.steps):
                    workflow.status = WorkflowStatus.COMPLETED
                    workflow.completed_at = time.time()
                    store.save_workflow(workflow)
                    store.append_event(workflow_id, "workflow.completed")
                    return
                if any(step.status == "failed" for step in workflow.steps):
                    workflow.status = WorkflowStatus.FAILED
                    workflow.error = next(
                        (step.error for step in workflow.steps if step.status == "failed"),
                        "step failed",
                    )
                    workflow.completed_at = time.time()
                    store.save_workflow(workflow)
                    store.append_event(workflow_id, "workflow.failed",
                                       data={"error": workflow.error})
                    return
                by_id = {step.id: step for step in workflow.steps}
                ready = [
                    step for step in workflow.steps
                    if step.status == "pending"
                    and all(by_id.get(dep, WorkflowStep(id=dep, name=dep, agent_id=""))
                            .status in terminal for dep in step.depends_on)
                ]
                if not ready:
                    workflow.status = WorkflowStatus.FAILED
                    workflow.error = "cyclic or unresolved dependencies"
                    workflow.completed_at = time.time()
                    store.save_workflow(workflow)
                    store.append_event(workflow_id, "workflow.failed",
                                       data={"error": workflow.error})
                    return
                for step in ready:
                    step.status = "running"
                    step.started_at = _now()
                    step.attempts += 1
                    store.save_step(workflow_id, step)
                    store.append_event(workflow_id, "step.started", step.id,
                                       {"attempt": step.attempts})
                    results = {
                        item.id: item.result for item in workflow.steps
                        if item.status == "completed"
                    }
                    try:
                        result = await self._execute_step(step, workflow.context, results)
                        step.status = "completed"
                        step.result = result
                        step.error = None
                        step.completed_at = _now()
                        store.save_step(workflow_id, step)
                        store.append_event(workflow_id, "step.completed", step.id,
                                           {"result": result})
                    except Exception as exc:
                        step.error = str(exc)
                        max_retries = int((step.retry_policy or {}).get("max_retries", 0))
                        delay = float((step.retry_policy or {}).get("delay", 1))
                        if step.attempts <= max_retries:
                            step.status = "pending"
                            store.save_step(workflow_id, step)
                            store.append_event(workflow_id, "step.retry", step.id,
                                               {"error": str(exc), "attempt": step.attempts})
                            await asyncio.sleep(max(0, delay))
                        else:
                            step.status = "failed"
                            step.completed_at = _now()
                            store.save_step(workflow_id, step)
                            store.append_event(workflow_id, "step.failed", step.id,
                                               {"error": str(exc)})
                            if step.compensation:
                                await self._compensate(workflow_id, workflow, step.compensation)
                            break
                await asyncio.sleep(0)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            try:
                workflow = store.load(workflow_id)
                if workflow:
                    workflow.status = WorkflowStatus.FAILED
                    workflow.error = str(exc)
                    workflow.completed_at = time.time()
                    store.save_workflow(workflow)
                    store.append_event(workflow_id, "workflow.failed",
                                       data={"error": str(exc)})
            except Exception:
                pass
        finally:
            self._running.pop(workflow_id, None)

    async def _compensate(self, workflow_id: str, workflow: Workflow, step_id: str) -> None:
        from . import workflow_store as store
        step = next((item for item in workflow.steps if item.id == step_id), None)
        if not step:
            return
        try:
            await self._execute_step(step, workflow.context, {})
            step.status = "completed"
            store.save_step(workflow_id, step)
            store.append_event(workflow_id, "step.compensated", step.id)
        except Exception as exc:
            store.append_event(workflow_id, "step.compensation_failed", step.id,
                               {"error": str(exc)})

    async def _execute_step(self, step: WorkflowStep, context: Dict[str, Any],
                            results: Dict[str, Any]) -> Any:
        agent = await self._registry.get_instance(step.agent_id)
        if agent is None:
            raise ValueError(f"agent not found: {step.agent_id}")
        input_data = _resolve_input(step.input, context, results)
        return await self._scheduler.run_agent(agent, input_data=input_data)


def _resolve_input(value: Any, context: Dict[str, Any], results: Dict[str, Any]) -> Any:
    if isinstance(value, list):
        return [_resolve_input(item, context, results) for item in value]
    if isinstance(value, dict):
        return {key: _resolve_input(item, context, results) for key, item in value.items()}
    if not isinstance(value, str):
        return value
    match = re.fullmatch(r"\{\{\s*([^}]+?)\s*\}\}", value.strip())
    if not match:
        return value
    path = match.group(1).strip()
    if path.startswith("context."):
        return _dig(context, path[len("context."):].split("."))
    if path.startswith("results."):
        return _dig(results, path[len("results."):].split("."))
    if path.startswith("steps.") and path.endswith(".result"):
        return _dig(results, path[len("steps."):-len(".result")].split("."))
    return value


def _dig(value: Any, parts: List[str]) -> Any:
    for part in parts:
        if isinstance(value, dict):
            value = value.get(part)
        else:
            return None
    return value
