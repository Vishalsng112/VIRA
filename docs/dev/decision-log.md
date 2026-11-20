# Decision log

A lightweight architecture decision record (ADR) log. Each entry records the
context, the decision, alternatives and consequences. Propose a new entry with
the **Decision proposal** issue template.

Status values: **Proposed**, **Accepted**, **Superseded**, **Rejected**.

## 2026-11-21 — Local-first, single-process by default

**Status:** Accepted

**Context:** VIRA targets a self-hosted machine or NAS. Users want private data
and a short install path, not a hosted service.

**Decision:** SQLite and an in-process event bus are the default. PostgreSQL,
external brokers and a separate worker are optional scale-out paths. The API,
worker, scheduler and dashboard remain deployable on one host.

**Consequences:** simple installs and easy backups; horizontal scale requires
PostgreSQL/Redis and the worker. Hosted SaaS is an explicit non-goal for now.

## 2026-11-21 — Python core, not a Rust rewrite

**Status:** Accepted

**Context:** The roadmap defers a Rust rewrite until profiling proves Python is
the bottleneck and extension APIs are stable.

**Decision:** Keep the Python core. Optimise with bounded work, workers and
durable queues before considering a rewrite.

**Consequences:** faster iteration and a large contributor pool; no low-level
performance win.

## 2026-11-21 — Approval gates for destructive actions

**Status:** Accepted

**Context:** Prompt injection and model mistakes make unrestricted shell,
filesystem and sandbox calls unsafe for a first-run product.

**Decision:** Destructive calls create a single-use, expiring approval request.
Execution requires an explicit user/admin decision. Approval state is re-checked
at execution time.

**Consequences:** safer defaults and an audit trail; some agent flows need a
human step. Approval is not a sandbox or a formal policy engine.

## 2026-11-21 — Generated artifacts are declarative and approval-gated

**Status:** Accepted

**Context:** Generated tools/agents are a Phase 5 research-adjacent capability.
Unreviewed generated code is unacceptable.

**Decision:** Generated tools support one declarative HTTPS GET with a host
allow-list; generated agents use an allow-listed tool set and a step budget.
Artifacts move through draft → approved → enabled, and drafts never execute.

**Consequences:** safer and testable generated capabilities; richer generated
code and formal verification remain future research.

## 2026-11-21 — Native macOS target, web/PWA for Intel

**Status:** Accepted

**Context:** The client matrix lacked macOS while the server already ran there
through Docker.

**Decision:** Add a native Flutter macOS target and publish an unsigned Apple
Silicon artifact. Intel Macs use the documented web/PWA client. Signing and
notarization are owner/deployment work.

**Consequences:** native macOS support for Apple Silicon; Intel support has an
explicit alternative rather than a separate artifact.

## 2026-11-21 — Monthly release cadence with deterministic evaluation

**Status:** Accepted

**Context:** Releases and quality claims need to be predictable and comparable.

**Decision:** Target a monthly release, keep a Keep-a-Changelog file, validate
tags against the changelog, and record deterministic evaluation results with
each release.

**Consequences:** repeatable release notes and measurable regressions; live
model quality still needs the separate benchmark.

## Template

```markdown
## YYYY-MM-DD — Title

**Status:** Proposed | Accepted | Superseded | Rejected

**Context:** ...

**Decision:** ...

**Alternatives:** ...

**Consequences:** ...
```
