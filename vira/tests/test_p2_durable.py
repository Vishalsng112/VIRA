"""Durable workflow and RAG vector tests."""
import asyncio
import tempfile
import unittest
from pathlib import Path

from vira.agent_orchestration import workflow_store as store
from vira.agent_orchestration.workflow import Workflow, WorkflowEngine, WorkflowStatus, WorkflowStep
from vira.auth import auth, database
from vira.rag import service as rag


class _Agent:
    def __init__(self, name, calls):
        self.name = name
        self.calls = calls

    async def run(self, input_data=None):
        self.calls.append((self.name, input_data))
        return {"agent": self.name, "input": input_data}


class _Registry:
    def __init__(self, agents):
        self.agents = agents

    async def get_instance(self, agent_id):
        return self.agents.get(agent_id)


class _Scheduler:
    async def run_agent(self, agent, input_data):
        return await agent.run(input_data=input_data)


class DurableWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        database.DB_PATH = Path(self.tmp.name) / "wf.sqlite3"
        database.init_db()
        auth.create_admin("root", "rootpass1")

    def tearDown(self):
        self.tmp.cleanup()

    def test_resume_skips_completed_steps(self):
        calls = []
        agents = {"a": _Agent("a", calls), "b": _Agent("b", calls)}
        engine = WorkflowEngine(_Scheduler(), _Registry(agents))
        workflow = Workflow(
            id="wf-1",
            name="demo",
            steps=[
                WorkflowStep(id="s1", name="one", agent_id="a", input={"x": 1}),
                WorkflowStep(id="s2", name="two", agent_id="b",
                             input={"previous": "{{ steps.s1.result }}"},
                             depends_on=["s1"]),
            ],
        )
        async def scenario():
            await engine.create(workflow, user_id=1)
            # Simulate a process crash after s1 completed.
            s1 = workflow.steps[0]
            s1.status = "completed"
            s1.result = {"agent": "a", "input": {"x": 1}}
            store.save_step("wf-1", s1)
            s2 = workflow.steps[1]
            s2.status = "running"
            store.save_step("wf-1", s2)
            await engine.resume("wf-1")
            for _ in range(50):
                current = store.load("wf-1")
                if current.status in (WorkflowStatus.COMPLETED, WorkflowStatus.FAILED):
                    break
                await asyncio.sleep(0.02)

        asyncio.run(scenario())
        loaded = store.load("wf-1")
        self.assertEqual(loaded.status, WorkflowStatus.COMPLETED)
        self.assertEqual([name for name, _ in calls], ["b"])
        self.assertEqual(loaded.steps[0].status, "completed")

    def test_create_and_replay_events(self):
        calls = []
        engine = WorkflowEngine(_Scheduler(), _Registry({"a": _Agent("a", calls)}))
        workflow = Workflow(
            id="wf-2", name="one step",
            steps=[WorkflowStep(id="s1", name="only", agent_id="a")],
        )
        async def scenario():
            await engine.create(workflow, user_id=1)
            await engine.start("wf-2")
            for _ in range(50):
                current = store.load("wf-2")
                if current.status in (WorkflowStatus.COMPLETED, WorkflowStatus.FAILED):
                    break
                await asyncio.sleep(0.02)

        asyncio.run(scenario())
        loaded = store.load("wf-2")
        self.assertEqual(loaded.status, WorkflowStatus.COMPLETED)
        events = store.list_events("wf-2")
        self.assertTrue(any(event["event_type"] == "workflow.completed" for event in events))


class RagVectorTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        database.DB_PATH = Path(self.tmp.name) / "rag.sqlite3"
        database.init_db()
        auth.create_admin("root", "rootpass1")

    def tearDown(self):
        self.tmp.cleanup()

    def test_ingest_and_vector_search(self):
        asyncio.run(rag.ingest(
            1, "Photoshop guide",
            "Adobe Photoshop uses layers, masks and adjustment layers for image editing.",
            source="notes",
        ))
        asyncio.run(rag.ingest(
            1, "Cooking notes",
            "Pasta is boiled in salted water and finished with a tomato sauce.",
            source="notes",
        ))
        results = asyncio.run(rag.search(1, "photoshop layer masking", limit=2))
        self.assertTrue(results)
        self.assertEqual(results[0]["title"], "Photoshop guide")
        self.assertGreater(results[0]["score"], 0)
        documents = rag.list_documents(1)
        self.assertEqual(len(documents), 2)


if __name__ == "__main__":
    unittest.main()
