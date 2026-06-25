<div align="center">

# 🧠 VIRA

### The AI kernel that understands your machine — and you

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](#-license)
[![Status](https://img.shields.io/badge/status-kernel%20functional-brightgreen)](#-development-status)
[![Platform](https://img.shields.io/badge/platform-Linux-blue)](#-platform-support)
[![Privacy](https://img.shields.io/badge/cloud-none-success)](#-privacy-first)

*No cloud. No telemetry. No data leaving your machine — ever.*

</div>

---

## 📖 Table of Contents

- [The Pitch](#-the-pitch)
- [What is VIRA?](#-what-is-vira)
- [Why it exists](#-why-it-exists)
- [Core Principles](#-core-principles)
- [How it works](#-how-it-works)
- [Quick Start](#-quick-start)
- [Development Status](#-development-status)
- [The Vision](#-the-vision)
- [Roadmap & Future Directions](#-roadmap--future-directions)
- [Contributing](#-contributing)
- [How VIRA is different from Claude Code, Codex & Copilot](#-how-vira-is-different-from-claude-code-codex--copilot)
- [License](#-license)

---

## 🎯 The Pitch

Every AI tool you open today is reasoning blind. It doesn't know what you've been working on, what's running on your machine, how you work, or what you actually need. You spend the first five minutes re-explaining your own computer to it — every single time.

**VIRA fixes that at the root.**

It runs quietly in the background and builds two things simultaneously: a live model of your **machine** (projects, processes, files, apps, hardware), and a model of **you** — your patterns, your workflow, your habits, what you tend to do next. Together, these give any AI tool the context it would otherwise have to ask you for.

But that's just where VIRA starts.

> **The future we're building toward:** You describe what you want to accomplish — in plain language. VIRA understands your goal, generates the right app, tool, or agent to get it done, and then *verifies it for correctness* before handing it to you. Not "here's some code, good luck" — but a working, trusted tool you can actually rely on. AI that doesn't just assist — it *delivers*.

This is what it looks like when a personal AI becomes actually useful for everyone, not just developers.

---

## 🚀 What is VIRA?

**VIRA** is an open-source, **local-first AI kernel** — a background system that continuously watches and understands two things: what's happening on your computer, and how *you* use it.

It builds a live, structured picture of your machine and your behaviour, and makes that understanding available to AI agents and tools — so they can act on real context instead of guessing. Today, that means every AI tool you use gets smarter without you lifting a finger. Tomorrow, it means VIRA can build and verify the tools you need on demand.

Everything runs **100% locally**. Nothing is sent to the cloud.

---

## 🎯 Why it exists

Most AI assistants today are smart, but blind. They don't know:

- 📁 what project you're currently working on
- 💻 what's running on your system right now
- 🔄 what just changed in your workspace
- 🧠 how you work, what patterns define your day
- 🕐 what you were doing for the last hour — or the last week

And none of them remember any of it between sessions.

**VIRA exists to fix that.** It runs as a continuously-updating kernel that senses your environment and your behaviour, and turns that raw signal into structured, AI-ready context — so the AI tools you use stop starting from zero every time.

---

## 🧩 Core Principles

| Principle | What it means |
|---|---|
| 🔒 **Privacy-first** | No telemetry, no cloud calls, no hidden network traffic. Everything stays on your device. |
| 🌍 **Open source** | Released under the MIT License — free to study, fork, and build on. |
| 🧠 **Context as a first-class citizen** | Context isn't an afterthought bolted onto an AI model — it's the core data structure the whole kernel is built around. |
| 👤 **You-aware, not just machine-aware** | VIRA doesn't just watch your system. It learns how *you* use it — your workflow, your rhythms, your intent. |
| ✅ **Trust through verification** | The future of this project isn't just generating tools — it's generating tools whose correctness can be checked. You shouldn't have to hope the AI got it right. |

---

## ⚙️ How it works

VIRA is built around small, focused **sensors** that each watch one part of your system. Their observations flow into a shared **event bus**, which builds a unified, constantly-updating model of your machine's state — and over time, your patterns within it.

| Sensor | What it watches |
|---|---|
| 🖥️ System Sensor | CPU, memory, load, OS state |
| 🔧 Hardware Sensor | Hardware metrics & resource usage |
| ⚡ Process Sensor | Running processes & their lifecycle |
| 🌐 Network Sensor | Network activity & connectivity |
| 📱 Application Sensor | Which apps are active and doing what |
| 📂 Workspace Sensor | File system & workspace changes |
| 📦 Project Sensor | Project structure & metadata |
| 👤 Activity Sensor | User behaviour patterns & workflow rhythms |
| 🧠 Context Sensor | Aggregates everything into higher-level context |

```
 Sensors  →  Event Bus  →  Context Engine  →  AI-ready context (machine + behaviour)
```

---

## 🐳 Quick Start

VIRA currently ships as a **Docker image** — this is the fastest way to run the kernel today, and it keeps the "nothing leaves your machine" claim easy to verify: the container has no reason to make outbound calls, and you can check that yourself.

```bash
git clone https://github.com/Vishalsng112/vira_framework
cd vira
docker compose up
```

This starts the kernel and its sensors as a background service on your machine. No data leaves the container's network namespace.

> Native packages (`.deb`, `AppImage`, `pip install vira`) are planned once the kernel architecture stabilizes further — see [Roadmap](#-roadmap--future-directions). Docker is the recommended way to run VIRA for now, for both users and contributors.

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

## 📍 Development Status

**Current phase: Kernel Foundation — functionally complete.** The core kernel (event bus, sensors, context engine, agent orchestration, and kernel APIs) is implemented and working end-to-end.

- ✅ Event bus architecture — functional
- ✅ Sensor framework — functional, all sensors implemented
- ✅ Context aggregation — functional
- ✅ Agent orchestration & runtime — functional
- ✅ First event-driven agent — implemented, used to validate the kernel end-to-end
- ⏳ Most sensors currently use periodic polling (event-driven sensing comes next)
- 🐧 Linux is the only supported platform for now

Iteration 1 is largely done. Performance tuning is intentionally **not** the priority yet — that comes in the next phase.

---

## 🌅 The Vision

VIRA's near-term goal is to be **assumed infrastructure**: the local context layer you install once and every AI tool you add afterward just finds it already there — aware of your machine, aware of you.

But the larger goal is something more ambitious.

**Imagine this:** you open VIRA and say — *"I want a tool that monitors my focus time and blocks distracting apps when I'm in deep work."* You don't write code. You don't configure anything. VIRA understands your intent, knows your system, knows your habits, and builds the right agent for the job. Then — before you ever run it — it verifies the tool for correctness: does it actually do what you asked? Does it do *only* what you asked?

You get a working, trusted tool. Not a code snippet. Not a prototype. Something you can actually rely on.

This is what it means for AI to be useful for *everyone* — not just people who can read a stack trace. A personal AI that doesn't just suggest — it delivers, and it proves it.

That's where this is headed.

---

## 🗺️ Roadmap & Future Directions

### Iteration 1 — Functional Kernel *(mostly complete)*
Build a complete, stable kernel that can sense, aggregate, and manage context.
- Sensor framework · Event bus · Context engine · State management · Local AI integration · Kernel APIs
- ✅ A first event-driven agent has been built on top of the kernel as a validation/testing harness for the architecture.

### Iteration 2 — Behaviour Awareness & Production Readiness
Turn the working kernel into something fast, efficient, and genuinely self-aware.

- **Behaviour modelling** — move beyond machine state into user patterns: what you work on, how you work, what comes next
- **MCP-native exposure** — expose the context engine as an MCP server so any MCP-compatible host or agent can connect with no custom integration
- **Event-driven sensing** — replace polling with real OS-level events (file system notifications, process events, system event streams)
- **Security & transparency layer** — a documented permission model for what connected agents can see and do, plus a local dashboard that makes "nothing leaves this machine" something you can watch happen
- **Runtime optimization** — lower memory/CPU footprint, better concurrency, less duplicate work
- **Cross-platform support:**

  | OS | Status |
  |---|---|
  | Linux | ✅ Supported |
  | macOS | 🚧 Planned |
  | Windows | 🚧 Planned |

### Iteration 3 — On-Demand Tool Generation *(the big one)*
Once the kernel and trust layer are solid, build the layer that makes VIRA useful for everyone.

- **Intent understanding** — parse natural language requests into structured goals VIRA can act on
- **Agent & tool synthesis** — generate the right agent, script, or mini-app to accomplish a stated goal, using the kernel's knowledge of your machine and your behaviour to get it right the first time
- **Verification layer** — formal or semi-formal checks that generated tools do what they claim and nothing else; the correctness guarantee that makes AI-generated tools trustworthy
- **Sensor SDK** — a versioned interface so third-party sensors (browser tabs, Docker, IDE state, cloud CLI context) can be added without touching kernel internals
- **Native packaging** — `.deb` / `AppImage` for Linux, then installers as cross-platform support lands
- **Community contributions** — once the architecture is stable, open up sensor and integration contributions properly (see [Contributing](#-contributing))

---

## 🤝 Contributing

VIRA is currently built and maintained by a **single developer**, and the core architecture is still evolving quickly — so direct code contributions are intentionally limited for now.

That said, **issues, discussions, design feedback, and ideas are very welcome.** Once the kernel architecture matures, contributions around AI integrations, tooling, and ecosystem features will be actively encouraged.

---

## 🆚 How VIRA is different from Claude Code, Codex & Copilot

This is the question people ask most, so here it is directly: **tools like Claude Code, OpenAI Codex, and GitHub Copilot's agents are coding assistants. VIRA is not a coding assistant — it's the awareness layer underneath one.**

| | Claude Code / Codex / Copilot Agents | **VIRA** |
|---|---|---|
| **What it is** | An AI agent that writes, edits, and reasons about code | A background kernel that senses your machine and learns your behaviour |
| **Scope** | Focused on a codebase or repo, inside a coding session | System-wide: apps, processes, workspaces, hardware, activity patterns — not just code |
| **Lifespan** | Task- or session-based — starts when you ask, ends when the task is done | Always-on — continuously running, updating, and learning |
| **Where intelligence runs** | Relies on a cloud-hosted LLM to do the reasoning | Local-first by design — sensing, context-building, and behaviour modelling happen entirely on-device |
| **Relationship to AI models** | *Is* the AI agent | Vendor-neutral *infrastructure* meant to feed context to any AI agent |
| **Core question it answers** | "Can you make this code change for me?" | "What is actually happening on this machine, and what does this person actually need?" |
| **Future direction** | Better code generation | On-demand tool generation with correctness verification — AI that anyone can use |

**In short:** Claude Code, Codex, and Copilot agents are excellent at *acting* once they're told what to do. VIRA's job is to make sure any AI — coding-focused or not — actually knows what's going on and who it's working with, before it acts. And eventually, to generate and verify the tools that get the job done — without requiring the person asking to be a developer.

---

## 📄 License

Released under the **MIT License**.

> Permission is hereby granted, free of charge, to any person obtaining a copy of this software and associated documentation files, to deal in the Software without restriction, including the rights to use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies of the Software.

See the [LICENSE](./LICENSE) file for full details.

---

<div align="center">

*Built for a future where AI understands your machine, knows how you work, and builds what you need — verifiably, locally, and for everyone.*

</div>
