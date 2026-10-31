"""Swarm tests: real AgentMessageBus + EventRouter + RuntimeScheduler, mock LLM."""
import asyncio
import tempfile

from vira.agent_orchestration.message_bus import AgentMessageBus
from vira.agent_orchestration.registry import AgentRegistry
from vira.agent_orchestration.router import EventRouter
from vira.agent_orchestration.scheduler import RuntimeScheduler
from vira.swarm.demo import DemoRuntime, MockLLM, _StubKernelBus
from vira.swarm.hub import get_hub
from vira.swarm.personas import expand_swarm_entries


def test_expand_swarm_entries():
    out = expand_swarm_entries([{"name": "S", "module": "m", "class": "C", "swarm": {"count": 10, "personas": ["actor"]}},
                                {"name": "plain", "module": "m", "class": "C"}])
    names = [c["name"] for c in out]
    assert len(out) == 11 and names[-1] == "plain" and len(set(names)) == 11
    assert out[0]["config"]["persona"] == "actor" and out[0]["config"]["swarm_size"] == 10


def test_swarm_talks_learns_evolves_and_tracks_alive():
    from vira.agent.Agents.persona_agent import PersonaAgent

    async def scenario():
        hub = get_hub()
        hub.persist = False
        hub.events.clear(); hub.agents.clear(); hub.history.clear()
        with tempfile.TemporaryDirectory() as tmp:
            bus, registry = AgentMessageBus(), AgentRegistry()
            sched = RuntimeScheduler(registry, max_concurrent=20)
            router = EventRouter(_StubKernelBus(), registry, scheduler=sched, agent_message_bus=bus)
            await router.start()
            runtime = DemoRuntime(MockLLM(), bus)
            shared = dict(speak_interval=[0.2, 0.5], heartbeat_interval=0.3, peer_ttl=1.5,
                          reflect_every=2, llm_concurrency=2, data_dir=tmp)
            agents = []
            for cfg in expand_swarm_entries([{"name": "T", "swarm": {"count": 5, "personas": ["cricketer", "actor", "dev_architect", "dev_ux", "dev_qa"]}, "config": shared}]):
                a = PersonaAgent(runtime, **cfg["config"])
                await a.initialize(); await a.start(); await registry.register(a)
                agents.append(a)
            await asyncio.sleep(9)
            # every agent independently knows all 5 are alive
            assert all(a.alive_count == 5 for a in agents), [a.alive_count for a in agents]
            kinds = {}
            for e in hub.events:
                kinds[e["kind"]] = kinds.get(e["kind"], 0) + 1
            assert kinds.get("message", 0) >= 10, kinds
            assert kinds.get("learn", 0) >= 3 and kinds.get("evolve", 0) >= 3, kinds
            assert any(a.generation > 0 for a in agents)
            assert all(a.sent > 0 for a in agents), [a.sent for a in agents]
            # one agent dies -> the others notice
            await agents[0].stop()
            await asyncio.sleep(2.5)
            assert all(a.alive_count == 4 for a in agents[1:]), [a.alive_count for a in agents[1:]]
            # human injection reaches the swarm
            before = sum(a.received for a in agents[1:])
            await hub.inject("What makes a legend?")
            await asyncio.sleep(1.5)
            assert sum(a.received for a in agents[1:]) > before
            state = hub.state()
            assert state["total"] == 5 and state["alive"] == 4, (state["total"], state["alive"])
            for a in agents[1:]:
                await a.stop()
            await router.stop()
            return kinds

    kinds = asyncio.run(scenario())
    print("event kinds:", kinds)


if __name__ == "__main__":
    test_expand_swarm_entries(); test_swarm_talks_learns_evolves_and_tracks_alive(); print("PASS")
