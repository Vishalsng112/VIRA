# VIRA Roadmap

Status: active product and engineering roadmap  
Last updated: 2026-11-20  
Owner: maintainers  
Related subsystem roadmaps: [server](docs/dev/roadmap/server.md), [client](docs/dev/roadmap/client.md)

This roadmap is about **maturing the framework into a product people can understand,
install, trust and adopt**. It deliberately separates what exists today from what
is still research, so public claims stay honest.

---

## North star

> **VIRA is a self-hosted, local-first context and tool server for AI agents.**
> It gives agents private access to your devices, memory, data and MCP tools,
> with explicit permissions and an audit trail.

The long-term vision can remain ambitious. The public story should lead with what
works now, not with unbuilt research.

### What VIRA is today

- A self-hosted server with an authenticated dashboard, chat, memory, agents,
  workflows, RAG, MCP tools, users and audit.
- A cross-platform Docker deployment on Linux, macOS and Windows, with a
  Linux/macOS/Windows one-command installer.
- **VIRA Link**, a Flutter device companion shipped for Android, iOS (unsigned
  artifact), web/PWA, Linux, Windows and macOS (unsigned Apple Silicon artifact).
- Consent-gated device signals, encryption at rest, permissions, an audit log,
  a Bubblewrap sandbox and a non-root, non-privileged container.
- A Chatbot with tool calling, including read-only database tools with schema
  discovery and administrator-only custom SQL.
- Published releases with Android, iOS, web, Linux AppImage and Windows assets.

### What VIRA is not yet

These are **not** current product claims. They belong to later phases or stay
deferred.

- Verified AI-generated tools or agents.
- Signed/notarized Apple store builds (artifacts exist; signing is owner work).
- A Rust rewrite of the core.
- A plugin ecosystem with broad third-party adoption.
- Always-on sensing by default.
- A hosted SaaS product.

---

## How to use this roadmap

- **Phases are ordered by adoption impact, not by how interesting the work is.**
- A phase is complete only when its **exit criteria** are met, not when code merges.
- Each task should produce a user-visible artifact: docs, demo, release, test,
  benchmark or hardened behaviour.
- Research work is explicitly deferred until the product has a stable core and a
  measurable user base.
- Keep the subsystem roadmaps for implementation detail; this file owns product
  priorities, acceptance criteria and public positioning.

---

## Phase 1 — Positioning and proof

**Status: repository work complete.** External validation (five testers and the
GitHub metadata change) remains an owner action.

**Why first:** the largest current risk is not missing features. It is that a new
visitor cannot quickly understand what VIRA is, why it is different, or what to do
first. This phase fixes the story and proves it with a reproducible demo.

**Target window:** 1–2 weeks.

### Workstream 1.1 — Public positioning

- [x] Rewrite the README above the fold:
  - one-sentence positioning;
  - who it is for;
  - what works today;
  - what is not built yet;
  - a 5-minute demo link;
  - security and privacy evidence.
- [ ] Update the GitHub repository description to match the README. **Owner action;
  GitHub CLI/authentication is not available in this environment.** Suggested copy:
  > Self-hosted, local-first context and tool server for AI agents: private device
  > signals, memory, MCP tools and a control center.
- [ ] Add focused repository topics: `local-first`, `ai-agents`, `mcp`, `self-hosted`,
  `privacy`, `ollama`, `agent-platform`. **Owner action.**
- [x] Remove or clearly mark as roadmap: “AI-OS”, “verifiable AI-generated tools”,
  and any claim that is not backed by code or tests. The README now separates
  “works today” from “not built yet”.
- [x] Add a “What works today / What is not built yet” table to the README.
- [x] Document the macOS client gap and the web/PWA workaround.

### Workstream 1.2 — A reproducible killer demo

- [x] Add `scripts/demo.py`: a dependency-free end-to-end demo that signs in,
  creates a conversation, asks the Chatbot for real device information, shows
  live tool activity, and prints the final answer.
