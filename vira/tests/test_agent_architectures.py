"""Paper-aligned agent architectures: selection rules and execution."""
import unittest
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from vira.agent.architectures import (
    ARCHITECTURE_PROFILES,
    AdaptiveAgentSystem,
    Architecture,
    CentralizedAgentSystem,
    DecentralizedAgentSystem,
    HybridAgentSystem,
    IndependentAgentSystem,
    SingleAgent,
    TaskProfile,
    recommend_architecture,
)
from vira.agent.base import TaskRequest
from vira.api.routes_architectures import build_architecture_router


class _Registry:
    version = 1

    def get(self, name):
        return None


class _Executor:
    def __init__(self):
        self._registry = _Registry()

    def list_tools(self):
        return []


class _Runtime:
    """Deterministic LLM fake keyed on prompt markers."""

    def __init__(self, handler=None):
        self.handler = handler or self.default
        self.prompts = []
        self.tool_executor = _Executor()

    @staticmethod
    def default(prompt):
        if "Break the task into" in prompt:
            return '{"subtasks": ["part A", "part B"]}'
        if "validating one worker result" in prompt:
            return '{"ok": false, "issue": "incomplete", "revised": "fixed result"}'
        if "decentralized debate" in prompt:
            return "debated result"
        if "final synthesizer" in prompt:
            return "final merged"
        if "focused worker" in prompt:
            return "worker result"
        return "single answer"

    async def call_llm(self, agent_id, prompt, **kwargs):
        self.prompts.append(prompt)
        return SimpleNamespace(text=self.handler(prompt))

    async def get_context(self, agent_id):
        return SimpleNamespace(agent_id=agent_id)

    async def memory_operation(self, agent_id, operation, **kwargs):
        return []

    async def send_agent_message(self, sender_agent_id, event_type, data,
                                 target_agent_ids=None, exclude_sender=True):
        return None


def _request(message="do the task", profile=None, **extra):
    metadata = dict(extra.pop("metadata", {}) or {})
    if profile is not None:
        metadata["task_profile"] = profile
    return TaskRequest(input={"message": message}, user_id=1,
                       conversation_id="c1", run_id="r1",
                       metadata=metadata, **extra)


