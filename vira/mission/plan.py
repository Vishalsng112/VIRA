"""Master-agent planning: turn ANY high-level brief into a team of experts + a task graph.

The master decides how many sub-agents are needed and writes each one's persona.
Output from the LLM is validated/repaired here so a small local model can still drive it;
if it keeps failing a generic (domain-agnostic) team is used so a mission never dead-ends.
"""
import re
from typing import Any, Awaitable, Callable, Dict, List

from vira.agent.toolcalls import extract_json

Ask = Callable[..., Awaitable[str]]

PLAN_PROMPT = """### MASTER_PLAN
You are the MASTER AGENT of an autonomous engineering team. A client gave this brief:

BRIEF: {brief}

Design the team that will actually build it. Rules:
1. Pick the SMALLEST team of expert sub-agents that covers the work: between {lo} and {hi} roles. Simple brief = few roles.
2. Roles must come from the brief's domain (e.g. for a Flutter payroll app: Flutter architect, UI engineer, domain/accounting expert, QA). Do not invent filler roles.
3. Include exactly one role that reviews/tests the others' output (key must contain "qa" or "review").
4. Each role needs a persona: who they are, years of experience, speciality, how they communicate.
5. Choose the tech stack and write the architecture/contracts (modules, file layout, data model, interfaces) so experts can work in parallel.
6. Tasks: 4-{max_tasks} concrete tasks, each owned by one role, with `deliverables` = real file paths inside the project (e.g. "lib/main.dart"), and `depends_on` = task ids that must finish first. Independent tasks should NOT depend on each other (they run in parallel).

Reply with ONLY JSON:
{{"project":"short-slug","summary":"2 sentences","stack":"languages/frameworks","architecture":"module list, file layout, key interfaces, data model (max 250 words)",
"roles":[{{"key":"snake_case","title":"Role Title","persona":"2-3 sentences","owns":"what this expert is responsible for"}}],
"tasks":[{{"id":"T1","title":"...","owner":"role key","depends_on":[],"deliverables":["path/file.ext"],"description":"what exactly to build and acceptance criteria"}}]}}"""


def slug(text: str, default: str = "x", n: int = 40) -> str:
    s = re.sub(r"[^a-z0-9]+", "_", str(text).lower()).strip("_")[:n]
    return s or default


def fallback_plan(brief: str, lo: int, hi: int) -> Dict[str, Any]:
    """Domain-agnostic team used when the LLM cannot produce a valid plan."""
    roles = [
        {"key": "architect", "title": "Solution Architect", "owns": "structure, interfaces, tech decisions",
         "persona": "Principal engineer, 15 years delivering software end to end. Decisive, writes concrete interfaces."},
        {"key": "developer", "title": "Lead Developer", "owns": "core implementation",
         "persona": "Senior developer who ships clean, working code. Talks in function signatures and examples."},
        {"key": "domain_expert", "title": "Domain Expert", "owns": "requirements, business rules, sample data",
         "persona": "Practitioner of the client's domain; knows what users expect and which rules are non-negotiable."},
        {"key": "qa_reviewer", "title": "QA & Review Engineer", "owns": "tests, review, integration checks",
         "persona": "Sceptical QA engineer. Reports defects as steps / expected / actual."},
    ][:max(lo, min(hi, 4))]
    keys = [r["key"] for r in roles]
    pick = lambda k: k if k in keys else keys[0]
    tasks = [
        {"id": "T1", "title": "Architecture & requirements", "owner": pick("architect"), "depends_on": [],
         "deliverables": ["docs/ARCHITECTURE.md"], "description": f"Define scope, modules, data model and file layout for: {brief}"},
        {"id": "T2", "title": "Domain rules & sample data", "owner": pick("domain_expert"), "depends_on": [],
         "deliverables": ["docs/REQUIREMENTS.md"], "description": "List the business rules, screens/flows and sample data the product must support."},
        {"id": "T3", "title": "Core implementation", "owner": pick("developer"), "depends_on": ["T1"],
         "deliverables": ["src/main"], "description": "Implement the core of the product following the architecture. Use a real extension for the main file."},
        {"id": "T4", "title": "Tests & review checklist", "owner": pick("qa_reviewer"), "depends_on": ["T1", "T2"],
         "deliverables": ["docs/TEST_PLAN.md"], "description": "Write the test plan and acceptance checks."},
    ]
    return {"project": slug(brief, "project"), "summary": brief[:300], "stack": "to be decided by the architect",
            "architecture": "See docs/ARCHITECTURE.md once written.", "roles": roles, "tasks": tasks, "fallback": True}


