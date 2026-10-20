# Contributing to VIRA

Contributions are open and welcome. Thank you for taking the time to help build this.

VIRA's modular architecture means you can contribute to one part of the system — a sensor, an agent, a fix, or a doc improvement — without needing to understand the whole codebase. This guide gets you running locally and points you at the best places to start.

---

## Table of Contents

- [Getting Started](#getting-started)
- [Good First Issues](#good-first-issues)
- [Ways to Contribute](#ways-to-contribute)
- [Writing a New Agent](#writing-a-new-agent)
- [Writing a New Sensor](#writing-a-new-sensor)
- [Event Naming Rules](#event-naming-rules)
- [PR Checklist](#pr-checklist)
- [Getting Help](#getting-help)

---

## Getting Started

**Prerequisites:** Python 3.10+, Git, and either [Ollama](https://ollama.com) (for local LLM) or an OpenAI / Anthropic API key.

```bash
git clone https://github.com/Vishalsng112/VIRA.git
cd VIRA

pip install -r requirements.txt

# Pull a local model (skip if using OpenAI/Anthropic)
ollama pull llama3.2

python run.py
```

The dashboard is at `http://localhost:8000`. On first run, admin credentials are printed to the terminal.

> For the full architecture, event schemas, agent/sensor specs, and config reference, see **[docs/VIRA_DOCS.md](./docs/VIRA_DOCS.md)**.

---

## Good First Issues

These are the best places to start if you're new to the codebase. All are labelled [`good first issue`](https://github.com/Vishalsng112/VIRA/issues?q=is%3Aissue+is%3Aopen+label%3A%22good+first+issue%22) on GitHub.

### Agents
- **`good first issue`** · Build a **CPU spike alert agent** — subscribes to `sensor.hardware.state`, fires an alert when CPU exceeds a configurable threshold. Reference: `vira/agent/examples/AGENT_MONITOR.py`.
- **`good first issue`** · Build a **idle reminder agent** — detects when the user has been inactive for N minutes (via `sensor.system.state`) and sends a desktop notification.
- **`good first issue`** · Build a **project context agent** — watches `sensor.workspace.state` events and maintains a summary of the active project in memory.

### Sensors
- **`good first issue`** · Add a **battery sensor** — polls `psutil.sensors_battery()` and publishes `sensor.battery.state` events with charge level and plugged status.
- **`good first issue`** · Add a **clipboard sensor** — watches clipboard changes and publishes `sensor.clipboard.changed` events (Linux: use `xclip` or `wl-paste`).
- **`good first issue`** · Add a **audio sensor** — detects microphone/speaker activity and publishes `sensor.audio.state`.

### Testing & Quality
- **`good first issue`** · Add unit tests for `EventBus` — cover `subscribe`, `publish`, `unsubscribe`, and the wildcard subscriber path.
- **`good first issue`** · Add unit tests for `AgentRegistry` — cover `register`, `unregister`, `find_by_event`, `find_by_capability`.
- **`good first issue`** · Fix the duplicate `AgentMessage` class — there are two definitions (`vira/agent/messaging.py` and `vira/agent_orchestration/messages.py`) with different schemas. Consolidate or clearly separate them.

### Documentation
- **`good first issue`** · Add docstrings to all public methods in `vira/kernel/event_bus.py`.
- **`good first issue`** · Add docstrings to all public methods in `vira/agent/base.py`.
- **`good first issue`** · Write an end-to-end example in `docs/` showing a sensor → event → agent → LLM call flow.

### Improvements
- **`enhancement`** · Make `WorkflowEngine._resolve_input` support `{{ context.key }}` and `{{ results.step_id }}` placeholder resolution (currently a stub).
- **`enhancement`** · Add a `pending_events()` implementation to `EventBus` — currently returns 0 always (the internal queue attribute name is wrong).
- **`enhancement`** · Add X11 support to `UserActivitySensor` (currently Wayland-only).

---

## Ways to Contribute

| Area | What's needed |
|------|--------------|
| **Agents** | New agents that subscribe to existing events and do useful things |
| **Sensors** | New sensors for data sources not yet covered (battery, clipboard, audio, GPU) |
| **Tests** | Unit and integration tests — coverage is low right now |
| **Bug fixes** | Open issues labelled `bug` |
| **Documentation** | Docstrings, examples, guides |
| **Platform support** | Windows and macOS compatibility (Iteration 2 goal) |
| **Performance** | Memory/CPU footprint of sensors and the event loop |

If you want to work on something not listed here, open an issue first to discuss it — happy to give feedback before you invest time writing code.

---

## Writing a New Agent

1. Create your file anywhere importable, e.g. `vira/agent/my_agents/my_agent.py`.
2. Extend `BaseAgent` and implement all four abstract methods.

```python
from vira.agent.base import BaseAgent
from vira.agent_orchestration.registry import AgentCapability

class MyAgent(BaseAgent):
    def __init__(self, runtime):
        super().__init__(
            name="MyAgent",
            description="One sentence describing what this agent does.",
            runtime=runtime
        )
        self._capabilities = [
            AgentCapability(name="my_capability", description="What it does")
        ]
        # Kernel event types this agent will react to
        self._subscribed_events = ["sensor.hardware.state"]
        # Set to a float (seconds) for periodic agents; None for event-only
        self._interval_seconds = None

    async def think(self, context, **kwargs) -> dict:
        """Analyse the event and decide on intent."""
        event = kwargs.get("event")
        return {"intent": "act", "data": event.data}

    async def plan(self, thought, **kwargs) -> list:
        """Turn intent into a list of action steps."""
        return [{"action": "call_llm", "prompt": str(thought["data"])}]

    async def act(self, plan, **kwargs) -> list:
        """Execute the plan. Call LLM, tools, or external APIs here."""
        results = []
        for step in plan:
            if step["action"] == "call_llm":
                response = await self.runtime.call_llm(self.agent_id, step["prompt"])
                results.append(response)
        return results

    async def reflect(self, result, **kwargs) -> dict:
        """Evaluate the result. Optionally store to memory."""
        return {"done": True}
```

3. Register it in `config.yaml`:

```yaml
agents:
  - name: MyAgent
    module: vira.agent.my_agents.my_agent
    class: MyAgent
    enabled: true
    config:
      my_param: value
```

4. Restart VIRA. Your agent will appear in the dashboard and begin receiving events.

For more detail on the agent lifecycle, state machine, and `AgentRuntime` methods, see [docs/VIRA_DOCS.md → Agent Specification](./docs/VIRA_DOCS.md#agent-specification).

---

## Writing a New Sensor

1. Create your file in `vira/sensors/my_sensor.py`.
2. Extend `BaseSensor`, implement `start`, `stop`, and `read`, and publish events via the dispatcher.

```python
import asyncio
from vira.sensors.base_sensor import BaseSensor
from vira.kernel.event_bus import Event

class MySensor(BaseSensor):
    def __init__(self, interval: float, event_bus, dispatcher):
        super().__init__(name="my_sensor")
        self._interval = interval
        self._dispatcher = dispatcher

    async def start(self) -> None:
        self._running = True
        asyncio.create_task(self._poll())

    async def stop(self) -> None:
        self._running = False

    async def read(self) -> dict:
        """Read and return raw data as a dict."""
        return {"value": 42}

    async def _poll(self):
        while self._running:
            data = await self.read()
            await self._dispatcher.publish(Event(
                type="sensor.my_sensor.state",   # must follow domain.entity.action
                data=data,
                source=self.name
            ))
            await asyncio.sleep(self._interval)
```

3. Register the factory in `vira/kernel/kernel.py` inside `_register_builtin_sensors()`:

```python
self.register_sensor("my_sensor", lambda cfg, eb, disp, mm: MySensor(
    interval=cfg.get("interval", 5.0),
    event_bus=eb,
    dispatcher=disp
))
```

4. Enable it in `config.yaml`:

```yaml
sensors:
  - name: my_sensor
    enabled: true
    interval: 5.0
```

---

## Event Naming Rules

All events must follow the **`domain.entity.action`** pattern. This is enforced by convention — the `EventBus` accepts any string, so it is your responsibility as a contributor to get it right.

| Pattern | Example | ✅ / ❌ |
|---------|---------|--------|
| `domain.entity.action` | `sensor.battery.state` | ✅ |
| `domain.entity.action` | `agent.my_agent.result` | ✅ |
| `domain.entity.action` | `kernel.ready` | ✅ |
| No namespace | `batterysensor` | ❌ |
| CamelCase | `BatteryEvent` | ❌ |
| Only two parts when three are needed | `sensor.state` | ❌ |

**Reserved namespaces** (do not use for custom events):

| Namespace | Owner |
|-----------|-------|
| `kernel.*` | Kernel only |
| `agent.registered`, `agent.unregistered` | AgentManager only |
| `workflow.*` | WorkflowEngine only |

---

## PR Checklist

Before opening a pull request, confirm:

- [ ] The code runs without error with `python run.py` and the default `config.yaml`
- [ ] New events follow the `domain.entity.action` naming convention
- [ ] New agents implement all four `BaseAgent` abstract methods (`think`, `plan`, `act`, `reflect`)
- [ ] New sensors publish events via `dispatcher.publish(...)`, not `event_bus.publish(...)` directly
- [ ] No hardcoded file paths — use `config_manager.get(...)` or environment variables
- [ ] New `config.yaml` keys are documented in `docs/VIRA_DOCS.md`
- [ ] If adding a dependency, it is added to `requirements.txt`

---

## Getting Help

- **Question about the codebase?** Open an issue with the `question` label. Include your Python version, OS, and relevant terminal log lines.
- **Not sure if your idea fits?** Open an issue before writing code — happy to give early feedback.
- **Found a bug?** Open an issue with the `bug` label and include steps to reproduce.

