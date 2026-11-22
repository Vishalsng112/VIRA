# VIRA Plugin SDK

VIRA plugins are normal Python packages that declare a manifest. A plugin can
add tools, HTTP routes, sensors, agents, prompt-defined specialists, event
handlers, scheduled jobs and namespaced state without importing kernel
internals.

## Directory layout

```
my-plugin/
├── vira-plugin.json
└── plugin.py
```

```json
{
  "id": "acme.weather",
  "name": "Weather Tools",
  "version": "1.2.0",
  "api_version": "1",
  "description": "Weather lookup and forecasts.",
  "author": "Acme",
  "license": "MIT",
  "homepage": "https://example.com/weather",
  "entrypoint": "plugin.py:WeatherPlugin",
  "permissions": ["tools.register", "http.routes", "storage"],
  "categories": ["weather", "productivity"],
  "requires": {"vira": ">=0.2.0"},
  "config": {"units": "metric"}
}
```

`vira-plugin.toml` and `plugin.json` are also accepted. The entrypoint can be
`plugin.py:Class` or `module:Class` for a pip-installed package.

## Lifecycle

```python
from vira.plugins.api import Plugin

class WeatherPlugin(Plugin):
    async def setup(self, ctx):
        # register everything here
        ...

    async def start(self):
        ...

    async def stop(self):
        ...
```

- `setup(ctx)` runs once before `start`.
- `start()` starts background work.
- `stop()` releases resources. Scheduled tasks and event subscriptions are
  also cancelled by the manager.
- A failed plugin is isolated: it is marked `error`, other plugins still load.

## Permissions

The manifest must declare every capability used. The server allow-list can
deny a permission, in which case the plugin is not loaded.

| Permission | Allows |
|---|---|
| `tools.register` | read-only tool registration |
| `tools.register.write` | tools with `write`/`execute`/`admin` actions |
| `sensors.register` | collector/sensor registration |
| `agents.register` | runtime agent and prompt-definition registration |
| `events.read` | subscribe to kernel events |
| `events.publish` | publish kernel events |
| `http.routes` | mount an API router |
| `storage` | namespaced key/value state and data directory |
| `jobs.schedule` | periodic async jobs |
| `config.read` | read manifest config |

Server policy lives in `plugins.allowed_permissions`,
`plugins.denied_permissions` and `plugins.allow_write_tools` in `config.yaml`.

## Registering a tool

```python
from pydantic import Field
from vira.tooling import BaseTool, StrictModel, ToolContext

class ForecastInput(StrictModel):
    city: str = Field(min_length=1)

class ForecastOutput(StrictModel):
    text: str

class ForecastTool(BaseTool):
    namespace = "acme"
    name = "forecast"
    title = "Weather forecast"
    description = "Get a weather forecast for a city."
    when_to_use = "Use for current or future weather."
    when_not_to_use = "Do not use for historical climate analysis."
    category = "weather"
    tags = ("weather", "forecast", "city")
    input_model = ForecastInput
    output_model = ForecastOutput

    async def run(self, params: ForecastInput, context: ToolContext) -> ForecastOutput:
        return ForecastOutput(text=f"Sunny in {params.city}")
```

`ctx.register_tool(ForecastTool())` makes `acme.forecast` available immediately.
It appears in the catalog, `tool_search` and agent prompts on the next request.

## HTTP routes

```python
from fastapi import APIRouter

router = APIRouter()

@router.get("/status")
async def status():
    return {"ok": True}

ctx.register_router(router)
```

Every plugin router is mounted at:

```
/api/v1/ext/<plugin-id>/...
```

Authentication is the plugin's responsibility. Use the shared dependencies if
you need a user; document the routes and validate input carefully.

## Sensors

```python
def factory(sensor_config, event_bus, dispatcher, metrics):
    return MySensor(...)

ctx.register_sensor("my_sensor", factory, {"interval": 30})
```

Plugin sensor events use the same validated ingestion path as built-in
sensors. The server-local device identity is applied automatically.

