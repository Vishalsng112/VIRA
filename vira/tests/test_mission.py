"""Mission tests (offline, MockLLM / scripted fakes). Run: pytest vira/tests/test_mission.py"""
import asyncio
import io
import json
import tempfile
import zipfile

import pytest

from vira.mission.crew import Mission, MissionManager, parse_output
from vira.mission.llm import MockLLM, make_ask
from vira.mission.plan import fallback_plan, make_plan, normalise
from vira.mission.workspace import Workspace, WorkspaceError

FAST = dict(llm_concurrency=3, max_llm_calls=60, max_minutes=2)


def run(coro):
    return asyncio.run(coro)


def test_workspace_blocks_escape_and_checks_syntax():
    with tempfile.TemporaryDirectory() as tmp:
        ws = Workspace(tmp)
        for bad in ("../x", "a/../../b", ".git/config", "a//b", ""):
            with pytest.raises(WorkspaceError):
                ws.write(bad, "x")
        assert ws.write("/etc/passwd", "x")["path"] == "etc/passwd"          # absolute paths are confined to the workspace
        assert ws.write("ok/a.py", "def f(:\n")["check"].startswith("python syntax error")
        assert ws.write("ok/a.py", "x = 1\n")["version"] == 2 and ws.meta["ok/a.py"]["check"] == ""
        assert ws.write("d.json", "{bad")["check"].startswith("invalid JSON")
        z = zipfile.ZipFile(io.BytesIO(ws.zip_bytes()))
        assert sorted(z.namelist()) == ["d.json", "etc/passwd", "ok/a.py"]


def test_parse_output_tolerates_fences_and_truncation():
    out = parse_output('<message to="qa">[QUESTION] hi?</message><file path="a.py">\n```python\nx=1\n```\n</file>'
                       '<file path="b.py">\ny = (1,\n<note>n</note>')
    assert out["files"][0]["content"] == "x=1" and not out["files"][0]["truncated"]
    assert out["files"][1]["truncated"] and out["messages"] == [("qa", "[QUESTION] hi?")]


def test_normalise_repairs_plan():
    raw = {"roles": [{"key": "Dev One", "title": "Dev"}, {"key": "dev_one"}, {"key": "x"}],
           "tasks": [{"id": "A", "owner": "ghost", "depends_on": ["B"]}, {"id": "B", "owner": "dev_one", "depends_on": ["A", "Z"]}]}
    p = normalise(raw, "brief", lo=2, hi=3)
    keys = [r["key"] for r in p["roles"]]
    assert len(keys) == len(set(keys)) <= 3 and any("qa" in k or "review" in k for k in keys)
    assert all(t["owner"] in keys for t in p["tasks"])
    a, b = p["tasks"]
    assert not (a["depends_on"] and b["depends_on"]), "dependency cycle must be broken"
    with pytest.raises(ValueError):
        normalise({"roles": [], "tasks": []}, "b", 2, 4)


def test_make_plan_falls_back_on_garbage():
    async def junk(prompt, **kw):
        return "I am not JSON"
    p = run(make_plan(junk, "Build a payroll app", 3, 5))
    assert p.get("fallback") and 3 <= len(p["roles"]) <= 5 and p["tasks"]
    assert fallback_plan("x", 3, 8)["roles"]


def _mission(tmp, ask, **cfg):
    return Mission("Build a demo accounting CLI app", ask, root=tmp, cfg={**FAST, **cfg})


def test_full_mission_with_mock_llm():
    async def scenario(tmp):
        m = _mission(tmp, make_ask(MockLLM(delay=0.01)))
        await asyncio.wait_for(m.run(), 60)
        return m

    with tempfile.TemporaryDirectory() as tmp:
        m = run(scenario(tmp))
        assert m.status == "done", (m.status, m.error)
        assert len(m.agents) == 5                         # master + 4 experts chosen by the plan
        assert all(t["status"] == "done" for t in m.tasks.values())
        paths = {f["path"] for f in m.ws.files()}
        assert {"app/core.py", "app/ui.py", "tests/test_core.py", "docs/ARCHITECTURE.md", "README.md", "MISSION_REPORT.md"} <= paths
        kinds = {}
        for e in m.hub.events:
            kinds[e["kind"]] = kinds.get(e["kind"], 0) + 1
        assert kinds["join"] == 5 and kinds["file"] >= 4 and kinds["message"] >= 5 and kinds["mission_done"] == 1, kinds
        assert any(e["kind"] == "message" and e["tag"] == "QUESTION" for e in m.hub.events)   # agents talk to each other
        assert any(a.replies for a in m.agents.values())                                     # ...and answer
        assert any("paise" in d["text"] for d in m.decisions)                               # shared decision log
        assert json.loads((m.dir / "meta" / "mission.json").read_text())["status"] == "done"


