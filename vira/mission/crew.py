"""Mission runtime: a Master agent plans a team of expert sub-agents, they talk to each other
and write the product into a sandboxed workspace.  Works for any brief.

    brief -> Master (plan: roles+personas+tasks) -> N CrewAgents run concurrently
          -> agents exchange tagged messages, share decisions, write files
          -> Master reviews (auto checks + LLM), assigns fix tasks, writes README + report

Everything observable goes through a per-mission ``SwarmHub`` (events, agent cards, SSE),
the same hub class the existing /swarm dashboard uses.
"""
import asyncio
import json
import re
import time
import uuid
from collections import deque
from pathlib import Path
from typing import Any, Callable, Deque, Dict, List, Optional

from loguru import logger

from vira.agent.toolcalls import extract_json
from vira.swarm.hub import SwarmHub

from .plan import make_plan
from .workspace import Workspace, WorkspaceError

TERMINAL = {"done", "partial", "failed"}
ACTIONABLE = {"QUESTION", "REVIEW", "BLOCKER", "REQUEST"}
_TAG = re.compile(r"^\s*\[([A-Z]+)\]")

DEFAULTS: Dict[str, Any] = {
    "data_dir": "data/missions", "model": None, "min_agents": 3, "max_agents": 8, "max_tasks": 24,
    "review_rounds": 1, "llm_concurrency": 1, "max_llm_calls": 120, "max_tokens": 4096,
    "temperature": 0.4, "call_timeout": 240, "max_replies": 8, "max_attempts": 2,
    "ctx_chars": 12000, "max_minutes": 90, "allow_parallel_missions": False,
}

COMM = ("COMMUNICATION: plain professional English, no roleplay, greetings or small talk. Max ~100 words per message. "
        "Start each message with ONE tag: [PROPOSAL] [QUESTION] [DECISION] [BLOCKER] [REVIEW] [REQUEST] [DONE]. "
        "Be concrete (signatures, schemas, paths). Address people by role key. Do not repeat what others said. "
        "Ask a question only if you cannot proceed with a sensible default - state the default you will use.")

OUTPUT_FORMAT = """OUTPUT FORMAT - use exactly these tags, nothing outside them:
<message to="role_key or all">[TAG] short note</message>      (0-2 messages)
<file path="relative/path.ext">
COMPLETE file content, no markdown fences
</file>                                                          (one block per file, always the whole file; keep each file under ~250 lines)
<note>one durable fact or decision worth remembering</note>     (optional)
<status>done</status>   or   <status>blocked: reason</status>"""

_FILE = re.compile(r"<file\s+path\s*=\s*[\"']([^\"']+)[\"']\s*>\r?\n?(.*?)</file\s*>", re.S | re.I)
_OPEN = re.compile(r"<file\s+path\s*=\s*[\"']([^\"']+)[\"']\s*>\r?\n?", re.I)
_MSG = re.compile(r"<message(?:\s+to\s*=\s*[\"']([^\"']*)[\"'])?\s*>(.*?)</message\s*>", re.S | re.I)
_NOTE = re.compile(r"<note>(.*?)</note>", re.S | re.I)
_STATUS = re.compile(r"<status>(.*?)</status>", re.S | re.I)


class Halted(Exception):
    """Mission stopped (budget, timeout or user)."""


class BudgetExceeded(Halted):
    pass


def _unfence(content: str) -> str:
    s = content.strip("\n")
    m = re.match(r"^```[\w+.-]*\n(.*?)\n?```\s*$", s, re.S)
    return m.group(1) if m else s


def parse_output(text: str) -> Dict[str, Any]:
    """Tolerant parser for the tag protocol (handles fences, missing </file> from cut-off output)."""
    files, end = [], 0
    for m in _FILE.finditer(text):
        files.append({"path": m.group(1).strip(), "content": _unfence(m.group(2)), "truncated": False})
        end = m.end()
    body = _FILE.sub("", text)
    tail = text[end:]
    o = _OPEN.search(tail)
    if o:                                                   # last file never closed -> output was cut off
        files.append({"path": o.group(1).strip(), "content": _unfence(tail[o.end():]), "truncated": True})
        body = body[:body.rfind("<file")] if "<file" in body else body
    st = _STATUS.findall(body)
    return {"files": files, "messages": [((to or "all").strip(), b.strip()) for to, b in _MSG.findall(body) if b.strip()],
            "notes": [n.strip() for n in _NOTE.findall(body) if n.strip()],
            "status": (st[-1].strip().lower() if st else "done")}