## Agents

Runtime agents must subclass `vira.agent.base.BaseAgent`:

```python
agent_id = await ctx.register_agent(MyAgent(ctx.runtime))
```

Prompt-defined specialists are simpler and safer:

```python
from vira.agent.definitions import AgentDefinition

ctx.register_agent_definition(AgentDefinition(
    name="weather_brief",
    description="Use for weather briefings.",
    prompt="You are a concise weather briefer. Use the forecast tool.",
    tools=["acme_forecast"],
    max_steps=3,
))
```

They are removed automatically when the plugin is disabled or unloaded.

## Events and jobs

```python
async def on_event(event):
    ...

ctx.on_event("device.battery.state", on_event)

async def sweep():
    ...

ctx.schedule(sweep, interval_seconds=300, run_immediately=True)
await ctx.emit("acme.weather.updated", {"city": "Pune"})
```

## State and data

```python
ctx.set_state("last_city", "Pune")
city = ctx.get_state("last_city", "London")

path = ctx.data_dir / "cache.json"   # ./data/plugins/<plugin-id>/
```

State is SQLite/PostgreSQL-backed and namespaced per plugin.

## UI contributions

A manifest can advertise a small front-end contribution without shipping code
into the core admin bundle:

```json
"ui": {
  "slots": ["settings", "dashboard"],
  "entry": "/ui/panel.js",
  "style": "/ui/panel.css",
  "label": "Weather"
}
```

`GET /api/v1/plugins/ui` returns active contributions with the plugin's mount
prefix (`/api/v1/ext/<plugin-id>`), so an admin shell can load the script or
open the route. Mount scripts only from trusted plugins and keep them free of
secrets.

## Managing plugins

Administrator API:

```text
GET    /api/v1/plugins                 list discovered/loaded plugins
POST   /api/v1/plugins/discover        rescan configured directories
GET    /api/v1/plugins/sdk             SDK/API metadata
GET    /api/v1/plugins/{id}
POST   /api/v1/plugins/{id}/enable
POST   /api/v1/plugins/{id}/disable
POST   /api/v1/plugins/{id}/reload
DELETE /api/v1/plugins/{id}            forget record (files are kept)
```

Enabling, disabling and reloading take effect without restarting the server for
tools, agents, event handlers and jobs. New HTTP routers are mounted at startup;
restart to add or remove route modules.

Configuration:

```yaml
plugins:
  directories:
    - ./examples/plugins
  allow_write_tools: true
  denied_permissions: []
  data_dir: ./data/plugins
```

`VIRA_PLUGIN_PATH` adds colon-separated directories. Packages can also expose a
`vira.plugins` entry point.

## Reference plugins and MCP example

The repository maintains three complete plugin examples and one MCP server
example, all covered by `vira/tests/test_examples.py`:

| Example | Demonstrates |
|---|---|
| `examples/plugins/hello_world` | read-only tool, HTTP route, persisted state |
| `examples/plugins/reading_list` | read/write tools, route, state, prompt specialist |
| `examples/plugins/focus_budget` | event subscription, scheduled job, tool, route |
| `examples/mcp/notes_server.py` | real MCP stdio server with tools and a resource |

Run them with:

```bash
python3 -m unittest vira.tests.test_examples -v
```

## Versioning and compatibility

- `api_version` is the SDK contract. This server supports `"1"`.
- Bump a plugin's `version` for every release.
- `requires` supports a small semver subset: `>=`, `>`, `<=`, `<`, `==`, `^`,
  `~`, comma-separated ranges and `*`.
- Declare `{"vira": ">=0.2.0"}` when a plugin needs newer core APIs.
- Plugin dependencies are loaded first and cycles are refused.

## Security guidance

- Request the smallest permission set.
- Never load remote code at runtime.
- Do not log secrets or raw device events.
- Return errors as data; do not crash the host process.
- Treat plugin code as trusted local code: plugins run in-process.
