# Decision log

A lightweight architecture decision record (ADR) log. Each entry records the
context, the decision, alternatives and consequences. Propose a new entry with
the **Decision proposal** issue template.

Status values: **Proposed**, **Accepted**, **Superseded**, **Rejected**.

## 2026-11-21 — One BaseAgent, with an LLMAgent layer

**Status:** Accepted

**Context:** VIRA had two `BaseAgent` implementations and `ChatAgent`
reimplemented tool discovery, permissions, prompting, the tool loop, delegation
and history. Read-only tools were rejected because the executor always checked
the `execute` action, MCP tools were only half-wired, and per-conversation
history lived in a class-level dict shared by every instance.

**Decision:** Make `vira/agent/base.py` the only `BaseAgent` (lifecycle, task
contract, per-task identity, helpers, tool policy) and add
`vira/agent/llm_agent.py` for LLM/tool agents. `ChatAgent` becomes a thin
subclass handling only chat events, history and responses. Tool permission
actions are resolved from each tool's declared permissions. Any permitted tool,
including qualified MCP tools, may be called by name even when it was not in the
prompt's selected subset.

**Consequences:** one lifecycle and one authoring model; new agents are a class
with an `execute` method plus a tool policy. `BaseAgent.initialize` rejects
classes without `execute`. The legacy `think/plan/act/reflect` pipeline and the
example/sensor agents were removed; `ChatAgent` is the only shipped agent.

## 2026-11-21 — One scoped knowledge store, not RAG per agent

**Status:** Accepted

**Context:** Agents need to persist what they learn so it can later feed a single
dynamic AGI knowledge base. Per-user or per-agent vector stores would multiply
indexes, break deduplication and conflict resolution, and tie knowledge to
ephemeral runtime identifiers (`BaseAgent.agent_id` is a random UUID).

**Decision:** Keep one knowledge store keyed by rows tagged with
`scope ∈ {conversation, personal, agent, org, global}` plus `scope_id`.
Retrieval takes the set of scopes a caller may read and merges results with
uploaded documents and episodic memory. Agent scope uses a stable role name, not
the runtime agent id. Corrections append revisions; only the promotion pipeline
creates `global` knowledge.

**Consequences:** shared learning, one embedding pipeline and one place to
enforce isolation. Isolation depends on correct scope filtering, so read paths
must be scope-aware and tested. Physical partitioning by scope remains a later
scale optimisation, not a design primitive.

## 2026-11-21 — SQL as the knowledge record, NoSQL as derived indexes

**Status:** Accepted

**Context:** The knowledge base needs multi-row transactions (dedupe,
supersession, events) and scope/ACL filtering. Retrieval also needs vector,
lexical and possibly graph indexes, which may be better served by NoSQL systems.
Choosing one database for both concerns would limit the framework either way.

**Decision:** Separate the authoritative record from derived stores. Items,
revisions, provenance and scope live behind the `KnowledgeRepository` port
(SQLite now, PostgreSQL at scale). Embeddings live behind `VectorIndex`; caches
behind `KnowledgeCache`. Both are rebuildable and never authoritative. The
factory selects adapters from `config.yaml`, and every adapter must pass the
same conformance suite.

**Consequences:** a future Qdrant, OpenSearch, Redis or graph backend is an
adapter plus a config change, not a rewrite. Writes must keep the record and
derived indexes consistent (outbox or synchronous update). The team must resist
reading derived stores as if they were authoritative, and must keep SQL confined
to adapters.

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