- [x] Add `docs/user/demo.md` with prerequisites, commands, expected output and a
  short explanation of what each step proves.
- [x] Make the demo cover:
  - device counts for the signed-in account;
  - device counts for the server;
  - a live MCP/database tool call;
  - the read-only database safety boundary.
- [x] Add a real demo recording (`docs/assets/demo.mp4`) and an animated GIF
  (`docs/assets/demo.gif`) at the top of the README and the demo guide.
- [x] Add a “demo failed?” troubleshooting section.

### Workstream 1.3 — Trust evidence

- [x] Add a concise security overview page covering:
  - authentication and sessions;
  - user/device roles and grants;
  - consent-gated collectors;
  - encryption at rest and the master-key backup requirement;
  - non-root container and `no-new-privileges`;
  - Bubblewrap sandbox and its limits;
  - audit log and tool-call records;
  - read-only database tool restrictions.
- [x] State limitations clearly instead of implying complete isolation.
- [x] Link the overview from the README and docs navigation.
- [x] Add `SECURITY.md` with a private vulnerability-reporting process.

### Workstream 1.4 — Roadmap hygiene

- [x] Add this roadmap to the README and documentation navigation.
- [x] Mark outdated public criticism as resolved where evidence exists:
  - releases exist;
  - one-command installs exist;
  - the server is cross-platform through Docker;
  - the sandbox exists.
- [x] Add a short “How to give feedback” section so feedback uses the current
  build and links evidence.
- [x] Add the baseline-facts appendix below so future feedback can be checked
  against the current tree.

### Phase 1 exit criteria

- [x] A new visitor can answer “what is VIRA, who is it for, why is it different?”
  from the first screen of the README.
- [x] A new user can install and run the demo in under 10 minutes.
- [x] The demo visibly shows a real tool call and a real answer, with no hand-written
  SQL required.
- [x] The README and roadmap tell the same story. The GitHub description still needs
  the owner edit above.
- [x] No public page in the repository headlines unbuilt verification, an AI-OS, or
  a Rust rewrite.
- [ ] At least 5 external testers complete the demo; at least 4 can repeat the
  positioning in one sentence. **External validation pending.**

---

## Phase 2 — First-run reliability and local-model quality

**Status: work complete.** The Chatbot output-hygiene task was explicitly
deferred by the owner. Live 10-run validation on the recommended local model
passed: device 10/10, database 10/10, RAG 9/10, web 10/10.

**Why:** a 9B local model is the default first impression. When it hesitates,
repeats calls or leaks reasoning markers, users conclude the product is broken.
This phase makes the first 15 minutes reliable.

**Target window:** 2–6 weeks.

### Work

- [x] Add a `vira doctor` command or script that checks:
  - Docker and Compose;
  - Ollama reachability;
  - selected model availability and context size;
  - port conflicts;
  - Chatbot agent enabled;
  - database writability;
  - required master key.
  Implemented as `python -m vira doctor` (`vira/doctor.py`) with a `--json`
  mode and a fix for every warning or failure.
- [x] Add first-run model guidance:
  - recommended local model tiers by RAM/GPU;
  - a cloud-model fallback path;
  - an explicit “tool use may be unreliable below X” warning.
  See [Choose a local model](docs/user/models.md); the same guidance is exposed
  by `/api/v1/models`.
- [ ] Improve Chatbot output hygiene:
  - strip reasoning wrappers (`</think`) from final answers;
  - never display internal tokens in normal chat;
  - keep raw traces available in the activity panel only.
  **Explicitly deferred by the owner; not part of this completion.**
- [x] Add a representative tool-use benchmark:
  - device questions;
  - database questions;
  - RAG questions;
  - web/tool failure recovery;
  - repeated-call and malformed-JSON handling.
  Deterministic scenarios run in CI (`vira/agent/benchmark.py`,
  `vira/tests/test_benchmark.py`); `scripts/benchmark.py` adds live runs against
  a real model.
