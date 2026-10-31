"""Observation hub for the swarm dashboard.

Agents talk to each other over the real agent message bus; the hub only
*observes*: it keeps a ring buffer of what happened, per-agent snapshots and
trait history, persists events to JSONL and fans them out to SSE clients.
Nothing here is used by agents to learn - it never leaks knowledge between them.
"""
import asyncio
import json
import time
from collections import deque
from pathlib import Path
from typing import Any, Deque, Dict, List, Optional


class SwarmHub:
    def __init__(self, data_dir: str = "data/swarm", max_events: int = 3000):
        self.dir = Path(data_dir)
        self.events: Deque[Dict[str, Any]] = deque(maxlen=max_events)
        self.agents: Dict[str, Dict[str, Any]] = {}
        self.history: Dict[str, List[Dict[str, Any]]] = {}   # per-agent trait/knowledge timeline
        self._seq = 0
        self._subs: List[asyncio.Queue] = []
        self._publisher = None
        self._sem: Optional[asyncio.Semaphore] = None
        self._llm_slots = 1
        self.started = time.time()
        self.persist = True

    # ---- LLM concurrency shared by all agents (a local model is the bottleneck)
    def configure(self, llm_concurrency: int = 1, data_dir: Optional[str] = None) -> None:
        if data_dir:
            self.dir = Path(data_dir)
        if self._sem is None or llm_concurrency != self._llm_slots:
            self._llm_slots = max(1, int(llm_concurrency))
            self._sem = asyncio.Semaphore(self._llm_slots)

    @property
    def llm_slot(self) -> asyncio.Semaphore:
        if self._sem is None:
            self._sem = asyncio.Semaphore(self._llm_slots)
        return self._sem

    def set_publisher(self, fn) -> None:
        """fn(sender_agent_id, event_type, data, target_agent_ids) coroutine."""
        self._publisher = fn

    # ---- events
    def emit(self, kind: str, agent_id: str, agent_name: str, **data: Any) -> Dict[str, Any]:
        self._seq += 1
        ev = {"seq": self._seq, "ts": time.time(), "kind": kind,
              "agent_id": agent_id, "agent": agent_name, **data}
        self.events.append(ev)
        if self.persist:
            try:
                self.dir.mkdir(parents=True, exist_ok=True)
                with (self.dir / "events.jsonl").open("a", encoding="utf-8") as fh:
                    fh.write(json.dumps(ev, ensure_ascii=False) + "\n")
            except OSError:
                self.persist = False
        for q in list(self._subs):
            try:
                q.put_nowait(ev)
            except asyncio.QueueFull:
                pass
        return ev

    def update_agent(self, agent_id: str, snap: Dict[str, Any]) -> None:
        snap = {**snap, "updated": time.time()}
        self.agents[agent_id] = snap
        hist = self.history.setdefault(agent_id, [])
        point = {"t": snap["updated"], "gen": snap.get("generation", 0),
                 "knowledge": snap.get("knowledge_count", 0), **snap.get("traits", {})}
        if not hist or hist[-1]["gen"] != point["gen"] or hist[-1]["knowledge"] != point["knowledge"]:
            hist.append(point)
            del hist[:-300]

    def remove_agent(self, agent_id: str) -> None:
        if agent_id in self.agents:
            self.agents[agent_id]["alive"] = False

    # ---- reads
    def state(self, since: int = 0, limit: int = 400) -> Dict[str, Any]:
        evs = [e for e in self.events if e["seq"] > since][-limit:]
        agents = list(self.agents.values())
        now = time.time()
        for a in agents:
            a["alive"] = a.get("alive", True) and now - a.get("updated", 0) < 30
        return {"now": now, "uptime": now - self.started, "agents": agents,
                "alive": sum(1 for a in agents if a["alive"]), "total": len(agents),
                "history": self.history, "events": evs, "last_seq": self._seq}

    def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=500)
        self._subs.append(q)
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        if q in self._subs:
            self._subs.remove(q)

    async def inject(self, text: str, author: str = "human") -> int:
        """Drop a topic into the swarm as a broadcast message (dashboard control)."""
        if not self._publisher:
            raise RuntimeError("swarm not running")
        msg = {"id": f"h{int(time.time()*1000)}", "from_id": "human", "from": author, "persona": "human",
               "to": "all", "text": text[:600], "topic": text[:80], "ts": time.time()}
        self.emit("message", "human", author, to="all", text=msg["text"], topic=msg["topic"])
        await self._publisher("human", "swarm.message", msg, None)
        return self._seq


_hub: Optional[SwarmHub] = None


def get_hub() -> SwarmHub:
    global _hub
    if _hub is None:
        _hub = SwarmHub()
    return _hub
