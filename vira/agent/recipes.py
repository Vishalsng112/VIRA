"""Machine-readable catalog of the recommended daily-use agents.

The catalog is onboarding metadata: clients can show what is available and what
each agent needs before a schedule is created. Agent implementations land in the
order defined by ``docs/dev/roadmap/agents.md``.
"""
from typing import Any, Dict, List

RECOMMENDED_AGENTS: List[Dict[str, Any]] = [
    {
        "id": "morning-brief",
        "name": "Morning Brief",
        "pitch": "Open VIRA with your coffee. It already knows what matters today.",
        "status": "implemented",
        "agent_id": "morning-brief",
        "daily_trigger": "morning",
        "architecture": "single",
        "schedule_modes": [],
        "default_mode": None,
        "required_tools": ["insights", "user_context", "knowledge_search", "rag_search"],
        "default_schedule": {
            "schedule_type": "daily",
            "time_of_day": "07:30",
            "timezone": "UTC",
        },
        "outputs": ["today's priorities", "device/fleet health", "focus context"],
        "why_users_return": "It becomes the first screen of the day.",
    },
    {
        "id": "focus-coach",
        "name": "Focus & Wellbeing Coach",
        "pitch": "Your agent sees your actual screen time and focus signals — privately.",
        "status": "implemented",
        "agent_id": "focus-coach",
        "daily_trigger": "morning, mid-day, evening",
        "architecture": "single",
        "schedule_modes": ["morning", "checkin", "evening", "weekly"],
        "default_mode": "evening",
        "required_tools": ["insights", "user_context"],
        "default_schedule": {
            "schedule_type": "daily",
            "time_of_day": "18:30",
            "timezone": "UTC",
            "input": {"mode": "evening"},
        },
        "outputs": ["focus plan", "break suggestions", "weekly report"],
        "why_users_return": "Daily coaching from data cloud assistants cannot see.",
    },
    {
        "id": "second-brain",
        "name": "Second Brain",
        "pitch": "Tell VIRA once. It remembers — locally, with your permission.",
        "status": "implemented",
        "agent_id": "second-brain",
        "daily_trigger": "on capture; weekly consolidation",
        "architecture": "single",
        "schedule_modes": ["ask", "consolidate"],
        "default_mode": "consolidate",
        "required_tools": ["knowledge_search", "knowledge_write", "rag_search"],
        "default_schedule": {
            "schedule_type": "weekly",
            "weekday": 6,
            "time_of_day": "19:00",
            "timezone": "UTC",
            "input": {"mode": "consolidate"},
        },
        "outputs": ["capture", "retrieval", "stale/duplicate report"],
        "why_users_return": "The assistant compounds in value every week.",
    },
    {
        "id": "chief-of-staff",
        "name": "Chief of Staff",
        "pitch": "Your agent triages the day and drafts replies — you approve what sends.",
        "status": "implemented",
        "agent_id": "chief-of-staff",
        "daily_trigger": "morning and evening",
        "architecture": "centralized",
        "schedule_modes": ["morning", "evening"],
        "default_mode": "morning",
        "required_tools": ["mcp email", "mcp calendar", "mcp tasks"],
        "default_schedule": {
            "schedule_type": "daily",
            "time_of_day": "08:00",
            "timezone": "UTC",
            "input": {"mode": "morning"},
        },
        "outputs": ["triage summary", "draft replies", "action items"],
        "why_users_return": "It saves time every day, with approval control.",
    },
    {
        "id": "household",
        "name": "Household & Life Admin",
        "pitch": "The family operations agent that lives on your own server.",
        "status": "implemented",
        "agent_id": "household",
        "daily_trigger": "morning and evening; weekly review",
        "architecture": "single",
        "schedule_modes": ["morning", "evening", "weekly"],
        "default_mode": "morning",
        "required_tools": ["family household store"],
        "default_schedule": {
            "schedule_type": "daily",
            "time_of_day": "07:00",
            "timezone": "UTC",
            "input": {"mode": "morning"},
        },
        "outputs": ["meal plan", "chores/bills", "weekly household review"],
        "why_users_return": "Shared household admin brings multiple users onto one server.",
    },
]


def list_recommended() -> List[Dict[str, Any]]:
    return [dict(item) for item in RECOMMENDED_AGENTS]


def get_recommended(agent_id: str) -> Dict[str, Any] | None:
    for item in RECOMMENDED_AGENTS:
        if item["id"] == agent_id:
            return dict(item)
    return None
