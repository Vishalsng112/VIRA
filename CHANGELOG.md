# Changelog

All notable changes to VIRA are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added

- Workspace-centric sandbox model: user-visible project directories under
  `workspace.root`, one shared default workspace per user, multiple agents
  attaching to the same workspace, per-request `workspace` selection injected
  into tool calls, `workspace.allow_user_paths`, and `/api/v1/workspaces` CRUD.
  Adds host execution mode (`execution_mode: host`) so agents use host-installed
  toolchains, plus `sandbox.extra_path` and read-only SDK mounts. Deleting one
  sandbox no longer deletes a shared workspace. See
  `docs/dev/designs/workspaces.md`.
- Reworked agent framework: one canonical `BaseAgent` with typed
  `TaskRequest`/`TaskResult`, lifecycle hooks, per-task identity, tool policy
  and helpers for LLM/tool/memory/knowledge/progress/response, plus a reusable
  `LLMAgent` layer for prompt + multi-step tool loops and delegation.
  `ChatAgent` is now a thin subclass connected to every registered local and MCP
  tool; qualified MCP tools can be called even when not preselected. Read-only
  tools now execute with their declared permission action instead of being
  rejected as `execute`. See `docs/dev/architecture/agent-design.md`.
- Scoped knowledge base for agents: a single `knowledge_items` store with
  `conversation`/`personal`/`agent`/`org`/`global` scopes, append-only revisions,
  deduplication, promotion policy and a `knowledge.*` event trail. Adds
  `knowledge_search`/`knowledge_write` agent tools, a `/api/v1/knowledge` API,
  merged retrieval over knowledge/documents/memories, and a
  `knowledge.consolidate` worker job stub that the future AGI consolidation
  algorithm can replace. See `docs/dev/designs/knowledge-base.md`.
- Pluggable knowledge storage: `KnowledgeStore`/`KnowledgeRepository`/
  `VectorIndex`/`KnowledgeCache` ports, a config-selected factory, an in-memory
  backend, capability flags, a TTL cache with generation-based invalidation and
  a conformance suite that runs the same contract against every backend.
- Mature sandbox execution environments: persistent per-agent/per-user
  workspaces, shell and argv execution, multi-file project creation, background
  jobs with logs/kill, pip/npm dependency installs, archives with safe restore,
  policy updates, usage/quota reporting and disk-backed recovery after restart.
- ChatAgent per-agent tool permissions (`allow`/`deny`/`pinned`) and per-tool
  timeouts; the shipped Chatbot pins the `sandbox` tool for code/build work.
- Plugin examples and MCP server examples with end-to-end tests.
- Contributor guide, decision log, release cadence and issue templates.
- Showcase page for deployment patterns and community demos.

### Removed

- Legacy agent implementations and their examples: `AutonomousAgent`,
  `LoadMonitorAgent`, `SimpleAgent`, the duplicate
  `vira/agent_orchestration/base.py`, the unused `vira/agent/messaging.py`, the
  `think/plan/act/reflect` execution pipeline and their tests. `BaseAgent` now
  requires `execute`; `ChatAgent` is the only shipped agent.

### Changed

- Default local model is now `nemotron-3.5-bolt:e4b`: faster than the previous
  default with better tool-protocol support.
- Documentation navigation now includes the platform matrix, evaluations,
  agent platform, release process and showcase.
- The shipped configuration auto-approves the isolated `sandbox` tool via
  `security.approvals.safe_tools`, so the ChatAgent can write and execute code
  without a per-call approval. Shell and host-filesystem writes remain gated.

## [0.4.0] - 2026-11-21

### Added

- **Phase 1 positioning and proof:** README rewrite, five-minute demo, demo
  recording, security overview and reproducible demo guide.
- **Phase 2 first-run reliability:** `vira doctor`, model tier guidance, a
  tool-use benchmark, chat recovery UI (retry, switch model, trace), Stop/cancel
  support and model discovery/switching APIs.
- **Phase 3 trust evidence:** threat model, approval gates for destructive tools,
  cross-user isolation tests, CI secret/dependency scanning, backup/restore drill
  with RPO/RTO, hardened Compose services, redacted audit export and client
  diagnostics.
- **Phase 4 cross-platform client:** native macOS Apple Silicon target, macOS
  CI artifact, platform capability matrix, release checksums/notes and uninstall
  paths, opt-in diagnostics and first-run permissions UX.
- **Phase 5 agent platform:** deterministic evaluation harness with recorded
  results, approval-gated generated tools/agents, run budgets, run resume,
  redacted run timelines, memory ranking/feedback, agent quotas, new specialist
  templates and dashboard observability.
- **Phase 6 community:** three complete plugin/MCP examples with tests, release
  cadence and changelog, decision log, contributor guide, curated good-first
  issues, issue templates and a showcase page.

### Changed

- Default local model is `nemotron-3.5-bolt:e4b`; model selection is persisted and
  can be changed without restarting.
- Docker images run with all capabilities dropped, a read-only root filesystem,
  `no-new-privileges`, process limits and a small `noexec` `/tmp`.

### Security

- Approval gates for destructive shell, filesystem and sandbox calls.
- Generated artifacts require administrator approval and remain re-checked at
  execution time.
- Redacted audit export and client diagnostic uploads.
- Gitleaks and pip-audit run in CI.

## [0.3.0] and earlier

Earlier history is available in the git log and release tags.