def test_retry_fix_and_review_tasks():
    """First attempt writes broken python -> author is asked to fix it."""
    calls = {"n": 0}
    base = MockLLM(delay=0)

    async def ask(prompt, **kw):
        out = (await base.generate(prompt)).text
        if "### WORK_TASK" in prompt and "TASK_ID: T2" in prompt and calls["n"] == 0:
            calls["n"] += 1
            out = '<file path="app/core.py">\ndef broken(:\n</file><status>done</status>'
        return out

    async def scenario(tmp):
        m = _mission(tmp, ask)
        await asyncio.wait_for(m.run(), 60)
        return m

    with tempfile.TemporaryDirectory() as tmp:
        m = run(scenario(tmp))
        assert m.status == "done" and m.tasks["T2"]["attempts"] == 2 and m.tasks["T2"]["status"] == "done"
        assert m.ws.meta["app/core.py"]["check"] == "" and m.ws.meta["app/core.py"]["version"] == 2


def test_budget_exhaustion_ends_gracefully():
    async def scenario(tmp):
        m = _mission(tmp, make_ask(MockLLM(delay=0)), max_llm_calls=3)
        await asyncio.wait_for(m.run(), 60)
        return m

    with tempfile.TemporaryDirectory() as tmp:
        m = run(scenario(tmp))
        assert m.status == "budget_exhausted" and m.calls <= 3
        assert m.ws.exists("MISSION_REPORT.md")


def test_manager_runs_one_mission_and_lists_it():
    async def scenario(tmp):
        mgr = MissionManager(ask_factory=lambda model: make_ask(MockLLM(delay=0.2)), overrides={**FAST, "data_dir": tmp})
        m = await mgr.start("Build something useful for the client")
        with pytest.raises(RuntimeError):
            await mgr.start("A second mission at once")
        with pytest.raises(ValueError):
            await MissionManager(ask_factory=lambda x: None).start("hi")
        await asyncio.wait_for(m._main, 60)
        assert mgr.list()[0]["id"] == m.id and mgr.workspace(m.id) and mgr.workspace("../etc") is None
        return m.status

    with tempfile.TemporaryDirectory() as tmp:
        assert run(scenario(tmp)) == "done"


def test_api_end_to_end():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from vira.api.routes_mission import build_mission_router

    with tempfile.TemporaryDirectory() as tmp:
        mgr = MissionManager(ask_factory=lambda model: make_ask(MockLLM(delay=0.01)), overrides={**FAST, "data_dir": tmp})
        app = FastAPI()
        app.include_router(build_mission_router(None, mgr))
        with TestClient(app) as c:
            assert c.post("/api/mission/start", json={"brief": "x"}).status_code == 400
            mid = c.post("/api/mission/start", json={"brief": "Build a labour payment app", "max_agents": 6}).json()["id"]
            import time
            for _ in range(200):
                st = c.get(f"/api/mission/{mid}/state").json()
                if not st["live"]:
                    break
                time.sleep(0.1)
            assert st["status"] == "done" and st["total"] == 6 and st["events"] and st["plan"]["roles"]
            assert c.get(f"/api/mission/{mid}/file", params={"path": "app/core.py"}).json()["content"]
            assert c.get(f"/api/mission/{mid}/file", params={"path": "../../etc/passwd"}).status_code == 404
            z = zipfile.ZipFile(io.BytesIO(c.get(f"/api/mission/{mid}/download").content))
            assert "README.md" in z.namelist()
            assert c.get("/api/mission/list").json()["missions"][0]["id"] == mid
            assert c.post(f"/api/mission/{mid}/say", json={"text": "hello"}).status_code == 200    # finished -> revision, no more 409
            assert c.post("/api/mission/nope-nope-1/say", json={"text": "hello"}).status_code == 404