class RecommendationTests(unittest.TestCase):
    def test_sequential_task_stays_single(self):
        rec = recommend_architecture(TaskProfile(
            decomposability=0.8, sequential_dependencies=0.9, tool_count=4,
            single_agent_baseline=0.2))
        self.assertEqual(rec.architecture, Architecture.SINGLE)
        self.assertEqual(rec.confidence, "strong")

    def test_parallel_analysis_prefers_centralized(self):
        rec = recommend_architecture(TaskProfile(
            decomposability=0.8, sequential_dependencies=0.1, tool_count=5,
            single_agent_baseline=0.35))
        self.assertEqual(rec.architecture, Architecture.CENTRALIZED)
        self.assertTrue(any("+80.9%" in reason for reason in rec.reasons))

    def test_dynamic_environment_prefers_decentralized(self):
        rec = recommend_architecture(TaskProfile(
            decomposability=0.7, sequential_dependencies=0.2, tool_count=5,
            single_agent_baseline=0.4, dynamic_environment=True))
        self.assertEqual(rec.architecture, Architecture.DECENTRALIZED)

    def test_tool_heavy_task_beats_capability_ceiling(self):
        rec = recommend_architecture(TaskProfile(
            decomposability=0.8, sequential_dependencies=0.1, tool_count=16,
            single_agent_baseline=0.63))
        self.assertEqual(rec.architecture, Architecture.DECENTRALIZED)

    def test_capability_ceiling_prefers_single(self):
        rec = recommend_architecture(TaskProfile(
            decomposability=0.8, sequential_dependencies=0.1, tool_count=4,
            single_agent_baseline=0.5))
        self.assertEqual(rec.architecture, Architecture.SINGLE)

    def test_peer_review_prefers_hybrid(self):
        rec = recommend_architecture(TaskProfile(
            decomposability=0.7, sequential_dependencies=0.2, tool_count=5,
            single_agent_baseline=0.3, needs_peer_review=True))
        self.assertEqual(rec.architecture, Architecture.HYBRID)

    def test_unknown_profile_falls_back_to_single(self):
        rec = recommend_architecture(TaskProfile(
            decomposability=0.4, sequential_dependencies=0.4, tool_count=2))
        self.assertEqual(rec.architecture, Architecture.SINGLE)
        self.assertEqual(rec.confidence, "fallback")

    def test_profile_is_clamped_and_serialized(self):
        rec = recommend_architecture(TaskProfile(
            decomposability=5, sequential_dependencies=-2,
            single_agent_baseline=3))
        self.assertEqual(rec.architecture, Architecture.SINGLE)
        self.assertLessEqual(rec.profile["decomposability"], 1.0)
        self.assertGreaterEqual(rec.profile["sequential_dependencies"], 0.0)
        self.assertLessEqual(rec.profile["single_agent_baseline"], 1.0)
        self.assertIn("coordination", rec.as_dict())

    def test_malformed_profile_values_fall_back(self):
        profile = TaskProfile.from_mapping({
            "decomposability": "bad",
            "sequential_dependencies": None,
            "tool_count": "many",
            "single_agent_baseline": "unknown",
        })
        self.assertEqual(profile.decomposability, 0.5)
        self.assertEqual(profile.sequential_dependencies, 0.5)
        self.assertEqual(profile.tool_count, 0)
        self.assertEqual(profile.single_agent_baseline, 0.0)

    def test_profiles_carry_measured_coordination_costs(self):
        self.assertEqual(ARCHITECTURE_PROFILES[Architecture.SINGLE]["overhead_pct"], 0)
        self.assertEqual(
            ARCHITECTURE_PROFILES[Architecture.INDEPENDENT]["error_amplification"],
            17.2)
        self.assertEqual(
            ARCHITECTURE_PROFILES[Architecture.HYBRID]["overhead_pct"], 515)


