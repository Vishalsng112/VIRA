"""Token/cost accounting and quota enforcement for LLM calls."""
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from vira.auth import database
from vira import errors

# USD per 1M tokens (input, output).  Override with VIRA_LLM_RATES as JSON if
# a deployment has negotiated prices; unknown models count as zero cost.
_DEFAULT_RATES: Dict[str, tuple] = {
    "gpt-4o": (2.5, 10.0),
    "gpt-4o-mini": (0.15, 0.60),
    "gpt-4.1": (2.0, 8.0),
    "o3": (2.0, 8.0),
    "claude-sonnet": (3.0, 15.0),
    "claude-haiku": (0.8, 4.0),
    "claude-opus": (15.0, 75.0),
    "llama": (0.0, 0.0),
    "mistral": (0.0, 0.0),
    "qwen": (0.0, 0.0),
    "default": (0.0, 0.0),
}


class QuotaExceeded(errors.ViraError):
    status_code = 429
    code = "quota_exceeded"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def rates() -> Dict[str, tuple]:
    import json
    import os
    merged = dict(_DEFAULT_RATES)
    raw = os.environ.get("VIRA_LLM_RATES", "")
    if raw:
        try:
            for key, value in json.loads(raw).items():
                if isinstance(value, list) and len(value) == 2:
                    merged[str(key).lower()] = (float(value[0]), float(value[1]))
        except ValueError:
            pass
    return merged


def estimate_cost(model: str, prompt_tokens: int, completion_tokens: int) -> float:
    name = (model or "").lower()
    table = rates()
    selected = table["default"]
    for key, value in table.items():
        if key != "default" and key in name:
            selected = value
            break
    return round(
        (prompt_tokens / 1_000_000) * selected[0]
        + (completion_tokens / 1_000_000) * selected[1],
        6,
    )


def record(user_id: Optional[int], agent_id: Optional[str], provider: str, model: str,
           prompt_tokens: int, completion_tokens: int, latency_ms: float,
           organization_id: Optional[str] = None) -> Dict[str, Any]:
    total = int(prompt_tokens or 0) + int(completion_tokens or 0)
    item = {
        "id": str(uuid.uuid4()),
        "user_id": user_id,
        "organization_id": organization_id,
        "agent_id": agent_id,
        "provider": provider or "unknown",
        "model": model or "unknown",
        "prompt_tokens": int(prompt_tokens or 0),
        "completion_tokens": int(completion_tokens or 0),
        "total_tokens": total,
        "cost_usd": estimate_cost(model, prompt_tokens, completion_tokens),
        "latency_ms": round(float(latency_ms or 0), 2),
        "created_at": _now(),
    }
    with database.transaction() as conn:
        conn.execute(
            "INSERT INTO llm_usage (id, user_id, organization_id, agent_id, provider, model, "
            "prompt_tokens, completion_tokens, total_tokens, cost_usd, latency_ms, created_at) "
            "VALUES (:id, :user_id, :organization_id, :agent_id, :provider, :model, "
            ":prompt_tokens, :completion_tokens, :total_tokens, :cost_usd, :latency_ms, "
            ":created_at)",
            item,
        )
    return item


def _period_start(period: str) -> str:
    now = datetime.now(timezone.utc)
    if period == "day":
        start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    else:
        start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    return start.isoformat()


def totals_since(since: str, user_id: Optional[int] = None,
                 organization_id: Optional[str] = None) -> Dict[str, float]:
    clauses = ["created_at >= ?"]
    values: List[Any] = [since]
    if user_id is not None:
        clauses.append("user_id = ?")
        values.append(user_id)
    if organization_id is not None:
        clauses.append("organization_id = ?")
        values.append(organization_id)
    with database.get_connection() as conn:
        row = conn.execute(
            "SELECT COALESCE(SUM(total_tokens),0) AS tokens, "
            "COALESCE(SUM(cost_usd),0) AS cost, COUNT(*) AS calls "
            f"FROM llm_usage WHERE {' AND '.join(clauses)}",
            values,
        ).fetchone()
    return {"tokens": int(row["tokens"]), "cost_usd": round(float(row["cost"]), 6),
            "calls": int(row["calls"])}


def usage_for_quota(scope: str, subject_id: str, period: str) -> Dict[str, float]:
    if scope == "user":
        return totals_since(_period_start(period), user_id=int(subject_id))
    if scope == "org":
        return totals_since(_period_start(period), organization_id=subject_id)
    return totals_since(_period_start(period))


def list_quotas() -> List[Dict[str, Any]]:
    with database.get_connection() as conn:
        rows = conn.execute("SELECT * FROM llm_quotas ORDER BY scope, subject_id").fetchall()
    return [dict(row) for row in rows]


def get_quota(scope: str, subject_id: str, period: str) -> Optional[Dict[str, Any]]:
    with database.get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM llm_quotas WHERE scope = ? AND subject_id = ? AND period = ?",
            (scope, subject_id, period),
        ).fetchone()
    return dict(row) if row else None