# --------------------------------------------------------------------------- agent
class CrewAgent:
    """One expert. Pulls ready tasks it owns, answers peers, writes files, keeps notes."""

    def __init__(self, mission: "Mission", key: str, title: str, persona: str, owns: str, is_master: bool = False):
        self.m, self.key, self.title, self.persona, self.owns, self.is_master = mission, key, title, persona, owns, is_master
        self.inbox: Deque[Dict[str, Any]] = deque(maxlen=12)
        self.recent: Deque[Dict[str, Any]] = deque(maxlen=8)
        self.notes: List[str] = []
        self.activity = "starting"
        self.wake = asyncio.Event()
        self.sent = self.received = self.replies = self.files_written = self.errors = 0
        self.tasks_done = 0
        self.current: Optional[str] = None

    # -- intake
    def receive(self, msg: Dict[str, Any]) -> None:
        self.received += 1
        self.recent.append(msg)
        if msg.get("actionable"):
            self.inbox.append(msg)
            self.wake.set()

    def set_activity(self, text: str) -> None:
        self.activity = text
        self.snapshot()

    def add_note(self, note: str) -> None:
        note = note.strip()[:240]
        if len(note) > 8 and note not in self.notes:
            self.notes = (self.notes + [note])[-12:]
            self.m.hub.emit("learn", self.key, self.title, fact=note, source="self")

    def snapshot(self) -> None:
        own = [t for t in self.m.tasks.values() if t["owner"] == self.key]
        self.m.hub.update_agent(self.key, {
            "id": self.key, "name": self.title, "key": self.key, "title": self.title, "persona": self.persona,
            "owns": self.owns, "is_master": self.is_master, "alive": not self.m.finished.is_set(),
            "activity": self.activity, "current": self.current, "tasks_total": len(own),
            "tasks_done": sum(1 for t in own if t["status"] in TERMINAL), "files": self.files_written,
            "notes": self.notes, "knowledge_count": len(self.notes), "generation": self.tasks_done,
            "sent": self.sent, "received": self.received, "replies": self.replies, "errors": self.errors})

    # -- prompts
    def _head(self) -> str:
        p, m = self.m.plan, self.m
        return (f"You are {self.title} (role key: {self.key}). {self.persona}\nYou own: {self.owns or 'your specialty'}\n"
                f"PROJECT: {p['summary']}\nSTACK: {p['stack']}\nARCHITECTURE & CONTRACTS:\n{p['architecture']}\n"
                f"TEAM:\n{m.roster()}\nSHARED DECISIONS:\n{m.decisions_text()}\n"
                f"YOUR NOTES:\n{chr(10).join('- ' + n for n in self.notes) or '(none)'}\n"
                f"PROJECT FILES NOW:\n{m.ws.tree_text()}\n"
                f"RECENT TEAM MESSAGES:\n{m.format_msgs(self.recent)}\n{COMM}\n")

    def _inbox_text(self) -> str:
        return self.m.format_msgs(self.inbox) if self.inbox else "(none)"

    def _ctx_files(self, t: Dict[str, Any]) -> str:
        m, paths = self.m, []
        for d in t["depends_on"]:
            paths += m.tasks.get(d, {}).get("files", [])
        paths += [p for p in t["deliverables"] if m.ws.exists(p)] + t.get("files", [])
        budget, out = m.cfg["ctx_chars"], []
        for pth in dict.fromkeys(paths):
            if budget <= 0:
                break
            try:
                txt = m.ws.read(pth, limit=min(4000, budget))
            except WorkspaceError:
                continue
            out.append(f"--- {pth} ---\n{txt}")
            budget -= len(txt)
        return "\n".join(out) or "(no existing files relevant to this task)"

    def _work_prompt(self, t: Dict[str, Any]) -> str:
        return (f"### WORK_TASK\n{self._head()}\nRELEVANT FILES:\n{self._ctx_files(t)}\n\nMESSAGES TO YOU:\n{self._inbox_text()}\n\n"
                f"ROLE_KEY: {self.key}\nTASK_ID: {t['id']}\nTASK: {t['title']}\nDESCRIPTION: {t['description']}\n"
                f"DELIVERABLES: {', '.join(t['deliverables']) or '(decide sensible paths)'}\n"
                + (f"FIX THIS FROM YOUR PREVIOUS ATTEMPT: {t['hint']}\n" if t.get("hint") else "")
                + "Build it now. Write complete, working files that follow the architecture and decisions exactly. "
                  "If you must deviate, post a [DECISION] message first.\n" + OUTPUT_FORMAT)

    # -- actions
    def _apply(self, text: str, task: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        out = parse_output(text)
        written, problems = [], []
        for f in out["files"]:
            try:
                info = self.m.ws.write(f["path"], f["content"], self.key)
            except WorkspaceError as exc:
                problems.append(f"{f['path']}: {exc}")
                continue
            if f["truncated"]:
                info["check"] = (info["check"] + " output was cut off").strip()
            written.append(info)
            self.files_written += 1
            if task is not None and info["path"] not in task.setdefault("files", []):
                task["files"].append(info["path"])
            self.m.hub.emit("file", self.key, self.title, path=info["path"], bytes=info["bytes"], lines=info["lines"],
                            version=info["version"], check=info["check"], task=(task or {}).get("id"))
        for to, body in out["messages"][:2]:
            self.m.send(self, to, body)
        for n in out["notes"][:2]:
            self.add_note(n)
        return {"written": written, "problems": problems, "status": out["status"],
                "truncated": any(f["truncated"] for f in out["files"])}

    async def work(self, t: Dict[str, Any]) -> None:
        m = self.m
        self.current = t["id"]                              # claim() already marked it running
        self.set_activity(f"{t['id']}: {t['title']}")
        res = self._apply(await m.ask(self._work_prompt(t)), t)
        self.inbox.clear()
        problems = list(res["problems"])
        if res["truncated"]:
            problems.append("your output was cut off - split the work into smaller files and finish every file")
        if not res["written"]:
            problems.append("you produced no <file> blocks; deliver the deliverables as <file path=...> blocks")
        if res["status"].startswith("blocked"):
            problems.append(res["status"])
            m.send(self, "master", f"[BLOCKER] {t['id']}: {res['status'][8:].strip() or 'blocked'}")
        problems += [f"{w['path']}: {w['check']}" for w in res["written"] if w["check"]]
        t["attempts"] += 1
        if not problems:
            m.set_task(t, "done")
            self.tasks_done += 1
            names = ", ".join(t.get("files", [])[:6]) or "no files"
            m.send(self, "all", f"[DONE] {t['id']} {t['title']} -> {names}", system=True)
        elif t["attempts"] < m.cfg["max_attempts"]:
            t["hint"] = "; ".join(problems)[:500]
            m.set_task(t, "pending", note="retry: " + t["hint"])
        else:
            m.set_task(t, "partial" if t.get("files") else "failed", note="; ".join(problems)[:300])
            self.tasks_done += 1 if t.get("files") else 0
        self.current = None
        m.wake_all()
        self.snapshot()

    async def reply(self) -> None:
        m = self.m
        self.set_activity("replying to team")
        prompt = (f"### REPLY\n{self._head()}\nMESSAGES TO YOU:\n{self._inbox_text()}\n\nROLE_KEY: {self.key}\n"
                  "Answer concisely and concretely. If the answer changes a contract, post a [DECISION] message. "
                  "If a file must change, output the COMPLETE updated file. If nothing is needed reply <status>done</status>.\n"
                  + OUTPUT_FORMAT)
        self.inbox.clear()
        self.replies += 1
        self._apply(await m.ask(prompt, max_tokens=min(m.cfg["max_tokens"], 2048)))
        self.snapshot()

    async def run(self) -> None:
        m = self.m
        self.set_activity("ready")
        while not m.finished.is_set():
            try:
                t = None if self.is_master else m.claim(self.key)
                if t:
                    await self.work(t)
                    continue
                if self.inbox:
                    if self.replies < m.cfg["max_replies"]:
                        await self.reply()
                        continue
                    self.inbox.clear()
                self.set_activity("idle" if not self.is_master else "coordinating")
                self.wake.clear()
                try:
                    await asyncio.wait_for(self.wake.wait(), timeout=2)
                except asyncio.TimeoutError:
                    pass
            except asyncio.CancelledError:
                raise
            except Halted as exc:
                m.halt("budget_exhausted" if isinstance(exc, BudgetExceeded) else "stopped")
                break
            except Exception as exc:                        # one bad LLM turn must not kill the agent
                self.errors += 1
                logger.warning("[mission] {} failed: {}", self.key, exc)
                m.hub.emit("error", self.key, self.title, error=str(exc)[:200])
                if self.current:                            # give the task back so it is retried or marked failed
                    t = m.tasks[self.current]
                    t["attempts"] += 1
                    m.set_task(t, "pending" if t["attempts"] < m.cfg["max_attempts"] else "failed", note=str(exc)[:200])
                    self.current = None
                await asyncio.sleep(1 + min(self.errors, 5))
        self.set_activity("finished")


# --------------------------------------------------------------------------- mission
class Mission:
    def __init__(self, brief: str, ask: Callable[..., Any], root: str = "data/missions",
                 cfg: Optional[Dict[str, Any]] = None, mid: Optional[str] = None):
        self.cfg = {**DEFAULTS, **(cfg or {})}
        self.id = mid or time.strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:4]
        self.brief = brief.strip()
        self.dir = Path(root) / self.id
        self.ws = Workspace(self.dir / "project")
        self.hub = SwarmHub(data_dir=str(self.dir / "meta"), max_events=5000)
        self.hub.configure(llm_concurrency=self.cfg["llm_concurrency"], data_dir=str(self.dir / "meta"))
        self._raw_ask = ask
        self.status = self.phase = "created"
        self.plan: Dict[str, Any] = {"summary": "", "stack": "", "architecture": "", "roles": [], "tasks": []}
        self.tasks: Dict[str, Dict[str, Any]] = {}
        self.agents: Dict[str, CrewAgent] = {}
        self.decisions: List[Dict[str, str]] = []
        self.calls = 0
        self.error = ""
        self.halt_reason = ""
        self.started = self.ended = 0.0
        self.finished = asyncio.Event()
        self._main: Optional[asyncio.Task] = None
        self._bg: List[asyncio.Task] = []

    # -- LLM with budget + shared concurrency
    async def ask(self, prompt: str, **kw) -> str:
        if self.calls >= self.cfg["max_llm_calls"]:
            raise BudgetExceeded(f"LLM call budget ({self.cfg['max_llm_calls']}) used up")
        kw.setdefault("max_tokens", self.cfg["max_tokens"])
        kw.setdefault("temperature", self.cfg["temperature"])
        async with self.hub.llm_slot:
            if self.finished.is_set():
                raise Halted("mission finished")
            self.calls += 1
            last: Optional[Exception] = None
            for attempt in range(2):
                try:
                    return await asyncio.wait_for(self._raw_ask(prompt, **kw), timeout=self.cfg["call_timeout"])
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    last = exc
                    await asyncio.sleep(1 + attempt)
            raise last or RuntimeError("LLM failed")

    # -- bus
    def resolve(self, to: str) -> Optional[str]:
        t = (to or "all").strip().lower()
        if t in ("", "all", "everyone", "team", "*"):
            return None
        if t in ("master", "lead", "master agent"):
            return "master"
        for a in self.agents.values():
            if t in (a.key.lower(), a.title.lower()):
                return a.key
        return next((a.key for a in self.agents.values() if t in a.key.lower() or t in a.title.lower()), "?")

    def send(self, sender, to: str, text: str, system: bool = False) -> None:
        """sender: CrewAgent or None (human). Directed [QUESTION]/[REVIEW]/[BLOCKER]/[REQUEST] wake the target."""
        skey, stitle = (sender.key, sender.title) if sender else ("human", "Human")
        text = text.strip()[:1500]
        tag = (_TAG.match(text).group(1) if _TAG.match(text) else "")
        target = self.resolve(to)
        directed = target not in (None, "?")
        msg = {"from": skey, "from_title": stitle, "to": target or "all", "text": text, "tag": tag, "ts": time.time()}
        for a in list(self.agents.values()):
            if a.key == skey or (directed and a.key != target):
                continue
            actionable = (not system) and ((sender is None) or (directed and (tag in ACTIONABLE or skey == "master")))
            a.receive({**msg, "actionable": actionable})
        if sender:
            sender.sent += 1
        if tag == "DECISION":
            self.decisions.append({"by": skey, "text": text})
            del self.decisions[:-40]
        self.hub.emit("message", skey, stitle, to=msg["to"], text=text, tag=tag, system=system)

    def wake_all(self) -> None:
        for a in self.agents.values():
            a.wake.set()

    @staticmethod
    def format_msgs(msgs) -> str:
        return "\n".join(f"{m['from']} -> {m['to']}: {m['text'][:400]}" for m in msgs) or "(none)"

    def roster(self) -> str:
        return "\n".join(f"- {a.key}: {a.title} - {a.owns}" + (" (coordinator)" if a.is_master else "")
                         for a in self.agents.values()) or "(forming)"

    def decisions_text(self, n: int = 10) -> str:
        return "\n".join(f"- {d['by']}: {d['text'][:300]}" for d in self.decisions[-n:]) or "(none yet)"

    # -- tasks
    def claim(self, key: str) -> Optional[Dict[str, Any]]:
        for t in self.tasks.values():
            if t["owner"] == key and t["status"] == "pending" and \
                    all(self.tasks[d]["status"] in TERMINAL for d in t["depends_on"] if d in self.tasks):
                self.set_task(t, "running")
                return t
        return None

    def set_task(self, t: Dict[str, Any], status: str, note: str = "") -> None:
        t["status"] = status
        self.hub.emit("task", t["owner"], self.agents[t["owner"]].title if t["owner"] in self.agents else t["owner"],
                      id=t["id"], title=t["title"], status=status, note=note, attempts=t["attempts"])

    def all_terminal(self) -> bool:
        return all(t["status"] in TERMINAL for t in self.tasks.values())

    async def _wait_tasks(self) -> None:
        while not self.finished.is_set() and not self.all_terminal():
            if time.time() - self.started > self.cfg["max_minutes"] * 60:
                self.halt("timeout")
                break
            await asyncio.sleep(0.4)

    def halt(self, reason: str) -> None:
        if self.finished.is_set():
            return
        if not self.halt_reason:
            self.halt_reason = reason
            self.hub.emit("system", "master", "Master Agent", text=f"mission halted: {reason}")
        self.finished.set()
        self.wake_all()

    # -- master lifecycle
    def _phase(self, phase: str) -> None:
        self.phase = phase
        self.hub.emit("phase", "master", "Master Agent", phase=phase)
        self.save()

    async def run(self) -> None:
        self.started, self.status = time.time(), "running"
        self.hub.emit("system", "master", "Master Agent", text=f"mission {self.id} started: {self.brief[:200]}")
        self._bg = [asyncio.create_task(self._beat())]
        try:
            self._phase("planning")
            master = CrewAgent(self, "master", "Master Agent",
                               "Engineering manager. Plans the team, resolves conflicts, reviews integration, owns delivery.",
                               "plan, coordination, final review", is_master=True)
            self.agents["master"] = master
            self.hub.emit("join", "master", master.title, persona=master.persona, owns=master.owns, tasks=[])
            master.set_activity("planning the team")
            self.plan = await make_plan(self.ask, self.brief, self.cfg["min_agents"], self.cfg["max_agents"], self.cfg["max_tasks"])
            self.tasks = {t["id"]: t for t in self.plan["tasks"]}
            self.hub.emit("plan", "master", "Master Agent", project=self.plan["project"], summary=self.plan["summary"],
                          stack=self.plan["stack"], roles=self.plan["roles"], fallback=bool(self.plan.get("fallback")),
                          tasks=[{k: t[k] for k in ("id", "title", "owner", "depends_on", "deliverables")} for t in self.plan["tasks"]])
            self._phase("staffing")
            for r in self.plan["roles"]:
                a = CrewAgent(self, r["key"], r["title"], r["persona"], r["owns"])
                self.agents[a.key] = a
                self.hub.emit("join", a.key, a.title, persona=a.persona, owns=a.owns,
                              tasks=[t["id"] for t in self.tasks.values() if t["owner"] == a.key])
            self.send(master, "all", f"[DECISION] Project '{self.plan['project']}': {self.plan['summary']} Stack: {self.plan['stack']}. "
                                     "Follow the architecture. Ask the owning role directly; post [DECISION] for contract changes.", system=True)
            self._bg += [asyncio.create_task(a.run(), name=f"mission-{a.key}") for a in self.agents.values()]
            self._phase("building")
            await self._wait_tasks()
            for rnd in range(self.cfg["review_rounds"]):
                if self.finished.is_set():
                    break
                self._phase(f"review {rnd + 1}")
                if not await self._review(rnd):
                    break
                await self._wait_tasks()
            self._phase("finalizing")
            await self._finalize()
            self.status = {"": "done"}.get(self.halt_reason, self.halt_reason)
        except asyncio.CancelledError:
            self.status = "stopped"
        except BudgetExceeded:
            self.status = "budget_exhausted"
            await self._finalize(use_llm=False)
        except Exception as exc:
            logger.exception("[mission] {} failed", self.id)
            self.status, self.error = "failed", str(exc)[:300]
        finally:
            self.ended = time.time()
            self.finished.set()
            self.wake_all()
            for tsk in self._bg:
                tsk.cancel()
            await asyncio.gather(*self._bg, return_exceptions=True)
            for a in self.agents.values():
                a.activity = "finished"
                a.snapshot()
                self.hub.remove_agent(a.key)
            self.phase = self.status
            self.hub.emit("mission_done", "master", "Master Agent", status=self.status, files=len(self.ws.files()),
                          calls=self.calls, error=self.error)
            self.save()

    async def _beat(self) -> None:
        while True:
            for a in list(self.agents.values()):
                a.snapshot()
            await asyncio.sleep(5)

    async def _review(self, rnd: int) -> bool:
        """Auto checks (missing deliverables, syntax) + one LLM integration review -> fix tasks."""
        issues: List[Dict[str, Any]] = []
        files = self.ws.files()
        for t in list(self.tasks.values()):
            for d in t["deliverables"]:
                if not any(f["path"] == d or f["path"].startswith(d) for f in files) and t["owner"] in self.agents:
                    issues.append({"owner": t["owner"], "title": f"Missing deliverable {d}", "files": [d],
                                   "description": f"Deliverable '{d}' of {t['id']} ({t['title']}) does not exist. Create it."})
        for f in files:
            if f["check"]:
                owner = f["author"] if f["author"] in self.agents else next(iter(self.plan["roles"]))["key"]
                issues.append({"owner": owner, "title": f"Fix {f['path']}", "files": [f["path"]],
                               "description": f"{f['path']} has a problem: {f['check']}. Output the corrected complete file."})
        if not self.finished.is_set():
            heads, budget = [], 7000
            for f in files:
                try:
                    h = self.ws.read(f["path"], limit=350)
                except WorkspaceError:
                    continue
                heads.append(f"--- {f['path']} ({f['author']}) ---\n{h}")
                budget -= len(h)
                if budget <= 0:
                    break
            prompt = (f"### REVIEW\nYou are the MASTER AGENT doing the integration review of project '{self.plan['project']}'.\n"
                      f"BRIEF: {self.brief}\nSTACK: {self.plan['stack']}\nARCHITECTURE:\n{self.plan['architecture']}\n"
                      f"TEAM:\n{self.roster()}\nDECISIONS:\n{self.decisions_text(15)}\nFILES:\n{self.ws.tree_text()}\n\n"
                      f"FILE HEADS:\n{chr(10).join(heads)}\n\nFind REAL integration problems only: missing entrypoint, interfaces that "
                      "do not match between files, unmet requirements from the brief, missing run instructions/dependencies. "
                      "Max 4 issues. Reply ONLY JSON: "
                      '{"issues":[{"owner":"role key","title":"...","files":["path"],"description":"exact fix"}]}  or {"issues":[]}')
            try:
                data = extract_json(await self.ask(prompt, max_tokens=1200, temperature=0.2)) or {}
                for it in (data.get("issues") or [])[:4]:
                    if isinstance(it, dict) and it.get("description"):
                        issues.append({"owner": self.resolve(str(it.get("owner", ""))), "title": str(it.get("title") or "Fix")[:80],
                                       "files": [str(x) for x in (it.get("files") or [])][:4], "description": str(it["description"])[:600]})
            except BudgetExceeded:
                raise
            except Exception as exc:
                logger.debug("[mission] review LLM failed: {}", exc)
        issues = issues[:6]
        for i, it in enumerate(issues):
            owner = it["owner"] if it["owner"] in self.agents and it["owner"] != "master" else self.plan["roles"][0]["key"]
            t = {"id": f"F{rnd + 1}-{i + 1}", "title": it["title"], "owner": owner, "depends_on": [], "deliverables": it["files"],
                 "description": it["description"], "status": "pending", "attempts": 0}
            self.tasks[t["id"]] = t
            self.set_task(t, "pending", note="from review")
        self.hub.emit("system", "master", "Master Agent", text=f"review {rnd + 1}: {len(issues)} issue(s) found")
        self.wake_all()
        return bool(issues)

    async def _finalize(self, use_llm: bool = True) -> None:
        if not self.ws.exists("README.md"):
            text = ""
            if use_llm and not self.halt_reason and self.calls < self.cfg["max_llm_calls"]:
                try:
                    text = await self.ask(
                        "### README\nWrite README.md for this project: what it is, setup, how to run, how to test, folder layout. "
                        f"Be accurate to the files that exist.\nBRIEF: {self.brief}\nSTACK: {self.plan['stack']}\n"
                        f"FILES:\n{self.ws.tree_text()}\nReply with the markdown only.", max_tokens=1500, temperature=0.2)
                except Exception:
                    text = ""
            if len(text.strip()) < 40:
                text = (f"# {self.plan.get('project', 'project')}\n\n{self.brief}\n\nStack: {self.plan.get('stack', '')}\n\n"
                        f"## Files\n{self.ws.tree_text()}\n")
            self.ws.write("README.md", _unfence(text), "master")
        self.ws.write("MISSION_REPORT.md", self._report(), "master")

    def _report(self) -> str:
        rows = "\n".join(f"| {t['id']} | {t['title']} | {t['owner']} | {t['status']} |" for t in self.tasks.values())
        team = "\n".join(f"- **{r['title']}** (`{r['key']}`): {r['persona']}" for r in self.plan["roles"])
        dec = "\n".join(f"- {d['by']}: {d['text']}" for d in self.decisions[-25:]) or "- none"
        left = [f"- {f['path']}: {f['check']}" for f in self.ws.files() if f["check"]]
        return (f"# Mission report {self.id}\n\n**Brief:** {self.brief}\n\n**Status:** {self.status or self.halt_reason or 'done'}  \n"
                f"**LLM calls:** {self.calls}/{self.cfg['max_llm_calls']}  \n**Stack:** {self.plan['stack']}\n\n## Team\n{team}\n\n"
                f"## Tasks\n| id | title | owner | status |\n|---|---|---|---|\n{rows}\n\n## Decisions\n{dec}\n\n"
                f"## Open problems\n{chr(10).join(left) or '- none detected by automatic checks'}\n")

    # -- control / views
    async def say(self, text: str, to: str = "all") -> None:
        if self.finished.is_set():
            raise RuntimeError("mission is not running")
        self.send(None, to, text[:800])

    def stop(self) -> None:
        if self._main and not self._main.done():
            self._main.cancel()

    def snapshot(self) -> Dict[str, Any]:
        return {"id": self.id, "brief": self.brief, "status": self.status, "phase": self.phase, "error": self.error,
                "calls": self.calls, "max_calls": self.cfg["max_llm_calls"], "started": self.started, "ended": self.ended,
                "plan": {k: self.plan.get(k) for k in ("project", "summary", "stack", "architecture", "roles", "fallback")},
                "tasks": list(self.tasks.values()), "decisions": self.decisions[-30:], "files": self.ws.files()}

    def save(self) -> None:
        try:
            (self.dir / "meta").mkdir(parents=True, exist_ok=True)
            (self.dir / "meta" / "mission.json").write_text(json.dumps(self.snapshot(), ensure_ascii=False, indent=1), encoding="utf-8")
        except OSError as exc:
            logger.debug("[mission] save failed: {}", exc)