- [x] Add clear recovery UI when the model fails:
  - retry;
  - switch model;
  - show what failed;
  - preserve the user message.
  Failures now carry run/conversation context and next steps. The chat UI offers
  Retry, model switching (administrator) and the stored run trace. Retrying reuses
  the original message instead of duplicating it.
- [x] Add streaming progress and cancel support if feasible.
  NDJSON progress was already streamed; the composer now has a Stop control that
  aborts the stream while the server safely finishes and saves the run.

### Phase 2 exit criteria

- [x] The Phase 1 demo succeeds in at least 9/10 runs on the recommended local model.
  Live validation against `ornith-1.5:9b`: the demo's device and database
  questions both passed 10/10; RAG passed 9/10 and web passed 10/10. Recorded in
  the [live benchmark](docs/dev/benchmarks/tool-use-live.md).
- [ ] No final answer shows raw `</think` or internal reasoning tokens.
  **Deferred with the output-hygiene task above.**
- [x] A failed first run gives the user an actionable next step, not a dead end.
  The recovery panel shows the failure, doctor guidance, Retry, model switching
  and the stored run trace.
- [x] Benchmark results are recorded in the repo and linked from the README.
  Baseline: [tool-use benchmark](docs/dev/benchmarks/tool-use.md).

---

## Phase 3 — Trust, safety and operational evidence

**Status: repository work complete.** All controls have code, tests and
documented verification commands.

**Why:** privacy and local-first operation are VIRA’s strongest differentiators.
They must be demonstrable, not asserted. This phase turns controls into evidence.

**Target window:** 4–8 weeks, partly parallel with Phase 2.

### Work

- [x] Write a threat model covering:
  - malicious prompts and tool injection;
  - cross-user data access;
  - device credential leakage;
  - plugin and MCP supply chain;
  - destructive tool calls;
  - backup and key loss.
  See the [threat model](docs/dev/security/threat-model.md).
- [x] Add approval gates for destructive tools (shell, filesystem writes, sandbox
  actions).
  `agent_approvals` stores single-use, expiring requests; the tool executor
  returns `APPROVAL_REQUIRED` and the API exposes `/api/v1/approvals` and
  `/api/v1/admin/approvals`.
- [x] Add tests for cross-user isolation across chat, memory, RAG, devices,
  insights, workflows and database tools.
  `vira/tests/test_security_phase3.py` covers every listed surface.
- [x] Add secret scanning and dependency vulnerability checks to CI.
  `.github/workflows/security.yml` runs gitleaks and pip-audit on push, pull
  request and a weekly schedule; `.gitleaks.toml` allowlists intentional
  documentation/test fixtures.
- [x] Add a backup/restore drill script and document RPO/RTO.
  `scripts/backup_drill.py` creates, copies, opens and integrity-checks a backup
  without touching the live database. RPO target is 24 hours (daily worker
  backup); measured RTO is recorded in
  [the drill runbook](docs/dev/runbooks/backup-restore.md).
- [x] Harden the container and document what host sensing is and is not available
  inside Docker.
  Compose now drops all capabilities, uses a read-only root filesystem, a small
  `noexec` `/tmp`, process limits and `no-new-privileges`. The security and
  Docker guides explain the container's sensing limits.
- [x] Publish a security page with controls, limitations and verification commands.
  [Security overview](docs/user/security.md) now links the threat model, drill,
  approvals, CI and exact test commands.
- [x] Add a redacted audit-log export for administrators.
  `/api/v1/admin/audit/export` supports JSON/CSV, audit/tool-call selection,
  time filters, recursive redaction and audits the export itself.

### Phase 3 exit criteria

- [x] Threat model and security page are public and linked from the README.
- [x] CI catches secrets and known vulnerable dependencies.
  gitleaks plus pip-audit in `.github/workflows/security.yml`.
