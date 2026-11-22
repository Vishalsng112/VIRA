# Knowledge base and dynamic AGI memory

VIRA keeps everything an agent learns in **one scoped knowledge store**. There is
no RAG instance per user or per agent. The end goal is a single knowledge base
that the future AGI consolidation algorithm can update dynamically; this layer
provides the interfaces and connections it will use.

## Why not one store per user or agent

* Runtime agent ids are random UUIDs (`BaseAgent.agent_id`), so per-agent stores
  would lose knowledge on restart.
* Cross-agent learning, deduplication and contradiction detection become N-way
  merges instead of status transitions.
* Embedding models and dimensions must stay consistent; N stores mean N
  re-embedding migrations.
* VIRA already scopes rows (`rag_documents.organization_id`, `memories.agent_id`,
  `memories.conversation_id`). Scoping rows is the established pattern.

A per-scope physical index (Postgres partition, materialized view) is a later
scale optimisation behind the same interface.

## Scopes

| Scope | `scope_id` | Written by | Read by |
|---|---|---|---|
| `conversation` | conversation id | any agent in the run | same conversation (TTL, default 7 days) |
| `personal` | user id | agent on behalf of a user | the same user, all their agents |
| `agent` | stable role name (`researcher`, `critic`, …) | that role | same role and user |
| `org` | organization id | organization members | organization members |
| `global` | — | promotion pipeline only | everyone |

Rules live in `vira/knowledge/policy.py`:

* `default_read_scopes()` returns the `(scope, scope_id)` pairs a caller may
  read. `global` is always included.
* `resolve_write_scope()` chooses `personal` when the user asked the agent to
  remember something, `agent` for autonomous learnings, and `conversation` when
  no stable role exists.
* Permission strings follow `knowledge.read.{scope}`,
  `knowledge.write.{scope}`, `knowledge.promote.{scope}`.

## Lifecycle

```
agent write ──► draft / verified ──► candidate ──► promoted (global)
                                   │
                          supersede / deprecate
```

* Writes are append-only. A correction creates a new item with
  `supersedes = previous_id`; the old row is marked `deprecated` and keeps a
  `superseded_by` back-reference.
* Duplicate content in the same scope merges: confidence/importance take the
  maximum and the revision increments.
* `global` cannot be written directly. `service.promote()` applies
  `consolidation.default_promotion_policy` (confidence ≥ 0.7 and at least two
  confirmations by default).

## Components

| Module | Responsibility |
|---|---|
| `vira/knowledge/models.py` | `KnowledgeItem`, `Scope`, `KnowledgeStatus`, hashing |
| `vira/knowledge/policy.py` | scope resolution, precedence, permission strings |
| `vira/knowledge/ports.py` | `KnowledgeStore`, `KnowledgeRepository`, `VectorIndex`, `KnowledgeCache`, `KnowledgeQuery`, `Capabilities` |
| `vira/knowledge/store.py` | SQL adapters + shared lifecycle base |
| `vira/knowledge/backends/memory.py` | ephemeral in-memory adapter used by conformance tests |
| `vira/knowledge/factory.py` | config-driven backend/cache selection |
| `vira/knowledge/cache.py` | `NullCache`, `InProcessTtlCache` |
| `vira/knowledge/ranking.py` | backend-neutral score blending |
| `vira/knowledge/service.py` | merged retrieval over knowledge + documents + memories |
| `vira/knowledge/events.py` | durable `knowledge.*` event trail (event-bus bridge) |
| `vira/knowledge/consolidation.py` | `PromotionPolicy` and the worker job stub |
| `vira/tooling/servers/vira_core/tools.py` | `vira.knowledge_search`, `vira.knowledge_write` agent tools |
| `vira/api/routes_knowledge.py` | `/api/v1/knowledge` REST surface |

Storage tables: `knowledge_items`, `knowledge_chunks`, `knowledge_events`
(migration 15, mirrored in `vira/db/postgres_schema.sql`). Chunks reuse
`rag.service.chunk_text` and the existing embedding provider
(`vira/memory/embeddings.py`).

## Storage adapters

Only `store.py` contains knowledge SQL. `service.py`, tools and the API use
`KnowledgeQuery` and plain item dicts. The factory selects the backend from
`config.yaml`:

```yaml
knowledge:
  backend: sql        # sql | memory
  cache: memory       # memory | none
  cache_ttl_seconds: 30
```

* `sql` runs on SQLite or PostgreSQL depending on `VIRA_DATABASE_URL`; the
  connection layer already routes both.
* `memory` is ephemeral, non-transactional and exists to prove the contract and
  to serve evaluations.
* `cache: memory` is a per-process TTL cache; every write bumps a generation, so
  invalidation is race-free. Cache entries are never authoritative.
* `Capabilities` (`durable`, `transactions`, `ann`, `fulltext`, `graph`,
  `read_your_writes`) let callers degrade instead of guessing.

Adding a NoSQL or vector-native backend means implementing the ports in
`ports.py` and registering it in `factory.py`. No caller changes. A future
Postgres/pgvector, Qdrant or Mongo adapter must pass
`vira/tests/test_knowledge_backends.py`, which runs the same contract against
every backend.

## Retrieval

`service.search()` merges three independently owned sources and annotates every
hit with `_origin` (`knowledge`, `document`, `memory`), `scope`, `status`,
`confidence` and `source`:

1. **knowledge** — scored by `0.7 * cosine + 0.3 * lexical`, multiplied by a
   confidence trust factor and a scope weight.
2. **documents** — `rag.service.search`, scoped to the user or organization.
3. **memories** — `database.search_memories`, ranked with
   `memory.embeddings.hybrid_score`.

Agents call this through the `knowledge_search` tool. The older `rag_search` tool
remains for uploaded documents and is unchanged.

## Hooks for the future AGI algorithm

Do not implement the consolidation algorithm yet. Build against these seams:

* Subscribe to `knowledge.written`, `knowledge.superseded`,
  `knowledge.deprecated`, `knowledge.promoted` via
  `events.set_event_bus()`.
* Replace `default_promotion_policy` with a `PromotionPolicy` implementation.
* Replace `consolidation.run_consolidation` (worker kind
  `knowledge.consolidate`) with the real pipeline.
* Swap `store.set_store()` / `factory.create_store()` for a Postgres, pgvector,
  Mongo or Qdrant adapter when scale requires it. Nothing above the ports
  changes.

## Testing

* `vira/tests/test_knowledge.py` covers service behaviour: migration, scope
  isolation, agent-role gating, deduplication, promotion policy, revision
  chains, organization scope, tools and account export/deletion.
* `vira/tests/test_knowledge_backends.py` is the conformance suite. It runs the
  same contract against the SQL and in-memory adapters and checks the factory,
  capability flags and cache invalidation.
