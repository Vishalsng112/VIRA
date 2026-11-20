# Event reference

All VIRA events share one structure, defined in `vira/kernel/event_bus.py`.
Events use a `domain.entity.action` naming convention and are published through
the `EventDispatcher` so security and the pipeline run first.

For the full dataclass, priority levels and publishing examples, see
[Event standard](../dev/architecture/framework.md#event-standard-kernel-events).

## Namespaces

| Namespace | Examples | Emitted by |
|---|---|---|
| `sensor.*` | `sensor.hardware.state`, `sensor.system.state` | Sensors |
| `kernel.*` | `kernel.ready`, `kernel.shutdown` | Kernel |
| `agent.*` | `agent.registered`, `agent.unregistered` | AgentManager |
| `user.*` | `user.message`, `user.activity` | User-activity sensor / API |
| `fs.*` | `fs.file.created`, `fs.file.modified`, `fs.file.deleted` | FileSystemSensor |
| `workflow.*` | `workflow.started`, `workflow.completed`, `workflow.failed` | WorkflowEngine |
| `memory.*` | `memory.stored`, `memory.retrieved` | MemoryManager |
| `tool.*` | `tool.invoked`, `tool.result` | ToolExecutor |
| `device.*` | `device.enrolled`, `device.focus.session` | Device service / VIRA Link |

## Priority levels

| Priority | Value | When to use |
|---|---|---|
| `LOW` | 0 | Background metrics, periodic logs |
| `NORMAL` | 1 | Default for sensor readings |
| `HIGH` | 2 | User-triggered actions |
| `CRITICAL` | 3 | Security violations, kernel errors, OOM signals |

## Durability

Set `durable=True` on state-changing events. The dispatcher records them in the
SQLite outbox before delivery and the kernel retries pending rows after restart.
High-frequency sensor telemetry stays non-durable by default.

Consumers that update durable state should use `vira.kernel.handle_idempotently`
so a retried event is applied once per consumer.
