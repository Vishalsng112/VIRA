"""LLM access for missions: reuse VIRA's providers (Ollama/OpenAI/Anthropic) from config.yaml,
plus an offline MockLLM so the whole pipeline can be demoed/tested without a model."""
import asyncio
import json
import re
from pathlib import Path
from typing import Any, Callable, Optional


def load_provider(config_path: str = "config.yaml", model: Optional[str] = None):
    """Create the provider for ``model`` (logical name from llm.models) or the default/first one."""
    import yaml
    from vira.llm.factory import create_provider
    cfg = (yaml.safe_load(Path(config_path).read_text(encoding="utf-8")) or {}).get("llm", {})
    models = cfg.get("models") or []
    if not models:
        raise RuntimeError(f"no models under llm.models in {config_path}")
    want = model or cfg.get("default_model")
    pick = next((m for m in models if want in (m.get("name"), m.get("model"))), models[0])
    return create_provider(pick)


def make_ask(provider) -> Callable[..., Any]:
    async def ask(prompt: str, **kw) -> str:
        resp = await provider.generate(prompt, **kw)
        return getattr(resp, "text", None) or str(resp)
    return ask


def make_ask_factory(config_path: str = "config.yaml"):
    cache = {}

    def factory(model: Optional[str] = None):
        if model not in cache:
            cache[model] = make_ask(load_provider(config_path, model))
        return cache[model]
    return factory


class MockLLM:
    """Deterministic fake model that speaks the mission protocol (no network)."""

    PLAN = {
        "project": "demo-app", "summary": "Demo product built by a mock team.", "stack": "Python 3, SQLite",
        "architecture": "app/core.py holds domain logic, app/ui.py the CLI, tests/test_core.py the tests.",
        "roles": [
            {"key": "architect", "title": "Solution Architect", "persona": "Principal engineer, 15y. Decisive.", "owns": "structure and interfaces"},
            {"key": "backend_dev", "title": "Backend Developer", "persona": "Senior Python dev. Talks in signatures.", "owns": "app/core.py"},
            {"key": "ui_dev", "title": "UI Developer", "persona": "Frontend engineer for data-entry apps.", "owns": "app/ui.py"},
            {"key": "qa_reviewer", "title": "QA Reviewer", "persona": "Sceptical QA engineer.", "owns": "tests"}],
        "tasks": [
            {"id": "T1", "title": "Architecture doc", "owner": "architect", "depends_on": [], "deliverables": ["docs/ARCHITECTURE.md"], "description": "Describe modules."},
            {"id": "T2", "title": "Core logic", "owner": "backend_dev", "depends_on": ["T1"], "deliverables": ["app/core.py"], "description": "Implement core."},
            {"id": "T3", "title": "CLI", "owner": "ui_dev", "depends_on": ["T1"], "deliverables": ["app/ui.py"], "description": "Implement CLI."},
            {"id": "T4", "title": "Tests", "owner": "qa_reviewer", "depends_on": ["T2"], "deliverables": ["tests/test_core.py"], "description": "Write tests."}]}

    def __init__(self, delay: float = 0.05):
        self.delay, self.calls = delay, 0

    async def generate(self, prompt: str, **kw):
        from vira.llm.base import LLMResponse
        await asyncio.sleep(self.delay)
        self.calls += 1
        return LLMResponse(text=self._answer(prompt), model="mock", usage={})

    def _answer(self, p: str) -> str:
        if "### MASTER_PLAN" in p:
            return json.dumps(self.PLAN)
        if "### REVIEW" in p:
            return '{"issues":[]}'
        if "### REVISE" in p:
            return json.dumps({"reply": "Change accepted.", "tasks": [{"owner": "backend_dev", "title": "Apply change",
                               "files": ["app/core.py"], "description": "Apply the requested change."}]})
        if "### README" in p:
            return "# Demo app\n\nRun `python -m app.ui`. Tests: `pytest`.\n\nGenerated offline by the mock model for pipeline testing.\n"
        if "### REPLY" in p:
            return '<message to="all">[DECISION] Answer: use integer paise for money everywhere.</message><status>done</status>'
        if "### WORK_TASK" in p:
            tid = re.search(r"TASK_ID: (\S+)", p).group(1)
            me = re.search(r"ROLE_KEY: (\S+)", p).group(1)
            dels = [d.strip() for d in re.search(r"DELIVERABLES: (.*)", p).group(1).split(",") if d.strip() and "(" not in d]
            peers = [k for k in re.findall(r"^- (\w+): ", p, re.M) if k not in (me, "master")]
            out = ""
            if tid == "T1":
                out += '<message to="all">[DECISION] Money is stored as integer paise; modules: core, ui.</message>'
            elif peers:
                out += f'<message to="{peers[0]}">[QUESTION] Which function signature should {me} call for {tid}?</message>'
            for d in dels:
                body = (f"# {d}\n\nMock content for {tid}.\n" if d.endswith(".md") else
                        f'"""{d} (mock, task {tid})"""\n\n\ndef main():\n    return "{tid}"\n')
                out += f'<file path="{d}">\n{body}</file>'
            out += f"<note>{me} finished {tid} using the shared paise decision.</note><status>done</status>"
            return out
        return "<status>done</status>"
