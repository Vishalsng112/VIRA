"""PersonaAgent: an autonomous, persona-driven agent that lives in a swarm.

One script, N agents: every instance reads its ``persona`` from config, runs its
own asyncio life-loop, discovers peers through heartbeats (so it always knows how
many agents are alive), talks to them over the agent message bus, learns facts
from the conversation and periodically *evolves* (traits, skills, self-summary,
generation counter).  All of it is mirrored to ``vira.swarm.hub`` for /swarm.
"""
import asyncio
import json
import random
import re
import time
from collections import deque
from pathlib import Path
from typing import Any, Deque, Dict, List, Optional

from loguru import logger

from vira.agent.base import BaseAgent
from vira.agent.toolcalls import extract_json
from vira.agent_orchestration.registry import AgentCapability, AgentState
from vira.swarm.hub import get_hub
from vira.swarm.personas import PERSONAS, TRAITS

EV_MSG, EV_BEAT, EV_HELLO, EV_BYE = "swarm.message", "swarm.heartbeat", "swarm.hello", "swarm.goodbye"
_WORD = re.compile(r"[a-z0-9]+")


def _tokens(text: str) -> set:
    return set(_WORD.findall(text.lower()))


def _same(a: str, b: str) -> bool:
    ta, tb = _tokens(a), _tokens(b)
    return bool(ta and tb) and len(ta & tb) / len(ta | tb) >= 0.7


def _clamp(x: float, lo: float = 0.05, hi: float = 0.95) -> float:
    return max(lo, min(hi, x))