# --------------------------------------------------------------------------- manager
class MissionManager:
    """Creates missions from the config.yaml ``mission:`` section; lists past ones from disk."""

    def __init__(self, config_path: str = "config.yaml", ask_factory: Optional[Callable[[Optional[str]], Callable]] = None,
                 overrides: Optional[Dict[str, Any]] = None):
        self.config_path, self._ask_factory, self._over = config_path, ask_factory, overrides or {}
        self.missions: Dict[str, Mission] = {}

    def config(self) -> Dict[str, Any]:
        cfg = dict(DEFAULTS)
        try:
            import yaml
            cfg.update((yaml.safe_load(Path(self.config_path).read_text(encoding="utf-8")) or {}).get("mission") or {})
        except (OSError, ValueError):
            pass
        cfg.update(self._over)
        return cfg

    def running(self) -> Optional[Mission]:
        return next((m for m in self.missions.values() if not m.finished.is_set() and m._main), None)

    async def start(self, brief: str, **over) -> Mission:
        brief = (brief or "").strip()
        if len(brief) < 8:
            raise ValueError("describe the task in at least a sentence")
        cfg = self.config()
        cfg.update({k: v for k, v in over.items() if v is not None and k in DEFAULTS})
        if not cfg["allow_parallel_missions"] and self.running():
            raise RuntimeError("a mission is already running - stop it or wait")
        if self._ask_factory is None:
            from .llm import make_ask_factory
            self._ask_factory = make_ask_factory(self.config_path)
        m = Mission(brief[:4000], self._ask_factory(cfg.get("model")), root=cfg["data_dir"], cfg=cfg)
        self.missions[m.id] = m
        m._main = asyncio.create_task(m.run(), name=f"mission-{m.id}")
        return m

    def get(self, mid: str) -> Optional[Mission]:
        return self.missions.get(mid)

    def _disk_dirs(self) -> List[Path]:
        root = Path(self.config()["data_dir"])
        return sorted((p for p in root.glob("*/meta/mission.json")), reverse=True) if root.exists() else []

    def list(self) -> List[Dict[str, Any]]:
        out = {m.id: {"id": m.id, "brief": m.brief[:120], "status": m.status, "phase": m.phase, "started": m.started,
                      "files": len(m.ws.files())} for m in self.missions.values()}
        for p in self._disk_dirs():
            mid = p.parent.parent.name
            if mid not in out:
                try:
                    d = json.loads(p.read_text(encoding="utf-8"))
                    out[mid] = {"id": mid, "brief": d.get("brief", "")[:120], "status": d.get("status", "?"), "phase": d.get("phase", ""),
                                "started": d.get("started", 0), "files": len(d.get("files", []))}
                except (OSError, ValueError):
                    pass
        return sorted(out.values(), key=lambda x: x["started"], reverse=True)

    def workspace(self, mid: str) -> Optional[Workspace]:
        if not re.fullmatch(r"[0-9a-zA-Z_-]{6,40}", mid):
            return None
        m = self.missions.get(mid)
        if m:
            return m.ws
        d = Path(self.config()["data_dir"]) / mid / "project"
        return Workspace(d) if d.is_dir() else None

    def saved(self, mid: str) -> Optional[Dict[str, Any]]:
        try:
            return json.loads((Path(self.config()["data_dir"]) / mid / "meta" / "mission.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None


_manager: Optional[MissionManager] = None


def get_manager() -> MissionManager:
    global _manager
    if _manager is None:
        _manager = MissionManager()
    return _manager