- [x] Cross-user isolation tests pass.
  `python3 -m unittest vira.tests.test_security_phase3 -v`.
- [x] Backup/restore is exercised and documented.
  Drill passed; evidence in
  [backup and restore drill](docs/dev/runbooks/backup-restore.md).
- [x] Destructive tools require explicit approval.
  Covered by `ApprovalTests` in `vira/tests/test_security_phase3.py`.

---

## Phase 4 — Cross-platform client and packaging

**Status: repository work complete.** macOS now has a native Apple Silicon build;
Intel Macs use the documented web/PWA alternative.

**Why:** the server runs everywhere Docker runs, but the native client matrix is
uneven. Windows and Linux clients exist; macOS does not. Packaging and signing
need to be predictable.

**Target window:** 6–12 weeks.

### Work

- [x] Decide the macOS strategy:
  - add a native Flutter macOS target; or
  - officially support the web/PWA client on macOS and document the limits.
  Added a native Flutter macOS target (`client/macos`, Apple Silicon CI build,
  network/keychain entitlements). Intel Macs use the documented web/PWA client.
- [x] Polish Windows and Linux installers:
  - signed artifacts where possible;
  - checksums and release notes;
  - clean uninstall paths.
  Release notes now include signing status, checksum verification and uninstall
  paths per platform. Android uses optional signing secrets; Windows/Linux/macOS
  remain unsigned because no code-signing certificates are in the repository.
- [x] Add a platform capability matrix to the docs.
  See [Platform capability matrix](docs/user/platforms.md).
- [x] Make release automation build every supported client target and attach
  checksums.
  `build-client.yml` builds Android, iOS, web, Linux, Windows and macOS, then
  publishes every artifact with `checksums.txt`.
- [x] Add crash/diagnostic reporting that is opt-in and privacy-preserving.
  Off by default; local-only until the user sends it. Client and server redact
  credentials, URLs, identifiers and token-shaped text. Reports land in the
  administrator diagnostics/audit view.
- [x] Improve first-run permissions UX for sensors and notifications.
  Added a first-run permissions banner and permission sheet, per-signal Allow
  actions, a Settings permissions summary and an honest OS-notification state
  (in-app reminders now; notification permission only when scheduled
  notifications ship).

### Phase 4 exit criteria

- [x] Every advertised platform has a tested build artifact or an explicit supported
  alternative.
  Android, iOS (unsigned), web/PWA, Linux x86_64, Windows x64 and macOS arm64 have
  CI artifacts; Intel Macs have the documented web/PWA alternative.
- [x] Release assets and checksums are produced automatically.
- [x] The capability matrix is accurate and linked from the README.

---

## Phase 5 — Agent and tool platform maturity

**Status: repository work complete.** The platform is measurable, generated
artifacts are approval-gated, and runs are recoverable and observable.

**Why:** the long-term differentiator is a trustworthy agent platform. This phase
earns the right to talk about generated tools and deeper autonomy.

**Target window:** 8–16 weeks.

### Work

- [x] Add an evaluation harness for tool selection, task completion, memory
  retrieval and failure recovery.
  `vira/evaluation` + `scripts/evaluate.py`; results in
  [agent platform evaluation](docs/dev/evaluations/agent-platform.md) with the
  [research basis](docs/dev/evaluations/research-basis.md).
- [x] Add approval-gated generated tools and agents (draft → review → enable).
  `generated_artifacts`, `/api/v1/generated`, checksummed specs, admin approval,
  execution-time status checks, safe HTTPS GET tools and bounded generated agents.
- [x] Add tool budgets, timeouts, destructive-action guards and output validation.
  Step, observation and wall-clock budgets; per-tool timeout; repeat guard;
  destructive approvals; generated JSON validation and bounded output.