# --------------------------------------------------------------------------- verification + revision
def test_static_checks_catch_broken_flutter_project():
    from vira.mission import verify
    with tempfile.TemporaryDirectory() as tmp:
        ws = Workspace(tmp)
        ws.write("pubspec.yaml", "name: gym_app\nenvironment:\n  sdk: '>=3.0.0 <4.0.0'\ndependencies:\n  flutter:\n    sdk: flutter\n"
                                 "  provider: ^6.0.0\n bad_indent: [\n", "dev")
        ws.write("lib/main.dart", "import 'package:gym_app/missing.dart';\nimport 'package:hive/hive.dart';\nvoid main() { runApp(\n", "dev")
        probs = " | ".join(f"{i.path}: {i.problem}" for i in verify.static_issues(ws))
        assert "pubspec.yaml: invalid YAML" in probs
        ws.write("pubspec.yaml", "name: gym_app\nenvironment:\n  sdk: '>=3.0.0 <4.0.0'\ndependencies:\n  flutter:\n    sdk: flutter\n", "dev")
        probs = " | ".join(f"{i.path}: {i.problem}" for i in verify.static_issues(ws))
        assert "unclosed" in probs and "lib/missing.dart" in probs and "'hive'" in probs
        ws.write("lib/main.dart", "void main() { print('x'); }\n", "dev")
        assert verify.static_issues(ws) == []


def test_failed_command_is_routed_to_author_and_missing_tool_skipped():
    from vira.mission import verify
    with tempfile.TemporaryDirectory() as tmp:
        ws = Workspace(tmp)
        ws.write("lib/a.dart", "void main(){}\n", "ui_dev")
        res = verify.CmdResult(["flutter", "analyze"], 1, "  error • Undefined name 'x' • lib/a.dart:3:5 • undefined_identifier\n")
        issues = verify.issues_from_result(res, ["lib/a.dart"])
        roles = [{"key": "ui_dev"}, {"key": "qa_reviewer"}]
        fixes = verify.route_issues(issues, ws, {"ui_dev": 1, "qa_reviewer": 1}, roles)
        assert fixes[0]["owner"] == "ui_dev" and "lib/a.dart" in fixes[0]["files"]
        r = run(verify.run_cmd(["definitely-not-a-tool-xyz"], tmp))
        assert r.skipped and verify.issues_from_result(r, []) == []


def test_verify_loop_sends_errors_back_then_passes():
    """Mission writes invalid YAML once; the runner finds it and the author fixes it."""
    base = MockLLM(delay=0)
    state = {"bad": True}

    async def ask(prompt, **kw):
        out = (await base.generate(prompt)).text
        if "### WORK_TASK" in prompt and "TASK_ID: T3" in prompt and state["bad"]:
            state["bad"] = False
            return '<file path="app/config.yaml">\nkey: [unclosed\n</file><status>done</status>'
        if "### WORK_TASK" in prompt and "TASK_ID: V0-1-1" in prompt:
            return '<file path="app/config.yaml">\nkey: fixed\n</file><status>done</status>'
        return out

    async def scenario(tmp):
        m = _mission(tmp, ask, execute_checks=False)
        await asyncio.wait_for(m.run(), 60)
        return m

    with tempfile.TemporaryDirectory() as tmp:
        m = run(scenario(tmp))
        assert m.status == "done", (m.status, m.error)
        assert any(t.startswith("V0-1") for t in m.tasks) and m.ws.read("app/config.yaml").strip() == "key: fixed"
        assert "no checks applicable" in m.verification or "SKIPPED" in m.verification or m.verification


def test_say_after_finish_starts_revision_instead_of_409():
    async def scenario(tmp):
        mgr = MissionManager(ask_factory=lambda model: make_ask(MockLLM(delay=0)), overrides={**FAST, "data_dir": tmp, "execute_checks": False})
        m = await mgr.start("Build something useful for the client")
        await asyncio.wait_for(m._main, 60)
        assert m.finished.is_set()
        await m.say("add a monthly summary", "all")            # used to raise RuntimeError -> HTTP 409
        assert not m.finished.is_set()
        with pytest.raises(RuntimeError):
            await mgr.start("A second mission while revising")
        await asyncio.wait_for(m._main, 60)
        assert m.status == "done" and any(t.startswith("R1-") for t in m.tasks)
        # simulate a server restart: a fresh manager re-opens the mission from disk
        mgr2 = MissionManager(ask_factory=lambda model: make_ask(MockLLM(delay=0)), overrides={**FAST, "data_dir": tmp, "execute_checks": False})
        m2 = mgr2.resume(m.id)
        assert m2 and m2.finished.is_set() and m2.rev >= 1
        await m2.say("one more tweak")
        await asyncio.wait_for(m2._main, 60)
        assert m2.status == "done" and any(t.startswith(f"R{m2.rev}-") for t in m2.tasks)
        return True

    with tempfile.TemporaryDirectory() as tmp:
        assert run(scenario(tmp))
