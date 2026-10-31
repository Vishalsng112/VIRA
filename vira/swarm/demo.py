"""Run the swarm + dashboard standalone (no auth, no kernel):

    python -m vira.swarm.demo --mock               # offline, scripted fake LLM
    python -m vira.swarm.demo                      # uses llm: section of config.yaml (Ollama etc.)
    python -m vira.swarm.demo --count 8 --port 8765

Uses the real AgentMessageBus / EventRouter / RuntimeScheduler, so it exercises
exactly the same routing as the full VIRA server.
"""
import argparse
import asyncio
import json
import random
import sys
from pathlib import Path

import uvicorn
import yaml
from fastapi import FastAPI
from fastapi.responses import FileResponse
from loguru import logger

from vira.agent_orchestration.message_bus import AgentMessageBus
from vira.agent_orchestration.messages import AgentMessage
from vira.agent_orchestration.registry import AgentRegistry
from vira.agent_orchestration.router import EventRouter
from vira.agent_orchestration.scheduler import RuntimeScheduler
from vira.api.routes_swarm import build_swarm_router
from vira.llm.base import LLMResponse
from vira.swarm.hub import get_hub
from vira.swarm.personas import expand_swarm_entries

FACTS = ["Pressure is easier to handle when the whole team shares the plan.",
         "A good story needs a clear want and an obstacle.",
         "Negotiations succeed when both sides can claim a win.",
         "Rhythm is predictable repetition with small surprises.",
         "Measuring a result twice beats trusting it once.",
         "Timing matters more than raw speed in most crafts."]


class MockLLM:
    """Deterministic-ish fake model so the whole loop can be tested offline."""
    async def generate(self, prompt: str, **kw) -> LLMResponse:
        await asyncio.sleep(random.uniform(0.05, 0.2))
        if "Reflect on how these conversations" in prompt:
            out = {"self_summary": "I am becoming more open to ideas from other fields.",
                   "trait_deltas": {"curiosity": random.choice([0.02, 0.03]), "openness": 0.02,
                                    "assertiveness": random.choice([-0.02, 0.01])},
                   "new_skill": random.choice(["cross-domain analogies", "active listening", "storytelling", ""])}
        else:
            names = [l.split(" (")[0] for l in prompt.split("Agents alive now: ")[1].split("\n")[0].split(", ")]
            fact = random.choice(FACTS)
            out = {"say": f"Here's a thought from my world: {fact} What do you think?",
                   "to": random.choice(names + ["all"]), "teach": fact,
                   "learned": [{"fact": random.choice(FACTS), "from": random.choice(names), "confidence": 0.7}] if random.random() < .6 else [],
                   "mood": random.choice(["curious", "excited", "calm", "playful"])}
        return LLMResponse(text=json.dumps(out), model="mock", usage={})


class _StubKernelBus:
    def subscribe_all(self, cb): return "stub"
    def unsubscribe_all(self, cb): return True
    async def publish(self, event): return 0


class DemoRuntime:
    def __init__(self, llm, bus):
        self._llm, self._bus = llm, bus
    async def get_context(self, agent_id): return None
    async def call_llm(self, agent_id, prompt, **kw):
        kw.pop("model", None)
        return await self._llm.generate(prompt, **kw)
    async def memory_operation(self, *a, **k): return None
    async def send_agent_message(self, sender_agent_id, event_type, data, target_agent_ids=None, exclude_sender=True):
        await self._bus.publish(AgentMessage(type=event_type, data=data, sender_agent_id=sender_agent_id,
                                             target_agent_ids=target_agent_ids, exclude_sender=exclude_sender))


def _real_llm(config_path: str):
    from vira.llm.factory import create_provider
    cfg = yaml.safe_load(Path(config_path).read_text())
    return create_provider(cfg["llm"]["models"][0])


async def run(args):
    from vira.agent.Agents.persona_agent import PersonaAgent
    bus = AgentMessageBus()
    registry = AgentRegistry()
    scheduler = RuntimeScheduler(registry, max_concurrent=max(10, args.count * 2))
    router = EventRouter(_StubKernelBus(), registry, scheduler=scheduler, agent_message_bus=bus)
    await router.start()
    runtime = DemoRuntime(MockLLM() if args.mock else _real_llm(args.config), bus)
    shared = {"speak_interval": [args.min_wait, args.max_wait], "heartbeat_interval": 2.0, "peer_ttl": 8.0,
              "reflect_every": args.reflect_every, "llm_concurrency": args.llm_concurrency, "data_dir": args.data_dir}
    entries = expand_swarm_entries([{"name": "Swarm", "swarm": {"count": args.count,
                                     "personas": ["cricketer", "actor", "politician"]}, "config": shared}])
    agents = []
    for cfg in entries:
        agent = PersonaAgent(runtime, **cfg["config"])
        await agent.initialize(); await agent.start(); await registry.register(agent)
        agents.append(agent)

    app = FastAPI(title="VIRA swarm demo")
    app.include_router(build_swarm_router())
    page = Path(__file__).parent.parent / "web" / "static" / "swarm.html"
    app.get("/")(lambda: FileResponse(str(page)))
    app.get("/swarm")(lambda: FileResponse(str(page)))
    server = uvicorn.Server(uvicorn.Config(app, host=args.host, port=args.port, log_level="warning"))
    logger.info("Swarm dashboard: http://{}:{}/", args.host, args.port)
    try:
        await server.serve()
    finally:
        for a in agents:
            await a.stop()


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--mock", action="store_true", help="use a fake offline LLM")
    p.add_argument("--count", type=int, default=5)
    p.add_argument("--port", type=int, default=8765)
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--config", default="config.yaml")
    p.add_argument("--data-dir", default="data/swarm")
    p.add_argument("--min-wait", type=float, default=8)
    p.add_argument("--max-wait", type=float, default=20)
    p.add_argument("--reflect-every", type=int, default=3)
    p.add_argument("--llm-concurrency", type=int, default=1)
    asyncio.run(run(p.parse_args()))


if __name__ == "__main__":
    main()
