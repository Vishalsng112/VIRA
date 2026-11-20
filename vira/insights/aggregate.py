"""Pure aggregation for device insight events.

The client sends interval aggregates; this module turns a window of events into
a compact summary that the UI and future LLM agents can consume without reading
raw payloads again.
"""
from collections import Counter, defaultdict
from typing import Any, Dict, Iterable, List, Optional


def _ms(value: Any) -> int:
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return 0


def aggregate_events(events: Iterable[Dict[str, Any]], days: int) -> Dict[str, Any]:
    app_ms: Dict[str, int] = defaultdict(int)
    app_labels: Dict[str, str] = {}
    app_categories: Dict[str, str] = {}
    categories: Dict[str, int] = defaultdict(int)
    daily: Dict[str, Dict[str, int]] = defaultdict(lambda: {
        "app_ms": 0, "screen_ms": 0, "unlocks": 0, "focus_ms": 0,
        "distraction_ms": 0, "focus_sessions": 0,
    })
    totals = {
        "app_ms": 0, "screen_ms": 0, "unlocks": 0, "interactions": 0,
        "focus_ms": 0, "distraction_ms": 0,
    }
    focus_session_count = completed_sessions = 0
    focus_session_seconds = 0
    focus_scores: List[int] = []
    latest_battery: Optional[Dict[str, Any]] = None
    latest_health: Optional[Dict[str, Any]] = None
    latest_focus_state: Optional[str] = None
    health_warnings: List[str] = []

    for event in events:
        event_type = str(event.get("event_type", ""))
        payload = event.get("payload")
        if not isinstance(payload, dict):
            continue
        day = str(event.get("occurred_at", ""))[:10]
        if event_type == "device.app.usage":
            total = _ms(payload.get("total_foreground_ms"))
            totals["app_ms"] += total
            daily[day]["app_ms"] += total
            for item in payload.get("apps", []):
                if not isinstance(item, dict):
                    continue
                package = str(item.get("package", "unknown"))
                ms = _ms(item.get("foreground_ms"))
                category = str(item.get("category", "other"))
                app_ms[package] += ms
                app_labels[package] = str(item.get("label", package))
                app_categories[package] = category
                categories[category] += ms
            for category, ms in (payload.get("categories") or {}).items():
                if not categories.get(str(category)):
                    categories[str(category)] += _ms(ms)
        elif event_type == "device.session.state":
            screen = _ms(payload.get("interactive_ms"))
            unlocks = _ms(payload.get("unlocks"))
            interactions = _ms(payload.get("interactions"))
            totals["screen_ms"] += screen
            totals["unlocks"] += unlocks
            totals["interactions"] += interactions
            daily[day]["screen_ms"] += screen
            daily[day]["unlocks"] += unlocks
        elif event_type == "device.focus.state":
            focus = _ms(payload.get("focus_ms"))
            distraction = _ms(payload.get("distraction_ms"))
            totals["focus_ms"] += focus
            totals["distraction_ms"] += distraction
            daily[day]["focus_ms"] += focus
            daily[day]["distraction_ms"] += distraction
            latest_focus_state = str(payload.get("state") or latest_focus_state or "")
            score = payload.get("focus_score")
            if isinstance(score, (int, float)):
                focus_scores.append(int(score))
        elif event_type == "device.focus.session":
            focus_session_count += 1
            daily[day]["focus_sessions"] += 1
            seconds = _ms(payload.get("duration_seconds"))
            focus_session_seconds += seconds
            if payload.get("completed") is True:
                completed_sessions += 1
        elif event_type == "device.battery.state":
            latest_battery = dict(payload)
        elif event_type == "device.health.state":
            latest_health = dict(payload)
            for warning in payload.get("warnings", []) or []:
                text = str(warning)
                if text and text not in health_warnings:
                    health_warnings.append(text)

    top_apps = [
        {
            "package": package,
            "label": app_labels.get(package, package),
            "category": app_categories.get(package, "other"),
            "foreground_ms": ms,
        }
        for package, ms in sorted(app_ms.items(), key=lambda item: item[1], reverse=True)[:20]
    ]
    daily_list = [
        {"date": day, **values}
        for day, values in sorted(daily.items(), key=lambda item: item[0])
    ]
    total_focus = totals["focus_ms"] + totals["distraction_ms"]
    focus_score = (
        round(totals["focus_ms"] / total_focus * 100)
        if total_focus else 0
    )
    display_categories = [
        {"category": category, "foreground_ms": ms}
        for category, ms in sorted(categories.items(), key=lambda item: item[1], reverse=True)
    ]
    summary = _summary_text(days, totals, top_apps, focus_session_count, completed_sessions,
                            focus_session_seconds, health_warnings)
    return {
        "days": days,
        "totals": {
            **totals,
            "focus_sessions": focus_session_count,
            "completed_focus_sessions": completed_sessions,
            "focus_session_seconds": focus_session_seconds,
            "focus_score": focus_score,
        },
        "top_apps": top_apps,
        "categories": display_categories,
        "daily": daily_list,
        "focus": {
            "state": latest_focus_state,
            "score": focus_score,
            "average_score": round(sum(focus_scores) / len(focus_scores)) if focus_scores else 0,
        },
        "battery": latest_battery,
        "health": {
            **(latest_health or {}),
            "warnings": health_warnings,
        },
        "summary": summary,
    }


def _summary_text(days: int, totals: Dict[str, int], top_apps: List[Dict[str, Any]],
                  sessions: int, completed: int, seconds: int,
                  warnings: List[str]) -> str:
    screen_min = totals["screen_ms"] // 60000
    app_min = totals["app_ms"] // 60000
    top = top_apps[0]["label"] if top_apps else "no app data"
    parts = [
        f"Last {days} day(s): screen time {screen_min} min, app time {app_min} min.",
        f"Top app: {top}.",
        f"Focus: {sessions} session(s), {completed} completed, {seconds // 60} min total.",
        f"Unlocks: {totals['unlocks']}.",
    ]
    if warnings:
        parts.append("Device warnings: " + "; ".join(warnings[:3]) + ".")
    return " ".join(parts)