class ArchitectureExecutionTests(unittest.IsolatedAsyncioTestCase):
    async def _run(self, agent, request):
        await agent.initialize()
        await agent.start()
        return await agent.run_task(request)

    async def test_single_agent_uses_tool_loop_and_reports_architecture(self):
        agent = SingleAgent(_Runtime())
        result = await self._run(agent, _request())
        self.assertEqual(result.text, "single answer")
        self.assertEqual(result.data["architecture"], "single")
        self.assertEqual(result.data["coordination"]["workers"], 1)

    async def test_independent_system_runs_workers_then_synthesizes(self):
        runtime = _Runtime()
        agent = IndependentAgentSystem(runtime, worker_count=2, delegation=False)
        result = await self._run(agent, _request())
        self.assertEqual(result.text, "final merged")
        self.assertEqual(result.data["architecture"], "independent")
        self.assertEqual(result.data["coordination"]["workers"], 2)
        self.assertEqual(result.data["coordination"]["rounds"], 0)
        self.assertEqual(result.data["coordination"]["llm_calls"], 3)
        self.assertEqual(len(runtime.prompts), 3)
        self.assertTrue(any("System:" in prompt for prompt in runtime.prompts))

    async def test_centralized_system_plans_validates_and_corrects(self):
        runtime = _Runtime()
        agent = CentralizedAgentSystem(
            runtime, worker_count=2, max_subtasks=2, delegation=False)
        result = await self._run(agent, _request())
        self.assertEqual(result.text, "final merged")
        self.assertEqual(result.data["architecture"], "centralized")
        self.assertEqual(result.data["coordination"]["subtasks"],
                         ["part A", "part B"])
        self.assertEqual(result.data["coordination"]["corrections"], 2)
        self.assertEqual(result.data["coordination"]["llm_calls"], 6)
        self.assertTrue(all(
            item["output"] == "fixed result" for item in result.data["workers"]))
        self.assertEqual(len(runtime.prompts), 6)

    async def test_decentralized_system_debates_for_bounded_rounds(self):
        runtime = _Runtime()
        agent = DecentralizedAgentSystem(
            runtime, worker_count=2, debate_rounds=1, delegation=False)
        result = await self._run(agent, _request())
        self.assertEqual(result.text, "final merged")
        self.assertEqual(result.data["architecture"], "decentralized")
        self.assertEqual(result.data["coordination"]["rounds"], 1)
        self.assertEqual(result.data["coordination"]["llm_calls"], 5)
        self.assertEqual(result.data["workers"][0]["output"], "debated result")

    async def test_hybrid_system_uses_hierarchy_and_peer_round(self):
        runtime = _Runtime()
        agent = HybridAgentSystem(
            runtime, worker_count=2, max_subtasks=2, debate_rounds=1,
            delegation=False)
        result = await self._run(agent, _request())
        self.assertEqual(result.text, "final merged")
        self.assertEqual(result.data["architecture"], "hybrid")
        self.assertEqual(result.data["coordination"]["rounds"], 1)
        self.assertEqual(result.data["coordination"]["llm_calls"], 8)
        self.assertEqual(result.data["coordination"]["corrections"], 2)
        self.assertEqual(len(runtime.prompts), 8)

    async def test_adaptive_selects_single_for_sequential_profile(self):
        runtime = _Runtime()
        agent = AdaptiveAgentSystem(runtime, delegation=False)
        result = await self._run(agent, _request(profile={
            "decomposability": 0.8,
            "sequential_dependencies": 0.9,
            "tool_count": 4,
            "single_agent_baseline": 0.2,
        }))
        self.assertEqual(result.data["architecture"], "single")
        recommendation = result.data["coordination"]["recommendation"]
        self.assertEqual(recommendation["architecture"], "single")

    async def test_adaptive_selects_centralized_for_analysis_profile(self):
        runtime = _Runtime()
        agent = AdaptiveAgentSystem(
            runtime, worker_count=2, max_subtasks=2, delegation=False)
        result = await self._run(agent, _request(profile={
            "decomposability": 0.8,
            "sequential_dependencies": 0.1,
            "tool_count": 5,
            "single_agent_baseline": 0.35,
        }))
        self.assertEqual(result.data["architecture"], "centralized")
        self.assertEqual(
            result.data["coordination"]["recommendation"]["architecture"],
            "centralized")

    async def test_worker_and_round_limits_are_bounded(self):
        agent = IndependentAgentSystem(
            _Runtime(), worker_count=99, delegation=False)
        self.assertEqual(agent.worker_count, 8)
        agent = DecentralizedAgentSystem(
            _Runtime(), worker_count=2, debate_rounds=99, delegation=False)
        self.assertEqual(agent.debate_rounds, 3)
        agent = IndependentAgentSystem(
            _Runtime(), worker_count=2, worker_max_tokens=321, delegation=False)
        self.assertEqual(agent._worker_tokens(), 321)


class ArchitectureApiTests(unittest.TestCase):
    def setUp(self):
        app = FastAPI()
        app.include_router(build_architecture_router(lambda: None))
        self.client = TestClient(app)

    def test_catalog_lists_every_topology(self):
        response = self.client.get("/api/v1/agent-architectures")
        self.assertEqual(response.status_code, 200)
        ids = {item["id"] for item in response.json()["architectures"]}
        self.assertEqual(ids, {item.value for item in Architecture})

    def test_recommend_endpoint_returns_a_topology(self):
        response = self.client.post(
            "/api/v1/agent-architectures/recommend",
            json={
                "decomposability": 0.8,
                "sequential_dependencies": 0.1,
                "tool_count": 5,
                "single_agent_baseline": 0.35,
            },
        )
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["architecture"], "centralized")
        self.assertIn("coordination", body)
        self.assertTrue(body["reasons"])


if __name__ == "__main__":
    unittest.main()