def normalise(data: Dict[str, Any], brief: str, lo: int, hi: int, max_tasks: int = 24) -> Dict[str, Any]:
    """Validate + repair a raw plan. Raises ValueError if unusable."""
    if not isinstance(data, dict) or not isinstance(data.get("roles"), list) or not isinstance(data.get("tasks"), list):
        raise ValueError("plan needs 'roles' and 'tasks' lists")
    roles, seen = [], set()
    for r in data["roles"]:
        if not isinstance(r, dict):
            continue
        key = slug(r.get("key") or r.get("title"), "role", 24)
        if key in seen or key in ("master", "human", "all"):
            continue
        seen.add(key)
        roles.append({"key": key, "title": str(r.get("title") or key.replace("_", " ").title())[:50],
                      "persona": str(r.get("persona") or "Senior expert in this area.")[:500],
                      "owns": str(r.get("owns") or "")[:300]})
    if len(roles) < 1:
        raise ValueError("no valid roles")
    roles = roles[:hi]
    keys = [r["key"] for r in roles]
    if len(roles) < lo:                                    # master asked for too few: pad with generic ones
        for extra in fallback_plan(brief, lo, hi)["roles"]:
            if len(roles) >= lo:
                break
            if extra["key"] not in keys:
                roles.append(extra); keys.append(extra["key"])
    if not any("qa" in k or "review" in k or "test" in k for k in keys):
        qa = {"key": "qa_reviewer", "title": "QA & Review Engineer", "owns": "tests, review, integration checks",
              "persona": "Sceptical QA engineer. Reports defects as steps / expected / actual."}
        if len(roles) >= hi:
            roles[-1] = qa                                 # team is full: the reviewer replaces the last role
        else:
            roles.append(qa)
        keys = [r["key"] for r in roles]

    tasks, ids = [], set()
    for i, t in enumerate(data["tasks"][:max_tasks]):
        if not isinstance(t, dict):
            continue
        tid = str(t.get("id") or f"T{i + 1}")[:12]
        if tid in ids:
            tid = f"T{i + 1}x"
        ids.add(tid)
        owner = slug(t.get("owner"), "")
        if owner not in keys:                              # unknown owner -> closest title, else round-robin
            owner = next((r["key"] for r in roles if owner and (owner in r["key"] or r["key"] in owner)), keys[i % len(keys)])
        dels = [str(d).strip().lstrip("/") for d in (t.get("deliverables") or []) if str(d).strip()][:8]
        tasks.append({"id": tid, "title": str(t.get("title") or tid)[:100], "owner": owner,
                      "depends_on": [str(d) for d in (t.get("depends_on") or [])],
                      "deliverables": dels, "description": str(t.get("description") or t.get("title") or "")[:700],
                      "status": "pending", "attempts": 0})
    if not tasks:
        raise ValueError("no valid tasks")
    for t in tasks:                                        # drop unknown / self deps, then break cycles
        t["depends_on"] = [d for d in dict.fromkeys(t["depends_on"]) if d in ids and d != t["id"]]
    done, left = set(), list(tasks)
    while left:
        ready = [t for t in left if all(d in done for d in t["depends_on"])]
        if not ready:                                      # cycle: cut the remaining edges
            for t in left:
                t["depends_on"] = [d for d in t["depends_on"] if d in done]
            ready = left
        for t in ready:
            done.add(t["id"]); left.remove(t)
    return {"project": slug(data.get("project") or brief, "project"), "summary": str(data.get("summary") or brief)[:500],
            "stack": str(data.get("stack") or "")[:300], "architecture": str(data.get("architecture") or "")[:2500],
            "roles": roles, "tasks": tasks}


async def make_plan(ask: Ask, brief: str, lo: int = 3, hi: int = 8, max_tasks: int = 24, tries: int = 2) -> Dict[str, Any]:
    lo = max(1, min(lo, hi))
    prompt = PLAN_PROMPT.format(brief=brief.strip()[:2000], lo=lo, hi=hi, max_tasks=max_tasks)
    last = ""
    for _ in range(tries):
        try:
            raw = await ask(prompt, max_tokens=2500, temperature=0.3)
            return normalise(extract_json(raw) or {}, brief, lo, hi, max_tasks)
        except ValueError as exc:
            last = str(exc)
            prompt += f"\n\nYour previous reply was invalid ({last}). Reply with ONLY the JSON object."
    plan = fallback_plan(brief, lo, hi)
    plan["fallback_reason"] = last
    return normalise(plan, brief, lo, hi, max_tasks) | {"fallback": True, "fallback_reason": last}