- [x] Improve run recovery and resumability for interrupted workflows.
  `POST /api/v1/runs/{id}/resume` reuses the original message; startup marks
  queued/running runs failed and visible.
- [x] Add agent templates and examples that solve concrete tasks.
  `incident_triage`, `research_brief` and `data_steward` definitions.
- [x] Improve memory ranking, recency and user controls.
  Recency/importance/feedback ranking, 30-day half-life, abstention, mute and
  useful/not-useful feedback API.
- [x] Add cost/token budgets per user/agent and surface them in the dashboard.
  Agent quota scope, enforcement in the LLM manager, per-agent usage breakdown and
  quota form.
- [x] Add observability for agent runs: timeline, tool inputs/results, failure
  reasons and redaction.
  `/api/v1/runs`, `/runs/{id}/timeline` with redaction, and the dashboard run list
  with trace and Resume actions.

### Phase 5 exit criteria

- [x] A generated tool or agent cannot execute without explicit approval.
  Drafts are never registered; enabled tools/agents re-check status on invocation.
  Covered by `vira/tests/test_phase5.py`.
- [x] Evaluation results are recorded and comparable across releases.
  `docs/dev/evaluations/agent-platform.md` and `.json` include revision, version,
  per-case results and repeat stability.
- [x] Destructive actions are blocked or require approval.
  Approval gates from Phase 3 are exercised by the evaluation suite.
- [x] Interrupted runs are recoverable and visible.
  Startup recovery, `GET /api/v1/runs`, `POST /runs/{id}/resume`, dashboard run
  list and redacted timeline.

---

## Phase 6 — Community and ecosystem

**Status: repository work complete.** External contributor recruitment is an
owner action that cannot be completed inside the repository.

**Why:** a platform eventually needs contributors and third-party extensions, but
this only works after the core story and first-run experience are solid.

**Target window:** ongoing after Phase 3.

### Work

- [x] Establish a predictable release cadence and changelog.
  `CHANGELOG.md`, [release process](docs/dev/releases.md), a tag-driven Release
  workflow and a monthly release checklist issue template.
- [x] Label and curate `good first issue` work.
  `.github/good-first-issues.json`, generated
  [good first issues](docs/dev/good-first-issues.md), `scripts/good_first_issues.py`
  and a dedicated issue template.
- [x] Add three complete plugin/MCP examples with tests.
  `hello_world`, `reading_list`, `focus_budget` and an MCP `notes_server`, all
  exercised by `vira/tests/test_examples.py`.
- [x] Publish a contributor guide that explains the architecture in plain language.
  `CONTRIBUTING.md` now includes a plain-language architecture model, repository
  map, 15-minute first change, testing commands and extension examples.
- [x] Add a public roadmap review cadence and decision log.
  The roadmap review cadence is weekly/monthly/per release; architecture and
  product decisions are recorded in [the decision log](docs/dev/decision-log.md).
- [ ] Recruit at least one regular contributor outside the maintainer.
  **Owner action:** requires outreach and people, not repository work.
- [x] Add a showcase page for real deployments and demos.
  [Showcase](docs/user/showcase.md) includes the reproducible demo, deployable
  patterns and a permission-safe submission template; community entries are added
  as they are approved.

### Phase 6 exit criteria

- [x] Releases happen on a predictable cadence.
  Monthly target, changelog, release checklist and automated tag validation.
- [ ] At least 3 external contributors have merged changes.
  **Owner action pending.** No external contributors can be recruited from inside
  the repository.
- [x] At least 3 plugin/MCP examples are maintained and tested.
  Three plugins + one MCP server example, all covered by tests.
