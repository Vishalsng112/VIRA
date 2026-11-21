-- PostgreSQL schema for VIRA (SQLite remains the default local backend).
CREATE TABLE IF NOT EXISTS users (
    id SERIAL PRIMARY KEY,
    username TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    recovery_code_hash TEXT NOT NULL,
    role TEXT NOT NULL DEFAULT 'admin',
    created_at TEXT DEFAULT (CURRENT_TIMESTAMP::text),
    public_id TEXT UNIQUE,
    status TEXT NOT NULL DEFAULT 'active',
    deleted_at TEXT,
    updated_at TEXT
);
CREATE TABLE IF NOT EXISTS sessions (
    id SERIAL PRIMARY KEY,
    session_id_hash TEXT UNIQUE NOT NULL,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    revoked_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id);
CREATE TABLE IF NOT EXISTS auth_audit (
    id SERIAL PRIMARY KEY,
    event_type TEXT NOT NULL,
    user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
    session_id_hash TEXT,
    action TEXT NOT NULL,
    resource TEXT,
    allowed INTEGER NOT NULL,
    correlation_id TEXT,
    details TEXT,
    created_at TEXT NOT NULL,
    actor_type TEXT NOT NULL DEFAULT 'user',
    target TEXT,
    device_id TEXT
);
CREATE TABLE IF NOT EXISTS outbox_events (
    id TEXT PRIMARY KEY,
    event_type TEXT NOT NULL,
    event_kind TEXT NOT NULL,
    payload TEXT NOT NULL,
    source TEXT NOT NULL,
    correlation_id TEXT NOT NULL,
    causation_id TEXT,
    status TEXT NOT NULL DEFAULT 'pending',
    attempts INTEGER NOT NULL DEFAULT 0,
    available_at TEXT NOT NULL,
    locked_at TEXT,
    published_at TEXT,
    last_error TEXT,
    created_at TEXT NOT NULL,
    device_id TEXT
);
CREATE INDEX IF NOT EXISTS idx_outbox_pending ON outbox_events(status, available_at);
CREATE TABLE IF NOT EXISTS event_consumptions (
    consumer_name TEXT NOT NULL,
    event_id TEXT NOT NULL,
    processed_at TEXT NOT NULL,
    PRIMARY KEY (consumer_name, event_id)
);
CREATE TABLE IF NOT EXISTS agent_definitions (
    agent_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    version TEXT NOT NULL,
    module TEXT NOT NULL,
    class_name TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    capabilities TEXT NOT NULL,
    subscribed_events TEXT NOT NULL,
    config TEXT NOT NULL,
    enabled INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS tool_calls (
    id TEXT PRIMARY KEY,
    tool_name TEXT NOT NULL,
    request TEXT NOT NULL,
    result TEXT,
    status TEXT NOT NULL,
    permission_allowed INTEGER NOT NULL,
    permission_action TEXT NOT NULL,
    error TEXT,
    duration_seconds DOUBLE PRECISION NOT NULL,
    correlation_id TEXT,
    agent_id TEXT,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS conversations (
    id TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    title TEXT NOT NULL DEFAULT 'New conversation',
    archived INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS incognito_conversations (
    id TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    title TEXT NOT NULL DEFAULT 'New conversation',
    archived INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS incognito_messages (
    id TEXT PRIMARY KEY,
    conversation_id TEXT NOT NULL REFERENCES incognito_conversations(id) ON DELETE CASCADE,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    sequence_no INTEGER NOT NULL,
    correlation_id TEXT,
    run_id TEXT,
    idempotency_key TEXT,
    metadata TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    created_by_device_id TEXT,
    UNIQUE(user_id, idempotency_key)
);
CREATE TABLE IF NOT EXISTS incognito_runs (
    id TEXT PRIMARY KEY,
    conversation_id TEXT NOT NULL REFERENCES incognito_conversations(id) ON DELETE CASCADE,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    agent_id TEXT,
    status TEXT NOT NULL,
    input_message_id TEXT,
    result_message_id TEXT,
    error TEXT,
    correlation_id TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS messages (
    id TEXT PRIMARY KEY,
    conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    sequence_no INTEGER NOT NULL,
    correlation_id TEXT,
    run_id TEXT,
    idempotency_key TEXT,
    metadata TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    created_by_device_id TEXT,
    UNIQUE(user_id, idempotency_key)
);
CREATE INDEX IF NOT EXISTS idx_messages_conversation ON messages(conversation_id, sequence_no);
CREATE TABLE IF NOT EXISTS agent_runs (
    id TEXT PRIMARY KEY,
    conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    agent_id TEXT,
    status TEXT NOT NULL,
    input_message_id TEXT,
    result_message_id TEXT,
    error TEXT,
    correlation_id TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS memories (
    id TEXT PRIMARY KEY,
    user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
    agent_id TEXT,
    conversation_id TEXT,
    memory_type TEXT NOT NULL,
    content TEXT NOT NULL,
    metadata TEXT NOT NULL DEFAULT '{}',
    importance DOUBLE PRECISION NOT NULL DEFAULT 0,
    expires_at TEXT,
    created_at TEXT NOT NULL,
    device_id TEXT,
    last_used_at TEXT,
    use_count INTEGER NOT NULL DEFAULT 0,
    feedback TEXT,
    feedback_note TEXT
);
CREATE INDEX IF NOT EXISTS idx_memories_scope ON memories(user_id, agent_id, conversation_id, created_at);
CREATE INDEX IF NOT EXISTS idx_memories_feedback ON memories(user_id, feedback, created_at);
CREATE TABLE IF NOT EXISTS schema_migrations (
    version INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    applied_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS devices (
    id TEXT PRIMARY KEY,
    display_name TEXT NOT NULL,
    platform TEXT NOT NULL,
    device_type TEXT NOT NULL,
    os_version TEXT,
    client_version TEXT,
    capabilities TEXT NOT NULL DEFAULT '[]',
    capability_status TEXT NOT NULL DEFAULT '{}',
    status TEXT NOT NULL DEFAULT 'pending',
    is_server_local INTEGER NOT NULL DEFAULT 0,
    created_by_user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    last_seen_at TEXT,
    last_event_at TEXT,
    revoked_at TEXT,
    ingest_error_count INTEGER NOT NULL DEFAULT 0,
    last_accepted_sequence INTEGER,
    queue_backlog INTEGER,
    rowid BIGSERIAL
);
CREATE UNIQUE INDEX IF NOT EXISTS devices_server_local_uq ON devices(is_server_local) WHERE is_server_local = 1;
CREATE INDEX IF NOT EXISTS devices_by_status ON devices(status, created_at);
CREATE TABLE IF NOT EXISTS device_credentials (
    id TEXT PRIMARY KEY,
    device_id TEXT NOT NULL REFERENCES devices(id) ON DELETE CASCADE,
    credential_hash TEXT NOT NULL,
    scopes TEXT NOT NULL,
    created_at TEXT NOT NULL,
    expires_at TEXT,
    revoked_at TEXT,
    last_used_at TEXT,
    rotated_from TEXT
);
CREATE UNIQUE INDEX IF NOT EXISTS devices_credentials_hash_uq ON device_credentials(credential_hash);
CREATE INDEX IF NOT EXISTS device_credentials_by_device ON device_credentials(device_id, revoked_at);
CREATE TABLE IF NOT EXISTS user_device_access (
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    device_id TEXT NOT NULL REFERENCES devices(id) ON DELETE CASCADE,
    access_role TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active',
    granted_at TEXT NOT NULL,
    granted_by_user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
    revoked_at TEXT,
    PRIMARY KEY (user_id, device_id)
);
CREATE INDEX IF NOT EXISTS user_device_access_by_user ON user_device_access(user_id, status, device_id);
CREATE INDEX IF NOT EXISTS user_device_access_by_device ON user_device_access(device_id, status, user_id);
CREATE TABLE IF NOT EXISTS device_events (
    event_id TEXT PRIMARY KEY,
    device_id TEXT NOT NULL REFERENCES devices(id) ON DELETE CASCADE,
    actor_user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
    source_component TEXT NOT NULL,
    source_instance_id TEXT,
    event_type TEXT NOT NULL,
    event_class TEXT NOT NULL,
    schema_version INTEGER NOT NULL,
    device_sequence INTEGER,
    occurred_at TEXT NOT NULL,
    received_at TEXT NOT NULL,
    correlation_id TEXT NOT NULL,
    causation_id TEXT,
    payload TEXT,
    payload_hash TEXT NOT NULL,
    expires_at TEXT,
    rowid BIGSERIAL
);
CREATE INDEX IF NOT EXISTS device_events_by_device_time ON device_events(device_id, occurred_at DESC);
CREATE INDEX IF NOT EXISTS device_events_by_actor_time ON device_events(actor_user_id, occurred_at DESC);
CREATE INDEX IF NOT EXISTS device_events_by_type_time ON device_events(event_type, received_at DESC);
CREATE INDEX IF NOT EXISTS device_events_by_expiry ON device_events(expires_at);
CREATE TABLE IF NOT EXISTS device_latest_state (
    device_id TEXT NOT NULL REFERENCES devices(id) ON DELETE CASCADE,
    event_type TEXT NOT NULL,
    event_id TEXT NOT NULL,
    occurred_at TEXT NOT NULL,
    received_at TEXT NOT NULL,
    payload TEXT NOT NULL,
    PRIMARY KEY (device_id, event_type)
);
CREATE TABLE IF NOT EXISTS jobs (
    id TEXT PRIMARY KEY,
    kind TEXT NOT NULL,
    payload TEXT NOT NULL DEFAULT '{}',
    status TEXT NOT NULL DEFAULT 'pending',
    priority INTEGER NOT NULL DEFAULT 0,
    attempts INTEGER NOT NULL DEFAULT 0,
    max_attempts INTEGER NOT NULL DEFAULT 5,
    available_at TEXT NOT NULL,
    locked_at TEXT,
    locked_by TEXT,
    last_error TEXT,
    dedupe_key TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    completed_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_jobs_ready ON jobs(status, available_at, priority);
CREATE INDEX IF NOT EXISTS idx_jobs_kind ON jobs(kind, status);
CREATE UNIQUE INDEX IF NOT EXISTS idx_jobs_dedupe_active ON jobs(dedupe_key)
  WHERE dedupe_key IS NOT NULL AND status IN ('pending','running');
CREATE TABLE IF NOT EXISTS insight_daily (
    device_id TEXT NOT NULL REFERENCES devices(id) ON DELETE CASCADE,
    day TEXT NOT NULL,
    app_ms INTEGER NOT NULL DEFAULT 0,
    screen_ms INTEGER NOT NULL DEFAULT 0,
    unlocks INTEGER NOT NULL DEFAULT 0,
    focus_ms INTEGER NOT NULL DEFAULT 0,
    distraction_ms INTEGER NOT NULL DEFAULT 0,
    focus_sessions INTEGER NOT NULL DEFAULT 0,
    focus_score INTEGER NOT NULL DEFAULT 0,
    top_apps TEXT NOT NULL DEFAULT '[]',
    categories TEXT NOT NULL DEFAULT '[]',
    warnings TEXT NOT NULL DEFAULT '[]',
    updated_at TEXT NOT NULL,
    PRIMARY KEY (device_id, day)
);
CREATE INDEX IF NOT EXISTS idx_insight_daily_day ON insight_daily(day);
CREATE TABLE IF NOT EXISTS households (
    id TEXT PRIMARY KEY, name TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS household_members (
    household_id TEXT NOT NULL REFERENCES households(id) ON DELETE CASCADE,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    role TEXT NOT NULL, created_at TEXT NOT NULL, PRIMARY KEY(household_id, user_id)
);
CREATE TABLE IF NOT EXISTS notebooks (
    id TEXT PRIMARY KEY, household_id TEXT NOT NULL REFERENCES households(id),
    owner_user_id INTEGER NOT NULL REFERENCES users(id), title TEXT NOT NULL,
    visibility TEXT NOT NULL DEFAULT 'household', version INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL, updated_at TEXT NOT NULL, deleted_at TEXT
);
CREATE TABLE IF NOT EXISTS family_notes (
    id TEXT PRIMARY KEY, household_id TEXT NOT NULL REFERENCES households(id),
    notebook_id TEXT NOT NULL REFERENCES notebooks(id),
    author_user_id INTEGER NOT NULL REFERENCES users(id),
    kind TEXT NOT NULL DEFAULT 'note', title TEXT NOT NULL, body_md TEXT NOT NULL DEFAULT '',
    pinned INTEGER NOT NULL DEFAULT 0, version INTEGER NOT NULL DEFAULT 1,
    updated_at TEXT NOT NULL, updated_by INTEGER NOT NULL, deleted_at TEXT
);
CREATE TABLE IF NOT EXISTS checklist_items (
    id TEXT PRIMARY KEY, household_id TEXT NOT NULL REFERENCES households(id),
    note_id TEXT NOT NULL REFERENCES family_notes(id), text TEXT NOT NULL,
    done INTEGER NOT NULL DEFAULT 0, position TEXT NOT NULL DEFAULT 'a0',
    assignee_user_id INTEGER, version INTEGER NOT NULL DEFAULT 1,
    updated_at TEXT NOT NULL, updated_by INTEGER NOT NULL, deleted_at TEXT
);
CREATE TABLE IF NOT EXISTS reminders (
    id TEXT PRIMARY KEY, household_id TEXT NOT NULL REFERENCES households(id),
    created_by_user_id INTEGER NOT NULL, assignee_user_id INTEGER,
    title TEXT NOT NULL, body TEXT NOT NULL DEFAULT '', due_at TEXT NOT NULL,
    timezone TEXT NOT NULL DEFAULT 'UTC', rrule TEXT, urgent INTEGER NOT NULL DEFAULT 0,
    note_id TEXT, item_id TEXT, status TEXT NOT NULL DEFAULT 'active',
    version INTEGER NOT NULL DEFAULT 1, updated_at TEXT NOT NULL,
    updated_by INTEGER NOT NULL, deleted_at TEXT
);
CREATE TABLE IF NOT EXISTS sync_op_receipts (
    household_id TEXT NOT NULL, user_id INTEGER NOT NULL, op_id TEXT NOT NULL,
    status TEXT NOT NULL, version INTEGER, result_json TEXT NOT NULL,
    created_at TEXT NOT NULL, PRIMARY KEY (household_id, user_id, op_id)
);
CREATE TABLE IF NOT EXISTS family_changes (
    seq BIGSERIAL PRIMARY KEY, household_id TEXT NOT NULL,
    entity_type TEXT NOT NULL, entity_id TEXT NOT NULL, op TEXT NOT NULL,
    version INTEGER NOT NULL, data TEXT, changed_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS family_changes_household_seq ON family_changes(household_id, seq);
CREATE TABLE IF NOT EXISTS device_consents (
    device_id TEXT NOT NULL REFERENCES devices(id) ON DELETE CASCADE,
    collector TEXT NOT NULL,
    enabled INTEGER NOT NULL DEFAULT 1,
    purpose TEXT NOT NULL DEFAULT 'device_insights',
    retention_hours INTEGER,
    updated_at TEXT NOT NULL,
    updated_by_user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
    revoked_at TEXT,
    PRIMARY KEY (device_id, collector)
);
CREATE INDEX IF NOT EXISTS idx_consents_device ON device_consents(device_id);
CREATE TABLE IF NOT EXISTS event_schemas (
    event_type TEXT NOT NULL,
    version INTEGER NOT NULL,
    schema_json TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    PRIMARY KEY (event_type, version)
);
CREATE TABLE IF NOT EXISTS device_commands (
    id TEXT PRIMARY KEY,
    device_id TEXT NOT NULL REFERENCES devices(id) ON DELETE CASCADE,
    kind TEXT NOT NULL,
    payload TEXT NOT NULL DEFAULT '{}',
    status TEXT NOT NULL DEFAULT 'pending',
    created_by_user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
    created_at TEXT NOT NULL,
    delivered_at TEXT,
    completed_at TEXT,
    expires_at TEXT,
    result TEXT
);
CREATE INDEX IF NOT EXISTS idx_commands_device_status ON device_commands(device_id, status, created_at);
CREATE TABLE IF NOT EXISTS device_pairing_codes (
    code_hash TEXT PRIMARY KEY,
    created_by_user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    used_at TEXT,
    device_id TEXT REFERENCES devices(id) ON DELETE SET NULL
);
CREATE TABLE IF NOT EXISTS user_notifications (
    id TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    device_id TEXT REFERENCES devices(id) ON DELETE SET NULL,
    kind TEXT NOT NULL,
    title TEXT NOT NULL,
    body TEXT NOT NULL DEFAULT '',
    data TEXT NOT NULL DEFAULT '{}',
    status TEXT NOT NULL DEFAULT 'pending',
    created_at TEXT NOT NULL,
    delivered_at TEXT,
    read_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_notifications_user ON user_notifications(user_id, status, created_at);
CREATE TABLE IF NOT EXISTS device_push_tokens (
    device_id TEXT NOT NULL REFERENCES devices(id) ON DELETE CASCADE,
    platform TEXT NOT NULL,
    token TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (device_id, token)
);
CREATE INDEX IF NOT EXISTS idx_push_tokens_device ON device_push_tokens(device_id);
CREATE TABLE IF NOT EXISTS agent_run_events (
    id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    seq INTEGER NOT NULL,
    event_type TEXT NOT NULL,
    data TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    UNIQUE(run_id, seq)
);
CREATE INDEX IF NOT EXISTS idx_run_events_run ON agent_run_events(run_id, seq);
CREATE TABLE IF NOT EXISTS agent_approvals (
    id TEXT PRIMARY KEY,
    run_id TEXT,
    user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
    agent_id TEXT,
    tool_name TEXT NOT NULL,
    action TEXT NOT NULL DEFAULT 'execute',
    fingerprint TEXT NOT NULL,
    arguments TEXT NOT NULL DEFAULT '{}',
    reason TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'approved', 'denied', 'expired')),
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    decided_at TEXT,
    decided_by_user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
    decision_note TEXT,
    consumed_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_approvals_user_status
    ON agent_approvals(user_id, status, created_at);
CREATE INDEX IF NOT EXISTS idx_approvals_match
    ON agent_approvals(user_id, tool_name, fingerprint, status);
CREATE INDEX IF NOT EXISTS idx_approvals_run ON agent_approvals(run_id);
CREATE TABLE IF NOT EXISTS generated_artifacts (
    id TEXT PRIMARY KEY,
    kind TEXT NOT NULL CHECK (kind IN ('tool', 'agent')),
    name TEXT NOT NULL,
    version TEXT NOT NULL DEFAULT '1.0.0',
    description TEXT NOT NULL DEFAULT '',
    spec TEXT NOT NULL DEFAULT '{}',
    status TEXT NOT NULL DEFAULT 'draft'
        CHECK (status IN ('draft', 'approved', 'rejected', 'enabled', 'disabled')),
    checksum TEXT NOT NULL,
    created_by_user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
    approved_by_user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    approved_at TEXT,
    enabled_at TEXT,
    rejection_reason TEXT,
    UNIQUE(kind, name, version)
);
CREATE INDEX IF NOT EXISTS idx_generated_status
    ON generated_artifacts(kind, status, updated_at);
CREATE TABLE IF NOT EXISTS workflows (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    context TEXT NOT NULL DEFAULT '{}',
    created_by_user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
    error TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    completed_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_workflows_user ON workflows(created_by_user_id, created_at);
CREATE TABLE IF NOT EXISTS workflow_steps (
    workflow_id TEXT NOT NULL REFERENCES workflows(id) ON DELETE CASCADE,
    id TEXT NOT NULL,
    seq INTEGER NOT NULL,
    name TEXT NOT NULL,
    agent_id TEXT NOT NULL,
    input TEXT NOT NULL DEFAULT '{}',
    depends_on TEXT NOT NULL DEFAULT '[]',
    retry_policy TEXT,
    compensation TEXT,
    status TEXT NOT NULL DEFAULT 'pending',
    attempts INTEGER NOT NULL DEFAULT 0,
    result TEXT,
    error TEXT,
    started_at TEXT,
    completed_at TEXT,
    PRIMARY KEY (workflow_id, id)
);
CREATE INDEX IF NOT EXISTS idx_workflow_steps_status ON workflow_steps(workflow_id, status);
CREATE TABLE IF NOT EXISTS workflow_events (
    id TEXT PRIMARY KEY,
    workflow_id TEXT NOT NULL REFERENCES workflows(id) ON DELETE CASCADE,
    step_id TEXT,
    event_type TEXT NOT NULL,
    data TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_workflow_events ON workflow_events(workflow_id, created_at);
CREATE TABLE IF NOT EXISTS memory_embeddings (
    memory_id TEXT PRIMARY KEY REFERENCES memories(id) ON DELETE CASCADE,
    user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
    model TEXT NOT NULL,
    dims INTEGER NOT NULL,
    vector TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_memory_embeddings_user ON memory_embeddings(user_id);
CREATE TABLE IF NOT EXISTS rag_documents (
    id TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    title TEXT NOT NULL,
    source TEXT NOT NULL DEFAULT 'manual',
    metadata TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_rag_documents_user ON rag_documents(user_id, created_at);
CREATE TABLE IF NOT EXISTS rag_chunks (
    id TEXT PRIMARY KEY,
    document_id TEXT NOT NULL REFERENCES rag_documents(id) ON DELETE CASCADE,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    chunk_index INTEGER NOT NULL,
    content TEXT NOT NULL,
    metadata TEXT NOT NULL DEFAULT '{}',
    model TEXT NOT NULL,
    dims INTEGER NOT NULL,
    vector TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_rag_chunks_user ON rag_chunks(user_id, document_id);
CREATE TABLE IF NOT EXISTS plugins (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    version TEXT NOT NULL,
    api_version TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    author TEXT NOT NULL DEFAULT '',
    entrypoint TEXT,
    manifest TEXT NOT NULL,
    permissions TEXT NOT NULL DEFAULT '[]',
    status TEXT NOT NULL DEFAULT 'discovered',
    enabled INTEGER NOT NULL DEFAULT 1,
    error TEXT,
    installed_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS plugin_storage (
    plugin_id TEXT NOT NULL,
    key TEXT NOT NULL,
    value TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (plugin_id, key)
);
CREATE TABLE IF NOT EXISTS mcp_servers (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    description TEXT NOT NULL DEFAULT '',
    transport TEXT NOT NULL DEFAULT 'stdio',
    command TEXT,
    args TEXT NOT NULL DEFAULT '[]',
    url TEXT,
    env TEXT NOT NULL DEFAULT '{}',
    permissions TEXT NOT NULL DEFAULT '["read","execute"]',
    allowed_tools TEXT NOT NULL DEFAULT '[]',
    denied_tools TEXT NOT NULL DEFAULT '[]',
    categories TEXT NOT NULL DEFAULT '[]',
    version TEXT NOT NULL DEFAULT '1.0.0',
    source TEXT NOT NULL DEFAULT 'manual',
    enabled INTEGER NOT NULL DEFAULT 1,
    created_by_user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS mcp_policies (
    id TEXT PRIMARY KEY,
    server_id TEXT NOT NULL REFERENCES mcp_servers(id) ON DELETE CASCADE,
    subject_type TEXT NOT NULL,
    subject_id TEXT NOT NULL,
    allowed INTEGER NOT NULL DEFAULT 1,
    allowed_tools TEXT NOT NULL DEFAULT '[]',
    denied_tools TEXT NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL,
    UNIQUE(server_id, subject_type, subject_id)
);
CREATE INDEX IF NOT EXISTS idx_mcp_policies_subject ON mcp_policies(subject_type, subject_id);
CREATE TABLE IF NOT EXISTS organizations (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    slug TEXT NOT NULL UNIQUE,
    owner_user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS organization_members (
    organization_id TEXT NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    role TEXT NOT NULL DEFAULT 'member',
    created_at TEXT NOT NULL,
    PRIMARY KEY (organization_id, user_id)
);
CREATE INDEX IF NOT EXISTS idx_org_members_user ON organization_members(user_id);
ALTER TABLE workflows ADD COLUMN IF NOT EXISTS organization_id TEXT;
ALTER TABLE rag_documents ADD COLUMN IF NOT EXISTS organization_id TEXT;
CREATE TABLE IF NOT EXISTS objects (
    id TEXT PRIMARY KEY,
    user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
    organization_id TEXT REFERENCES organizations(id) ON DELETE SET NULL,
    object_key TEXT NOT NULL,
    content_type TEXT NOT NULL DEFAULT 'application/octet-stream',
    size_bytes INTEGER NOT NULL,
    sha256 TEXT NOT NULL,
    storage_backend TEXT NOT NULL,
    storage_key TEXT NOT NULL,
    metadata TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_objects_user ON objects(user_id, created_at);
CREATE INDEX IF NOT EXISTS idx_objects_org ON objects(organization_id, created_at);
CREATE TABLE IF NOT EXISTS llm_usage (
    id TEXT PRIMARY KEY,
    user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
    organization_id TEXT,
    agent_id TEXT,
    provider TEXT NOT NULL DEFAULT 'unknown',
    model TEXT NOT NULL DEFAULT 'unknown',
    prompt_tokens INTEGER NOT NULL DEFAULT 0,
    completion_tokens INTEGER NOT NULL DEFAULT 0,
    total_tokens INTEGER NOT NULL DEFAULT 0,
    cost_usd REAL NOT NULL DEFAULT 0,
    latency_ms REAL NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_llm_usage_user ON llm_usage(user_id, created_at);
CREATE INDEX IF NOT EXISTS idx_llm_usage_org ON llm_usage(organization_id, created_at);
CREATE TABLE IF NOT EXISTS llm_quotas (
    id TEXT PRIMARY KEY,
    scope TEXT NOT NULL,
    subject_id TEXT NOT NULL,
    period TEXT NOT NULL DEFAULT 'month',
    token_limit INTEGER,
    cost_limit_usd REAL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(scope, subject_id, period)
);
CREATE TABLE IF NOT EXISTS update_releases (
    id TEXT PRIMARY KEY,
    product TEXT NOT NULL,
    channel TEXT NOT NULL DEFAULT 'stable',
    version TEXT NOT NULL,
    min_version TEXT,
    notes TEXT NOT NULL DEFAULT '',
    url TEXT NOT NULL DEFAULT '',
    checksum TEXT,
    published_at TEXT NOT NULL,
    created_by_user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
    UNIQUE(product, channel, version)
);
CREATE INDEX IF NOT EXISTS idx_updates_lookup ON update_releases(product, channel, published_at);
CREATE TABLE IF NOT EXISTS knowledge_items (
    id TEXT PRIMARY KEY,
    user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
    organization_id TEXT,
    scope TEXT NOT NULL CHECK (scope IN ('conversation', 'personal', 'agent', 'org', 'global')),
    scope_id TEXT,
    agent_role TEXT,
    kind TEXT NOT NULL DEFAULT 'fact',
    content TEXT NOT NULL,
    summary TEXT,
    metadata TEXT NOT NULL DEFAULT '{}',
    source TEXT NOT NULL DEFAULT '{}',
    tags TEXT NOT NULL DEFAULT '[]',
    confidence REAL NOT NULL DEFAULT 0.5,
    importance REAL NOT NULL DEFAULT 0.0,
    status TEXT NOT NULL DEFAULT 'draft',
    revision INTEGER NOT NULL DEFAULT 1,
    supersedes TEXT,
    superseded_by TEXT,
    valid_from TEXT,
    valid_until TEXT,
    expires_at TEXT,
    content_hash TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_knowledge_scope ON knowledge_items(scope, scope_id, status, created_at);
CREATE INDEX IF NOT EXISTS idx_knowledge_user ON knowledge_items(user_id, updated_at);
CREATE INDEX IF NOT EXISTS idx_knowledge_org ON knowledge_items(organization_id, updated_at);
CREATE INDEX IF NOT EXISTS idx_knowledge_hash ON knowledge_items(content_hash);
CREATE TABLE IF NOT EXISTS knowledge_chunks (
    id TEXT PRIMARY KEY,
    item_id TEXT NOT NULL REFERENCES knowledge_items(id) ON DELETE CASCADE,
    chunk_index INTEGER NOT NULL,
    content TEXT NOT NULL,
    model TEXT NOT NULL,
    dims INTEGER NOT NULL,
    vector TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_knowledge_chunks_item ON knowledge_chunks(item_id, chunk_index);
CREATE TABLE IF NOT EXISTS knowledge_events (
    id TEXT PRIMARY KEY,
    item_id TEXT,
    event TEXT NOT NULL,
    actor TEXT,
    agent_role TEXT,
    data TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_knowledge_events_item ON knowledge_events(item_id, created_at);
CREATE TABLE IF NOT EXISTS workspaces (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    path TEXT NOT NULL,
    owner_user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
    organization_id TEXT,
    execution_mode TEXT NOT NULL DEFAULT 'bubblewrap',
    metadata TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_workspaces_owner ON workspaces(owner_user_id, updated_at);
CREATE INDEX IF NOT EXISTS idx_workspaces_path ON workspaces(path);
CREATE UNIQUE INDEX IF NOT EXISTS idx_workspaces_name ON workspaces(owner_user_id, name);
ALTER TABLE devices ADD COLUMN IF NOT EXISTS installation_id TEXT;
CREATE UNIQUE INDEX IF NOT EXISTS devices_installation_uq
    ON devices(created_by_user_id, installation_id)
    WHERE installation_id IS NOT NULL;

-- Proactive agent schedules and notification delivery (migration 17)
ALTER TABLE user_notifications ADD COLUMN IF NOT EXISTS channel TEXT NOT NULL DEFAULT 'inapp';
ALTER TABLE user_notifications ADD COLUMN IF NOT EXISTS dedupe_key TEXT;
ALTER TABLE user_notifications ADD COLUMN IF NOT EXISTS attempts INTEGER NOT NULL DEFAULT 0;
ALTER TABLE user_notifications ADD COLUMN IF NOT EXISTS last_error TEXT;
CREATE UNIQUE INDEX IF NOT EXISTS user_notifications_dedupe
    ON user_notifications(user_id, dedupe_key) WHERE dedupe_key IS NOT NULL;
CREATE TABLE IF NOT EXISTS agent_schedules (
    id TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    organization_id TEXT,
    agent_id TEXT NOT NULL,
    name TEXT NOT NULL,
    message TEXT NOT NULL,
    schedule_type TEXT NOT NULL
        CHECK (schedule_type IN ('daily', 'weekly', 'interval')),
    time_of_day TEXT,
    weekday INTEGER,
    interval_minutes INTEGER,
    timezone TEXT NOT NULL DEFAULT 'UTC',
    quiet_hours_start TEXT,
    quiet_hours_end TEXT,
    channels TEXT NOT NULL DEFAULT '["inapp"]',
    task_profile TEXT NOT NULL DEFAULT '{}',
    enabled INTEGER NOT NULL DEFAULT 1,
    next_run_at TEXT,
    last_run_at TEXT,
    last_error TEXT,
    locked_until TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_agent_schedules_due
    ON agent_schedules(enabled, next_run_at);
CREATE INDEX IF NOT EXISTS idx_agent_schedules_user
    ON agent_schedules(user_id, enabled, created_at);
CREATE TABLE IF NOT EXISTS agent_schedule_runs (
    id TEXT PRIMARY KEY,
    schedule_id TEXT NOT NULL REFERENCES agent_schedules(id) ON DELETE CASCADE,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    agent_id TEXT,
    run_id TEXT,
    scheduled_for TEXT,
    status TEXT NOT NULL,
    result TEXT,
    error TEXT,
    notification_id TEXT,
    started_at TEXT,
    completed_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_agent_schedule_runs_schedule
    ON agent_schedule_runs(schedule_id, started_at);
CREATE INDEX IF NOT EXISTS idx_agent_schedule_runs_user
    ON agent_schedule_runs(user_id, started_at);
