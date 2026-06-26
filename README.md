<div align="center">

# VIRA

### An AI-OS / Agentic OS layer for your machine

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](#license)
[![Status](https://img.shields.io/badge/status-kernel%20in%20development-brightgreen)](#development-status)
[![Platform](https://img.shields.io/badge/platform-Linux-blue)](#platform-support)
[![Privacy](https://img.shields.io/badge/cloud-none-success)](#privacy-first)

*No cloud. No telemetry. Nothing leaves your machine.*

</div>

---

## Table of Contents

- [What is VIRA?](#what-is-vira)
- [Why it exists](#why-it-exists)
- [Core Principles](#core-principles)
- [How it works](#how-it-works)
- [Quick Start](#quick-start)
- [Project Structure](#project-structure)
- [Development Status](#development-status)
- [Roadmap](#roadmap)
- [Contributing](#contributing)
- [How VIRA differs from Claude Code, Codex & Copilot](#how-vira-differs-from-claude-code-codex--copilot)
- [License](#license)

---

## What is VIRA?

VIRA is an open-source **AI-OS layer** — also described as an Agentic OS layer — that provides the necessary architecture to:

- Build and maintain **live Context** that models both your system state and your behaviour over time
- **Automatically synthesize** new system apps, tools, and agents from natural language using a verification-based programming language and a provided Domain Specific Language (DSL)
- **Verify correctness** of generated tools before they ever run — not "here's some code, good luck", but something you can actually trust

Everything runs **100% locally**. Nothing is sent to the cloud.

VIRA is built for everyone: general-purpose users who want tools that just work, developers who want a context-rich foundation to build on, and open-source contributors who want to extend and improve the framework.

---

## Why it exists

Every AI tool you use today starts blind. It doesn't know what you're working on, what's running on your system, how you work, or what you need. You re-explain your own computer to it every single time — and it forgets everything the moment the session ends.

VIRA exists to fix that at the root. It runs as a continuously-updating kernel, senses your environment and your behaviour, and turns that into structured, AI-ready context. The longer-term goal is a system where you describe what you want in plain language and VIRA generates and verifies the right tool to get it done — for everyone, not just developers.

---

## Core Principles

| Principle | What it means |
|---|---|
| Privacy-first | No telemetry, no cloud calls. Everything stays on your device. |
| Open source | MIT licensed — free to study, fork, and build on. |
| Context as infrastructure | Context isn't bolted onto an AI model as an afterthought — it's the core data structure the kernel is built around. |
| User-aware, not just machine-aware | VIRA models how *you* use your system — your workflow, rhythms, and intent — not just what's running on the hardware. |
| Trust through verification | Generated tools will have their correctness checked before you run them. You shouldn't have to hope the AI got it right. |

---

## How it works

VIRA is built around focused **sensors**, each watching one part of your system. Observations flow through a shared **event bus** into a context engine that builds a unified, constantly-updating model of your machine and behaviour.

| Sensor | What it watches |
|---|---|
| System | CPU, memory, load, OS state |
| Hardware | Hardware metrics and resource usage |
| Process | Running processes and their lifecycle |
| Network | Network activity and connectivity |
| Application | Which apps are active and what they're doing |
| Workspace | File system and workspace changes |
| Project | Project structure and metadata |
| Activity | User behaviour patterns and workflow rhythms |
| Context | Aggregates everything into higher-level context |

```
Sensors  →  Event Bus  →  Context Engine  →  AI-ready context (machine + behaviour)
```

The architecture is intentionally modular and follows microservice principles — individual components can be optimized, rewritten, or extended without touching the rest of the system.

---

## Quick Start

VIRA currently ships as a Docker image — the fastest way to run the kernel today, and the easiest way to verify that nothing leaves your machine.

```bash
git clone https://github.com/Vishalsng112/VIRA
cd VIRA
docker compose up
```

This starts the kernel and its sensors as a background service. No data leaves the container's network namespace.

> **For open-source contributors:** Detailed instructions on how to set up the development Docker container for local contribution will be provided soon. Watch this space.

---

## Project Structure

```
├── config.yaml
├── cookies.ck
├── data
│   ├── checkpoints
│   │   └── latest.json
│   ├── user_activity
│   └── vira.db
├── Dockerfile
├── get_cookies.sh
├── helpers
│   └── Testing.ipynb
├── README.md
├── requirements.txt
├── run.py
└── vira
    ├── actions
    │   ├── base_action.py
    │   └── __init__.py
    ├── agent
    │   ├── base.py
    │   ├── examples
    │   │   ├── AGENT_MONITOR.py
    │   │   └── simple_agent.py
    │   ├── __init__.py
    │   └── messaging.py
    ├── agent_orchestration
    │   ├── base.py
    │   ├── capability_registry.py
    │   ├── events.py
    │   ├── __init__.py
    │   ├── message_bus.py
    │   ├── messages.py
    │   ├── metrics.py
    │   ├── planner.py
    │   ├── registry.py
    │   ├── router.py
    │   ├── scheduler.py
    │   └── workflow.py
    ├── agent_runtime
    │   ├── context.py
    │   ├── __init__.py
    │   └── runtime.py
    ├── api
    │   ├── app.py
    │   └── __init__.py
    ├── auth
    │   ├── auth.py
    │   ├── database.py
    │   └── models.py
    ├── cognition
    │   ├── base_cognition.py
    │   └── __init__.py
    ├── content
    │   ├── base.py
    │   ├── __init__.py
    │   └── manager.py
    ├── __init__.py
    ├── kernel
    │   ├── config_manager.py
    │   ├── context_manager.py
    │   ├── event_bus.py
    │   ├── event_dispatcher.py
    │   ├── event_pipeline.py
    │   └── __init__.py
    ├── sensors
    │   ├── activity_sensor.py
    │   ├── base_sensor.py
    │   ├── hardware_sensor.py
    │   ├── __init__.py
    │   ├── network_sensor.py
    │   ├── process_sensor.py
    │   ├── project_sensor.py
    │   ├── system_sensor.py
    │   ├── user_activity_sensor.py
    │   └── workspace_sensor.py
    ├── tests
    │   └── test_load_monitor.py
    ├── tools
    │   ├── base.py
    │   ├── connection.py
    │   ├── executor.py
    │   ├── __init__.py
    │   ├── mcp_server.py
    │   ├── mcp_tool.py
    │   └── registry.py
    └── web
        └── static
            ├── app.js
            ├── auth.css
            ├── dashboard.html
            ├── forgot.html
            ├── login.html
            ├── setup.html
            └── style.css
```

---

## Development Status

**Current phase: maturing the kernel.**

The core kernel — event bus, sensors, context engine, agent orchestration, and kernel APIs — is implemented and working end-to-end. The focus right now is stabilizing and hardening this foundation before moving to the next layer.

- Event bus architecture — functional
- Sensor framework — functional, all sensors implemented
- Context aggregation — functional
- Agent orchestration and runtime — functional
- First event-driven agent — implemented as an end-to-end validation harness
- Most sensors currently use periodic polling (event-driven sensing comes next)
- Linux (Wayland) is the only supported platform for now

Once the kernel is solid, work will begin on the infrastructure for building agents, the DSL, and integration of a verification-based language (Dafny) so users can generate any app, tool, or agent they need from natural language — backed by strong reasoning models.

**On the implementation language:** the project is currently written entirely in Python. Core parts will later be rewritten in Rust — system-level components in Rust, exposed to the rest of the framework as Python modules. This keeps the contribution surface accessible while allowing the kernel and runtime to be progressively optimized without disrupting the broader codebase.

---

## Roadmap

### Iteration 1 — Functional Kernel *(mostly complete)*

Build a complete, stable kernel that can sense, aggregate, and manage context.

- Sensor framework, event bus, context engine, state management, local AI integration, kernel APIs
- First event-driven agent built on top as a validation harness

### Iteration 2 — Behaviour Awareness and Production Readiness

- Behaviour modelling — move from machine state to user patterns
- MCP-native exposure — expose context as an MCP server so any compatible host or agent can connect
- Event-driven sensing — replace polling with OS-level events
- Security and transparency layer — permission model, local dashboard
- Runtime optimization — lower memory/CPU footprint, better concurrency

**Cross-platform support** is a key goal here. VIRA is currently developed on Linux (Wayland). The plan is to support Linux (X11), Windows, and macOS as well.

The chosen approach: VIRA will run as a container with the necessary privileges granted. This works cleanly across platforms because Windows has WSL2 and macOS now ships its own lightweight container tooling. Rather than maintaining separate native ports, a well-configured container gives users on all three platforms the same experience with minimal friction. Platform-specific container setup instructions will be provided for each target OS.

### Iteration 3 — On-Demand Tool Generation

Once the kernel and trust layer are solid, this is where VIRA becomes useful for everyone.

- Intent understanding — parse natural language into structured goals
- Agent and tool synthesis — generate the right agent, script, or mini-app using the kernel's knowledge of your machine and habits, via the DSL and Dafny-based verification
- Verification layer — formal checks that generated tools do what they claim, and nothing else
- Sensor SDK — versioned interface for third-party sensors (browser, Docker, IDE, cloud CLI)
- Native packaging — `.deb` / `AppImage` for Linux, then others

**At this point, the framework will be ready for developers and open-source contributors to add support for new platforms, build new features, and optimize existing components.** The modular architecture is designed specifically to make this tractable — you shouldn't need to understand the whole system to improve one part of it.

---

## Contributing

VIRA is currently built and maintained by a single developer, and the core architecture is still moving fast — so direct code contributions are limited for now.

That said, issues, discussions, design feedback, and ideas are welcome. Once the kernel matures, contributions around agents, integrations, tooling, and ecosystem features will be actively encouraged. Open-source contributor setup docs (Docker dev environment, contribution workflow) are coming soon.

---

## How VIRA differs from Claude Code, Codex & Copilot

The question comes up a lot. Claude Code, Codex, and Copilot are coding assistants. VIRA is not a coding assistant — it's the awareness layer that sits underneath one.

| | Claude Code / Codex / Copilot | VIRA |
|---|---|---|
| What it is | An AI agent that writes and reasons about code | A background kernel that senses your machine and models your behaviour |
| Scope | Focused on a codebase or repo | System-wide: apps, processes, workspaces, hardware, activity patterns |
| Lifespan | Session-based | Always-on — continuously running and updating |
| Where intelligence runs | Cloud-hosted LLM | Local-first — sensing and context-building happen entirely on-device |
| Relationship to AI models | Is the AI agent | Vendor-neutral infrastructure that feeds context to any AI agent |
| Future direction | Better code generation | On-demand tool generation with correctness verification |

Claude Code and Copilot are good at acting once told what to do. VIRA's job is to make sure any AI actually knows what's going on and who it's working with before it acts — and eventually, to generate and verify the tools that get the job done without requiring the person asking to be a developer.

---

## License

Released under the **MIT License**. See [LICENSE](./LICENSE) for details.

---

<div align="center">

*Built for a future where AI understands your machine, knows how you work, and builds what you need — verifiably, locally, and for everyone.*

</div>