- [x] Issues receive an initial response within a documented target.
  Documented in [release process](docs/dev/releases.md#response-targets) and
  `CONTRIBUTING.md`; adherence is an owner/community operational metric.

---

## Deferred research and explicit non-goals

These are intentionally **not** near-term priorities. They can be revisited when
the prerequisites are met.

- **Verified AI-generated tools/agents.** Hard research problem. Approval gates,
  evaluation and sandboxing now exist (Phase 5); formal verification of generated
  behaviour remains research, so do not headline “verified” yet.
- **Python-to-Rust rewrite.** No current plan. Revisit only if profiling shows
  Python is the bottleneck and the plugin/sensor APIs are stable.
- **Always-on sensing by default.** Keep sensing explicit, consent-gated and
  per-collector.
- **Hosted SaaS / multi-tenant cloud.** VIRA is local-first; hosted operation is
  a separate product decision.
- **Full mobile feature parity with the server dashboard.** Focus on the device
  companion use case.
- **Compliance certifications.** Defer until there are real enterprise users.

---

## Success metrics

| Area | Metric | Target |
|---|---|---|
| Positioning | Visitors can explain VIRA in one sentence | 4/5 testers |
| Onboarding | Install + demo completion | < 10 minutes |
| Reliability | Demo success on recommended local model | ≥ 90% |
| Reliability | Final answers free of raw reasoning tokens | 100% |
| Trust | Cross-user isolation tests | 100% pass |
| Trust | Destructive tools requiring approval | 100% |
| Platform | Advertised targets with tested artifacts | 100% |
| Community | External contributors with merged work | ≥ 3 |
| Community | Release cadence | Monthly or documented |

---

## Decision gates

1. **Do not broaden the public claim until Phase 1 exit criteria are met.**
2. **Do not start Phase 5 research work until Phase 2 and Phase 3 are stable.**
3. **Do not plan a rewrite until the current APIs are versioned and profiling
   proves a need.**
4. **Do not add a new platform target without a tested artifact and a support
   story.**
5. **Do not call a feature “verified” until there is an evaluation and approval
   path a user can inspect.**

---

## Review cadence

- Weekly: current-phase blockers, good-first issues and open security reports.
- Monthly: metrics, changelog, release notes, roadmap reprioritisation and
  community health (see [release process](docs/dev/releases.md)).
- Per release: update the “what works today” table, evaluation results and remove
  stale claims.
- Per decision: record architecture/product choices in the
  [decision log](docs/dev/decision-log.md).

---

## Baseline facts (2026-11-20)

Use these when evaluating feedback. They are deliberately factual and should be
updated when the repository changes.

- The server runs through Docker on Linux, macOS and Windows.
- One-command installers exist: `scripts/install.sh` and `scripts/install.ps1`.
- Releases exist with Android APK, unsigned iOS, web, Linux AppImage and Windows
  assets, plus checksums.
- The default Compose deployment runs as non-root with `no-new-privileges`; it does
  not use `privileged` and does not mount the Docker socket.
- A Bubblewrap sandbox exists (`vira/sandbox`) with CPU, memory, process and
  timeout limits. It is not a VM boundary.
- VIRA Link ships for Android, iOS (unsigned), web/PWA, Linux, Windows and macOS
  (unsigned Apple Silicon). Intel Macs use the web/PWA client.
- Device collectors are opt-in and consent is enforced at ingestion.
- Sensitive config values and device event payloads are encrypted with a master
  key; the whole SQLite file is not application-encrypted.
- The read-only database MCP tools exist and reject writes, secret columns and
  multiple statements.
- There is no Rust rewrite plan in the current repository.
- Verified AI-generated tools/agents are not implemented.

---

## Repository metadata copy

Use this when updating the GitHub description and pinned repository details:

**Description**

> Self-hosted, local-first context and tool server for AI agents: private device
> signals, memory, MCP tools and a control center.

**Topics**

`local-first`, `ai-agents`, `mcp`, `self-hosted`, `privacy`, `ollama`,
`agent-platform`, `device-telemetry`, `rag`, `workflows`

**Pinned demo title**

> Ask your local AI about your own devices — private, self-hosted, tool-driven.