class PersonaAgent(BaseAgent):
    def __init__(self, runtime, persona: str = "cricketer", name: Optional[str] = None,
                 speak_interval: List[float] = (15, 35), heartbeat_interval: float = 5.0,
                 peer_ttl: float = 20.0, reflect_every: int = 4, max_tokens: int = 400,
                 temperature: float = 0.85, llm_concurrency: int = 1, model: Optional[str] = None,
                 data_dir: str = "data/swarm", swarm_size: Optional[int] = None,
                 topics: Optional[List[str]] = None, max_knowledge: int = 60, **kwargs):
        spec = PERSONAS.get(persona)
        if spec is None:
            raise ValueError(f"unknown persona '{persona}', choose from {sorted(PERSONAS)}")
        super().__init__(name=name or kwargs.get("agent_name") or f"Swarm-{spec['title']}",
                         description=f"Autonomous swarm agent: {spec['bio']}", runtime=runtime)
        self.persona, self.spec = persona, spec
        self.speak_interval = (float(speak_interval[0]), float(speak_interval[1]))
        self.heartbeat_interval, self.peer_ttl = float(heartbeat_interval), float(peer_ttl)
        self.reflect_every, self.max_tokens = int(reflect_every), int(max_tokens)
        self.temperature, self.model = float(temperature), model
        self.max_knowledge, self.topics = int(max_knowledge), list(topics or [])
        self.expected_size = swarm_size
        self.data_dir = Path(data_dir)
        self.hub = get_hub()
        self.hub.configure(llm_concurrency=llm_concurrency, data_dir=data_dir)

        # --- evolving state
        self.traits: Dict[str, float] = dict(spec["traits"])
        self.knowledge: List[Dict[str, Any]] = [
            {"fact": f, "conf": 0.9, "source": "self", "hits": 0, "t": time.time()} for f in spec["seed"]]
        self.skills: List[str] = []
        self.self_summary: str = spec["bio"]
        self.generation = 0
        self.turns = 0
        self.trust: Dict[str, float] = {}
        self.mood = "neutral"
        # --- runtime state (not persisted)
        self.peers: Dict[str, Dict[str, Any]] = {}
        self.inbox: Deque[Dict[str, Any]] = deque(maxlen=20)
        self.convo: Deque[Dict[str, Any]] = deque(maxlen=14)
        self.sent = self.received = self.llm_errors = 0
        self._learned_since_reflect = 0
        self._tasks: List[asyncio.Task] = []
        self._wake = asyncio.Event()
        self._activity = "starting"
        self._subscribed_events = [EV_MSG, EV_BEAT, EV_HELLO, EV_BYE]
        self._capabilities = [AgentCapability(
            name="swarm_converse", description="Talk to peer agents, learn and evolve.",
            input_schema={"type": "object"}, output_schema={"type": "object"})]

    # ------------------------------------------------------------ lifecycle
    async def start(self):
        await super().start()
        self._load()
        self.hub.set_publisher(self.runtime.send_agent_message)
        self._tasks = [asyncio.create_task(self._heartbeat_loop(), name=f"{self.name}-beat"),
                       asyncio.create_task(self._life_loop(), name=f"{self.name}-life")]
        await self._announce(EV_HELLO)
        self.hub.emit("join", self.agent_id, self.name, persona=self.persona, generation=self.generation)
        self._publish_snapshot()
        logger.info("[swarm] {} ({}) started, generation {}", self.name, self.persona, self.generation)

    async def stop(self):
        for t in self._tasks:
            t.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks = []
        try:
            await self._announce(EV_BYE)
        except Exception:
            pass
        self._save()
        self.hub.emit("leave", self.agent_id, self.name)
        self.hub.remove_agent(self.agent_id)
        await super().stop()

    # ------------------------------------------------------------ event intake (fast, never calls the LLM)
    async def handle(self, event):
        data = event.data if isinstance(event.data, dict) else {}
        sender = data.get("id") or data.get("from_id") or event.sender_agent_id
        if sender == self.agent_id:
            return
        if event.type in (EV_BEAT, EV_HELLO):
            self._touch_peer(data)
        elif event.type == EV_BYE:
            self.peers.pop(sender, None)
        elif event.type == EV_MSG:
            self._on_message(data)

    async def think(self, context, **kw):          # BaseAgent contract: one cognitive cycle = _turn()
        return {"decision": "converse"}

    async def plan(self, thought, **kw):
        return [{"action": "turn"}]

    async def act(self, plan, **kw):
        await self._turn()
        return []

    async def reflect(self, result, **kw):
        return {"status": "ok", "turns": self.turns}

    def _touch_peer(self, d: Dict[str, Any]) -> None:
        pid = d.get("id")
        if not pid or pid == self.agent_id:
            return
        new = pid not in self.peers
        self.peers[pid] = {"name": d.get("name", pid[:6]), "persona": d.get("persona", "?"),
                           "generation": d.get("generation", 0), "last_seen": time.time()}
        if new:
            self.trust.setdefault(pid, 0.5)
            self.hub.emit("peer", self.agent_id, self.name, peer=d.get("name"), alive=len(self._alive_peers()) + 1)

    def _alive_peers(self) -> Dict[str, Dict[str, Any]]:
        now = time.time()
        return {k: v for k, v in self.peers.items() if now - v["last_seen"] < self.peer_ttl}

    @property
    def alive_count(self) -> int:
        return 1 + len(self._alive_peers())

    def _on_message(self, d: Dict[str, Any]) -> None:
        self.received += 1
        if d.get("from_id") not in (None, "human"):
            self._touch_peer({"id": d.get("from_id"), "name": d.get("from"), "persona": d.get("persona")})
        self.convo.append({"from": d.get("from", "?"), "to": d.get("to", "all"), "text": d.get("text", "")})
        self.inbox.append(d)
        self._ingest_teaching(d)
        if d.get("from_id") == "human":
            self._wake.set()

    # ------------------------------------------------------------ loops
    async def _heartbeat_loop(self):
        while True:
            try:
                await self._announce(EV_BEAT)
                self._publish_snapshot()
            except Exception as exc:                    # keep beating no matter what
                logger.debug("[swarm] {} heartbeat failed: {}", self.name, exc)
            await asyncio.sleep(self.heartbeat_interval)

    async def _life_loop(self):
        await asyncio.sleep(random.uniform(3, 8))        # let peers boot; desynchronise agents
        while True:
            try:
                await self._turn()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self.llm_errors += 1
                self._activity = "error"
                self.hub.emit("error", self.agent_id, self.name, error=str(exc)[:200])
                logger.warning("[swarm] {} turn failed: {}", self.name, exc)
            lo, hi = self.speak_interval
            delay = random.uniform(lo, hi) * (0.4 if self.inbox else 1.0) * (2 ** min(self.llm_errors, 3) if self.llm_errors else 1)
            self._activity = "idle"
            try:
                await asyncio.wait_for(self._wake.wait(), timeout=delay)
            except asyncio.TimeoutError:
                pass
            self._wake.clear()

    # ------------------------------------------------------------ one turn
    async def _turn(self):
        peers = self._alive_peers()
        if not peers and not any(m.get("from_id") == "human" for m in self.inbox):
            self._activity = "waiting for peers"
            return
        incoming = self._pick_incoming()
        self._activity = "thinking"
        self._publish_snapshot()
        reply = await self._ask_llm(self._conversation_prompt(incoming, peers))
        data = extract_json(reply) or {"say": reply.strip()}
        say = str(data.get("say") or "").strip()[:600]
        if not say:
            return
        self.turns += 1
        self.llm_errors = 0
        self.mood = str(data.get("mood") or self.mood)[:20]
        to_name = str(data.get("to") or "all")
        target = next((pid for pid, p in peers.items() if p["name"].lower() == to_name.lower()), None)
        if incoming and not target and incoming.get("from_id") in peers:
            target, to_name = incoming["from_id"], incoming.get("from", "all")
        teach = str(data.get("teach") or "").strip()[:240]
        topic = (incoming or {}).get("topic") or say[:60]
        msg = {"id": f"{self.agent_id[:6]}-{self.turns}", "from_id": self.agent_id, "from": self.name,
               "persona": self.persona, "to": to_name if target else "all", "text": say, "teach": teach,
               "topic": topic, "reply_to": (incoming or {}).get("id"), "ts": time.time()}
        self.convo.append({"from": self.name, "to": msg["to"], "text": say})
        await self.send_event(EV_MSG, msg, target_agent_ids=[target] if target else None)
        self.sent += 1
        self.hub.emit("message", self.agent_id, self.name, persona=self.persona, to=msg["to"],
                      text=say, teach=teach, topic=topic, mood=self.mood, reply_to=msg["reply_to"])
        self._apply_learned(data.get("learned"), peers)
        if self.turns % self.reflect_every == 0:
            await self._evolve()
        self._save()
        self._publish_snapshot()

    def _pick_incoming(self) -> Optional[Dict[str, Any]]:
        if not self.inbox:
            return None
        humans = [m for m in self.inbox if m.get("from_id") == "human"]
        chosen = humans[-1] if humans else self.inbox[-1]
        self.inbox.clear()
        return chosen

    async def _ask_llm(self, prompt: str) -> str:
        kw = {"temperature": self.temperature, "max_tokens": self.max_tokens}
        if self.model:
            kw["model"] = self.model
        async with self.hub.llm_slot:                   # one shared local model: take turns
            resp = await asyncio.wait_for(self.runtime.call_llm(self.agent_id, prompt, **kw), timeout=180)
        return getattr(resp, "text", None) or str(resp)

    # ------------------------------------------------------------ prompts
    def _knowledge_lines(self, n: int = 8) -> str:
        top = sorted(self.knowledge, key=lambda k: k["conf"] * (1 + 0.1 * k["hits"]), reverse=True)[:n]
        return "\n".join(f"- {k['fact']} ({k['conf']:.2f})" for k in top) or "- (nothing yet)"

    def _conversation_prompt(self, incoming: Optional[Dict[str, Any]], peers: Dict[str, Dict[str, Any]]) -> str:
        trait_line = ", ".join(f"{t} {self.traits[t]:.2f}" for t in TRAITS)
        roster = ", ".join(f"{p['name']} ({p['persona']})" for p in peers.values()) or "nobody yet"
        recent = "\n".join(f"{c['from']} -> {c['to']}: {c['text']}" for c in list(self.convo)[-6:]) or "(silence)"
        if incoming:
            task = f"{incoming.get('from')} just said to you: \"{incoming.get('text')}\". Respond in character, and share or ask for knowledge."
            if self.spec.get("mission"):
                task += " Build on it: agree, object with a reason, or refine into a concrete decision."
        else:
            seeds = self.topics or self.spec["seed"]
            if self.spec.get("mission"):
                task = ("Move the shared project forward: propose one concrete design decision from your area, or ask a peer "
                        f"a specific question about theirs (inspiration: {random.choice(seeds)}).")
            else:
                task = ("Start a conversation. Ask one specific peer something you want to learn, or share an idea from your world "
                        f"(inspiration: {random.choice(seeds)}).")
        return (
            f"You are {self.name}, one of {self.alive_count} autonomous agents alive in a swarm. {self.spec['bio']}\n"
            f"Speaking style: {self.spec['style']}\nWho you are becoming: {self.self_summary}\n"
            + (f"Shared mission: {self.spec['mission']}\n" if self.spec.get("mission") else "") +
            f"Personality (0-1): {trait_line}\nSkills: {', '.join(self.skills) or 'none yet'}\n"
            f"What you know (confidence):\n{self._knowledge_lines()}\n"
            f"Agents alive now: {roster}\nRecent conversation:\n{recent}\n\n{task}\n"
            'Reply with ONLY JSON: {"say":"<1-3 sentences, in character>","to":"<exact agent name or all>",'
            '"teach":"<one factual sentence from your expertise worth sharing, or empty>",'
            '"learned":[{"fact":"<one new fact YOU just learned from the conversation>","from":"<agent name>","confidence":0.7}],'
            '"mood":"<one word>"}\nOnly fill "learned" when the conversation really taught you something new.'
        )

    # ------------------------------------------------------------ learning
    def _find(self, fact: str) -> Optional[Dict[str, Any]]:
        return next((k for k in self.knowledge if _same(k["fact"], fact)), None)

    def _add_fact(self, fact: str, source: str, conf: float, peer_id: Optional[str] = None) -> bool:
        fact = fact.strip()[:240]
        if len(fact) < 8:
            return False
        existing = self._find(fact)
        if existing:                                    # reinforcement, not duplication
            existing["conf"] = min(0.99, existing["conf"] + 0.1)
            existing["hits"] += 1
            return False
        self.knowledge.append({"fact": fact, "conf": round(_clamp(conf, 0.1, 0.95), 2), "source": source, "hits": 0, "t": time.time()})
        if len(self.knowledge) > self.max_knowledge:
            self.knowledge.sort(key=lambda k: k["conf"] * (1 + 0.1 * k["hits"]))
            del self.knowledge[0]
        self._learned_since_reflect += 1
        if peer_id:
            self.trust[peer_id] = _clamp(self.trust.get(peer_id, 0.5) + 0.04 * conf, 0, 1)
        self.hub.emit("learn", self.agent_id, self.name, fact=fact, source=source, confidence=round(conf, 2))
        return True

    def _ingest_teaching(self, d: Dict[str, Any]) -> None:
        teach, src, pid = d.get("teach"), d.get("from", "?"), d.get("from_id")
        if teach and pid != "human":
            self._add_fact(teach, src, 0.65 - 0.3 * self.traits["skepticism"], peer_id=pid)

    def _apply_learned(self, learned: Any, peers: Dict[str, Dict[str, Any]]) -> None:
        if not isinstance(learned, list):
            return
        by_name = {p["name"].lower(): pid for pid, p in peers.items()}
        for item in learned[:3]:
            if isinstance(item, dict) and isinstance(item.get("fact"), str):
                src = str(item.get("from") or "conversation")
                try:
                    conf = float(item.get("confidence", 0.6))
                except (TypeError, ValueError):
                    conf = 0.6
                self._add_fact(item["fact"], src, conf * (1 - 0.3 * self.traits["skepticism"]), by_name.get(src.lower()))

    # ------------------------------------------------------------ evolution
    async def _evolve(self):
        before = dict(self.traits)
        self._activity = "evolving"
        learned = self._learned_since_reflect
        recent = "\n".join(f"{c['from']}: {c['text']}" for c in list(self.convo)[-8:])
        prompt = (f"You are {self.name} ({self.spec['bio']}). Your current self-description: {self.self_summary}\n"
                  f"Personality: {', '.join(f'{t} {v:.2f}' for t, v in self.traits.items())}\n"
                  f"Facts learned recently: {learned}. Recent conversation:\n{recent}\n"
                  "Reflect on how these conversations changed you. Reply with ONLY JSON: "
                  '{"self_summary":"<2 sentences: who you are becoming>","trait_deltas":{"curiosity":0.02,"openness":0.0},'
                  '"new_skill":"<short skill gained, or empty>"} Each delta must be between -0.05 and 0.05.')
        summary, skill, used_llm = None, "", False
        try:
            data = extract_json(await self._ask_llm(prompt)) or {}
            deltas = data.get("trait_deltas") if isinstance(data.get("trait_deltas"), dict) else {}
            for t in TRAITS:
                try:
                    self.traits[t] = _clamp(self.traits[t] + max(-0.05, min(0.05, float(deltas.get(t, 0)))))
                except (TypeError, ValueError):
                    pass
            summary = str(data.get("self_summary") or "").strip()[:400] or None
            skill = str(data.get("new_skill") or "").strip()[:60]
            used_llm = bool(deltas or summary)
        except Exception as exc:
            logger.debug("[swarm] {} reflection LLM failed: {}", self.name, exc)
        if not used_llm:                                 # deterministic drift keeps evolving even if the model fails
            if learned:
                self.traits["curiosity"] = _clamp(self.traits["curiosity"] + 0.01)
                self.traits["openness"] = _clamp(self.traits["openness"] + 0.01)
            else:
                self.traits["assertiveness"] = _clamp(self.traits["assertiveness"] + 0.01)
        if summary:
            self.self_summary = summary
        if skill and skill.lower() not in (s.lower() for s in self.skills):
            self.skills = (self.skills + [skill])[-12:]
        self.generation += 1
        self._learned_since_reflect = 0
        self.hub.emit("evolve", self.agent_id, self.name, generation=self.generation, summary=self.self_summary,
                      skill=skill, learned=learned, llm=used_llm,
                      changes={t: round(self.traits[t] - before[t], 3) for t in TRAITS if abs(self.traits[t] - before[t]) > 1e-6},
                      traits={t: round(v, 3) for t, v in self.traits.items()})

    # ------------------------------------------------------------ messaging / telemetry / persistence
    async def _announce(self, event_type: str):
        await self.send_event(event_type, {"id": self.agent_id, "name": self.name, "persona": self.persona,
                                           "generation": self.generation, "ts": time.time()})

    def _publish_snapshot(self):
        peers = self._alive_peers()
        top = sorted(self.knowledge, key=lambda k: k["conf"], reverse=True)[:12]
        self.hub.update_agent(self.agent_id, {
            "id": self.agent_id, "name": self.name, "persona": self.persona, "title": self.spec["title"],
            "alive": True, "activity": self._activity, "mood": self.mood, "generation": self.generation,
            "traits": {t: round(v, 3) for t, v in self.traits.items()}, "skills": self.skills,
            "self_summary": self.self_summary, "knowledge_count": len(self.knowledge),
            "knowledge": [{"fact": k["fact"], "conf": k["conf"], "source": k["source"]} for k in top],
            "peers_alive": sorted(p["name"] for p in peers.values()), "alive_known": 1 + len(peers),
            "trust": {self.peers[p]["name"]: round(v, 3) for p, v in self.trust.items() if p in self.peers},
            "turns": self.turns, "sent": self.sent, "received": self.received, "errors": self.llm_errors,
            "state": self.state.value if isinstance(self.state, AgentState) else str(self.state)})

    def _path(self) -> Path:
        return self.data_dir / f"{re.sub(r'[^A-Za-z0-9_-]+', '_', self.name)}.json"

    def _save(self):
        try:
            self.data_dir.mkdir(parents=True, exist_ok=True)
            self._path().write_text(json.dumps({
                "traits": self.traits, "knowledge": self.knowledge, "skills": self.skills,
                "self_summary": self.self_summary, "generation": self.generation, "turns": self.turns}), encoding="utf-8")
        except OSError as exc:
            logger.debug("[swarm] save failed: {}", exc)

    def _load(self):
        try:
            d = json.loads(self._path().read_text(encoding="utf-8"))
            self.traits.update({k: float(v) for k, v in d.get("traits", {}).items() if k in TRAITS})
            self.knowledge = d.get("knowledge") or self.knowledge
            self.skills, self.self_summary = d.get("skills", []), d.get("self_summary", self.self_summary)
            self.generation, self.turns = int(d.get("generation", 0)), int(d.get("turns", 0))
        except (OSError, ValueError):
            pass