def set_quota(scope: str, subject_id: str, period: str, token_limit: Optional[int] = None,
              cost_limit_usd: Optional[float] = None) -> Dict[str, Any]:
    if scope not in ("user", "org", "global"):
        raise errors.ValidationFailed("scope must be user, org or global")
    if period not in ("day", "month"):
        raise errors.ValidationFailed("period must be day or month")
    now = _now()
    with database.transaction() as conn:
        row = conn.execute(
            "SELECT id FROM llm_quotas WHERE scope = ? AND subject_id = ? AND period = ?",
            (scope, subject_id, period),
        ).fetchone()
        if row:
            conn.execute(
                "UPDATE llm_quotas SET token_limit = ?, cost_limit_usd = ?, updated_at = ? WHERE id = ?",
                (token_limit, cost_limit_usd, now, row["id"]),
            )
        else:
            conn.execute(
                "INSERT INTO llm_quotas (id, scope, subject_id, period, token_limit, "
                "cost_limit_usd, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (str(uuid.uuid4()), scope, subject_id, period, token_limit, cost_limit_usd, now, now),
            )
    return get_quota(scope, subject_id, period)


def delete_quota(quota_id: str) -> bool:
    with database.transaction() as conn:
        cur = conn.execute("DELETE FROM llm_quotas WHERE id = ?", (quota_id,))
        return bool(cur.rowcount)


def check_quota(user_id: Optional[int], organization_id: Optional[str] = None) -> None:
    if user_id is None:
        return
    for quota in list_quotas():
        if quota["scope"] == "user" and str(user_id) != str(quota["subject_id"]):
            continue
        if quota["scope"] == "org" and str(organization_id or "") != str(quota["subject_id"]):
            continue
        usage = usage_for_quota(quota["scope"], str(quota["subject_id"]), quota["period"])
        token_limit = quota.get("token_limit")
        cost_limit = quota.get("cost_limit_usd")
        if token_limit is not None and usage["tokens"] >= int(token_limit):
            raise QuotaExceeded(
                f"Token quota exceeded for {quota['scope']} ({quota['period']})"
            )
        if cost_limit is not None and usage["cost_usd"] >= float(cost_limit):
            raise QuotaExceeded(
                f"Cost quota exceeded for {quota['scope']} ({quota['period']})"
            )


def resource_usage(user_id: Optional[int], days: int = 30,
                   organization_id: Optional[str] = None,
                   is_admin: bool = False) -> Dict[str, Any]:
    """Storage bytes and device-event counts for the same dashboard scope."""
    since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    with database.get_connection() as conn:
        if is_admin:
            storage = conn.execute(
                "SELECT COUNT(*) AS objects, COALESCE(SUM(size_bytes),0) AS bytes FROM objects"
            ).fetchone()
            events = conn.execute(
                "SELECT COUNT(*) AS events FROM device_events WHERE received_at >= ?", (since,)
            ).fetchone()
        elif organization_id:
            storage = conn.execute(
                "SELECT COUNT(*) AS objects, COALESCE(SUM(size_bytes),0) AS bytes "
                "FROM objects WHERE organization_id = ?", (organization_id,)
            ).fetchone()
            events = conn.execute("SELECT 0 AS events").fetchone()
        else:
            storage = conn.execute(
                "SELECT COUNT(*) AS objects, COALESCE(SUM(size_bytes),0) AS bytes "
                "FROM objects WHERE user_id = ? AND organization_id IS NULL", (user_id,)
            ).fetchone()
            events = conn.execute(
                "SELECT COUNT(*) AS events FROM device_events e JOIN user_device_access a "
                "ON a.device_id = e.device_id WHERE a.user_id = ? AND a.status = 'active' "
                "AND e.received_at >= ?", (user_id, since)
            ).fetchone()
    return {
        "storage": {"objects": int(storage["objects"]), "bytes": int(storage["bytes"])},
        "device_events": int(events["events"]),
    }


def summary(user_id: Optional[int], days: int = 30,
            organization_id: Optional[str] = None, is_admin: bool = False) -> Dict[str, Any]:
    days = min(max(int(days), 1), 365)
    since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    clauses = ["created_at >= ?"]
    values: List[Any] = [since]
    if not is_admin:
        if organization_id:
            clauses.append("organization_id = ?")
            values.append(organization_id)
        else:
            clauses.append("user_id = ? AND organization_id IS NULL")
            values.append(user_id)
    where = " AND ".join(clauses)
    with database.get_connection() as conn:
        daily = conn.execute(
            "SELECT substr(created_at,1,10) AS day, "
            "SUM(total_tokens) AS tokens, SUM(cost_usd) AS cost, COUNT(*) AS calls "
            f"FROM llm_usage WHERE {where} GROUP BY day ORDER BY day",
            values,
        ).fetchall()
        models = conn.execute(
            "SELECT model, SUM(total_tokens) AS tokens, SUM(cost_usd) AS cost, "
            f"COUNT(*) AS calls FROM llm_usage WHERE {where} GROUP BY model "
            "ORDER BY tokens DESC LIMIT 20",
            values,
        ).fetchall()
        agents = conn.execute(
            "SELECT COALESCE(agent_id,'main') AS agent_id, SUM(total_tokens) AS tokens, "
            f"SUM(cost_usd) AS cost, COUNT(*) AS calls FROM llm_usage WHERE {where} "
            "GROUP BY agent_id ORDER BY tokens DESC LIMIT 20",
            values,
        ).fetchall()
    totals = totals_since(since, None if is_admin else user_id,
                          organization_id if not is_admin and organization_id else None)
    return {
        "days": days,
        "totals": totals,
        "daily": [dict(row) for row in daily],
        "models": [dict(row) for row in models],
        "agents": [dict(row) for row in agents],
        **resource_usage(user_id, days, organization_id, is_admin),
    }
