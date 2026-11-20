"""Persistence for durable workflows and step state."""
import json
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from vira.auth import database
from .workflow import Workflow, WorkflowStatus, WorkflowStep


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _step_row(step: WorkflowStep, workflow_id: str, seq: int) -> Dict[str, Any]:
    return {
        "workflow_id": workflow_id,
        "id": step.id,
        "seq": seq,
        "name": step.name,
        "agent_id": step.agent_id,
        "input": json.dumps(step.input, default=str),
        "depends_on": json.dumps(step.depends_on, default=str),
        "retry_policy": json.dumps(step.retry_policy, default=str) if step.retry_policy else None,
        "compensation": step.compensation,
        "status": step.status,
        "attempts": step.attempts,
        "result": json.dumps(step.result, default=str) if step.result is not None else None,
        "error": step.error,
        "started_at": step.started_at,
        "completed_at": step.completed_at,
    }


def _step_from_row(row: Dict[str, Any]) -> WorkflowStep:
    result = row.get("result")
    retry = row.get("retry_policy")
    return WorkflowStep(
        id=row["id"],
        name=row["name"],
        agent_id=row["agent_id"],
        input=_json(row.get("input"), {}),
        depends_on=_json(row.get("depends_on"), []),
        retry_policy=_json(retry, None) if retry else None,
        compensation=row.get("compensation"),
        status=row.get("status", "pending"),
        attempts=int(row.get("attempts", 0)),
        result=_json(result, None) if result is not None else None,
        error=row.get("error"),
        started_at=row.get("started_at"),
        completed_at=row.get("completed_at"),
    )


def _json(value: Any, default: Any) -> Any:
    try:
        return json.loads(value) if isinstance(value, str) else (value if value is not None else default)
    except ValueError:
        return default


def create(workflow: Workflow, user_id: Optional[int] = None) -> Workflow:
    now = _now()
    with database.transaction() as conn:
        conn.execute(
            "INSERT INTO workflows (id, name, status, context, created_by_user_id, "
            "organization_id, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (workflow.id, workflow.name, workflow.status.value,
             json.dumps(workflow.context, default=str), user_id,
             workflow.organization_id, now, now),
        )
        for seq, step in enumerate(workflow.steps):
            row = _step_row(step, workflow.id, seq)
            conn.execute(
                "INSERT INTO workflow_steps (workflow_id, id, seq, name, agent_id, input, "
                "depends_on, retry_policy, compensation, status, attempts, result, error, "
                "started_at, completed_at) VALUES (:workflow_id, :id, :seq, :name, :agent_id, "
                ":input, :depends_on, :retry_policy, :compensation, :status, :attempts, "
                ":result, :error, :started_at, :completed_at)",
                row,
            )
    workflow.created_by_user_id = user_id
    return workflow


def load(workflow_id: str) -> Optional[Workflow]:
    with database.get_connection() as conn:
        row = conn.execute("SELECT * FROM workflows WHERE id = ?", (workflow_id,)).fetchone()
        if not row:
            return None
        step_rows = conn.execute(
            "SELECT * FROM workflow_steps WHERE workflow_id = ? ORDER BY seq", (workflow_id,)
        ).fetchall()
    item = dict(row)
    workflow = Workflow(
        id=item["id"],
        name=item["name"],
        steps=[],
        status=WorkflowStatus(item["status"]),
        context=_json(item.get("context"), {}),
        created_by_user_id=item.get("created_by_user_id"),
        organization_id=item.get("organization_id"),
        error=item.get("error"),
        created_at=_timestamp(item.get("created_at")),
        completed_at=_timestamp(item.get("completed_at")) if item.get("completed_at") else None,
    )
    workflow.steps = [_step_from_row(dict(step)) for step in step_rows]
    return workflow


def save_workflow(workflow: Workflow) -> None:
    with database.transaction() as conn:
        conn.execute(
            "UPDATE workflows SET status = ?, context = ?, error = ?, updated_at = ?, "
            "completed_at = ? WHERE id = ?",
            (workflow.status.value, json.dumps(workflow.context, default=str),
             workflow.error, _now(),
             _now() if workflow.completed_at else None, workflow.id),
        )


def save_step(workflow_id: str, step: WorkflowStep) -> None:
    with database.transaction() as conn:
        conn.execute(
            "UPDATE workflow_steps SET status = ?, attempts = ?, result = ?, error = ?, "
            "started_at = ?, completed_at = ? WHERE workflow_id = ? AND id = ?",
            (step.status, step.attempts,
             json.dumps(step.result, default=str) if step.result is not None else None,
             step.error, step.started_at, step.completed_at, workflow_id, step.id),
        )


def reset_running(workflow_id: str) -> None:
    with database.transaction() as conn:
        conn.execute(
            "UPDATE workflow_steps SET status = 'pending', started_at = NULL "
            "WHERE workflow_id = ? AND status = 'running'",
            (workflow_id,),
        )


def list_workflows(user_id: Optional[int], is_admin: bool = False, limit: int = 100,
                   organization_id: Optional[str] = None) -> List[Dict[str, Any]]:
    with database.get_connection() as conn:
        if is_admin:
            rows = conn.execute(
                "SELECT * FROM workflows ORDER BY created_at DESC LIMIT ?", (limit,)
            ).fetchall()
        elif organization_id:
            rows = conn.execute(
                "SELECT * FROM workflows WHERE organization_id = ? "
                "ORDER BY created_at DESC LIMIT ?", (organization_id, limit)
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM workflows WHERE created_by_user_id = ? AND organization_id IS NULL "
                "ORDER BY created_at DESC LIMIT ?", (user_id, limit)
            ).fetchall()
    result = []
    for row in rows:
        item = dict(row)
        item["context"] = _json(item.get("context"), {})
        result.append(item)
    return result


def reset_failed(workflow_id: str) -> None:
    with database.transaction() as conn:
        conn.execute(
            "UPDATE workflow_steps SET status = 'pending', attempts = 0, error = NULL, "
            "started_at = NULL, completed_at = NULL WHERE workflow_id = ? AND status = 'failed'",
            (workflow_id,),
        )


def list_active_ids() -> List[str]:
    with database.get_connection() as conn:
        rows = conn.execute(
            "SELECT id FROM workflows WHERE status IN ('pending','running') ORDER BY created_at"
        ).fetchall()
    return [row["id"] for row in rows]


def append_event(workflow_id: str, event_type: str, step_id: Optional[str] = None,
                 data: Optional[Dict[str, Any]] = None) -> None:
    with database.transaction() as conn:
        conn.execute(
            "INSERT INTO workflow_events (id, workflow_id, step_id, event_type, data, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (str(uuid.uuid4()), workflow_id, step_id, event_type,
             json.dumps(data or {}, default=str), _now()),
        )


def list_events(workflow_id: str, limit: int = 1000) -> List[Dict[str, Any]]:
    with database.get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM workflow_events WHERE workflow_id = ? ORDER BY created_at LIMIT ?",
            (workflow_id, limit),
        ).fetchall()
    result = []
    for row in rows:
        item = dict(row)
        item["data"] = _json(item.get("data"), {})
        result.append(item)
    return result


def _timestamp(value: Any) -> float:
    if value is None:
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return datetime.fromisoformat(str(value)).timestamp()
    except ValueError:
        return 0.0
