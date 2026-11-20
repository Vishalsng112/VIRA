"""Explicit, versioned schema migrations (VIRA multi-device design, section 6.3).

``database.init_db`` still creates the legacy baseline tables with
``CREATE TABLE IF NOT EXISTS``.  Everything introduced by the multi-user /
multi-device design is applied here, exactly once, and recorded in
``schema_migrations``.  The module is stdlib-only and independent of
``database`` so it can be unit-tested against any sqlite3 connection.
"""
import sqlite3
import uuid
from datetime import datetime, timezone
from typing import Callable, List, Set, Tuple


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _columns(conn: sqlite3.Connection, table: str) -> Set[str]:
    return {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    return conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (table,)
    ).fetchone() is not None


def _add_column(conn: sqlite3.Connection, table: str, column: str, ddl: str) -> None:
    if _table_exists(conn, table) and column not in _columns(conn, table):
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}")


# --------------------------------------------------------------------------- #
# 001 - users: public_id, lifecycle status
# --------------------------------------------------------------------------- #
def _m001_users(conn: sqlite3.Connection) -> None:
    _add_column(conn, "users", "public_id", "TEXT")
    _add_column(conn, "users", "status", "TEXT NOT NULL DEFAULT 'active'")
    _add_column(conn, "users", "deleted_at", "TIMESTAMP")
    _add_column(conn, "users", "updated_at", "TIMESTAMP")
    rows = conn.execute("SELECT id FROM users WHERE public_id IS NULL").fetchall()
    for row in rows:
        conn.execute("UPDATE users SET public_id = ? WHERE id = ?", (str(uuid.uuid4()), row[0]))
    conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS users_public_id_uq ON users(public_id)")


# --------------------------------------------------------------------------- #
# 002 - devices, credentials, user-device access, event provenance
# --------------------------------------------------------------------------- #
def _m002_devices(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS devices (
            id TEXT PRIMARY KEY,
            display_name TEXT NOT NULL,
            platform TEXT NOT NULL,
            device_type TEXT NOT NULL,
            os_version TEXT,
            client_version TEXT,
            capabilities TEXT NOT NULL DEFAULT '[]',
            capability_status TEXT NOT NULL DEFAULT '{}',
            status TEXT NOT NULL DEFAULT 'pending'
                CHECK (status IN ('pending', 'active', 'revoked', 'retired')),
            is_server_local INTEGER NOT NULL DEFAULT 0,
            created_by_user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
            created_at TIMESTAMP NOT NULL,
            updated_at TIMESTAMP NOT NULL,
            last_seen_at TIMESTAMP,
            last_event_at TIMESTAMP,
            revoked_at TIMESTAMP,
            ingest_error_count INTEGER NOT NULL DEFAULT 0,
            last_accepted_sequence INTEGER,
            queue_backlog INTEGER
        )
        """
    )
    # At most one device represents the VIRA server installation itself.
    conn.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS devices_server_local_uq "
        "ON devices(is_server_local) WHERE is_server_local = 1"
    )
    conn.execute("CREATE INDEX IF NOT EXISTS devices_by_status ON devices(status, created_at)")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS device_credentials (
            id TEXT PRIMARY KEY,
            device_id TEXT NOT NULL REFERENCES devices(id) ON DELETE CASCADE,
            credential_hash TEXT NOT NULL,
            scopes TEXT NOT NULL,
            created_at TIMESTAMP NOT NULL,
            expires_at TIMESTAMP,
            revoked_at TIMESTAMP,
            last_used_at TIMESTAMP,
            rotated_from TEXT
        )
        """
    )
    conn.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS devices_credentials_hash_uq "
        "ON device_credentials(credential_hash)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS device_credentials_by_device "
        "ON device_credentials(device_id, revoked_at)"
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS user_device_access (
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            device_id TEXT NOT NULL REFERENCES devices(id) ON DELETE CASCADE,
            access_role TEXT NOT NULL CHECK (access_role IN ('owner', 'operator', 'viewer')),
            status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'revoked')),
            granted_at TIMESTAMP NOT NULL,
            granted_by_user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
            revoked_at TIMESTAMP,
            PRIMARY KEY (user_id, device_id)
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS user_device_access_by_user "
        "ON user_device_access(user_id, status, device_id)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS user_device_access_by_device "
        "ON user_device_access(device_id, status, user_id)"
    )
    conn.execute(
        """
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
            occurred_at TIMESTAMP NOT NULL,
            received_at TIMESTAMP NOT NULL,
            correlation_id TEXT NOT NULL,
            causation_id TEXT,
            payload TEXT,
            payload_hash TEXT NOT NULL,
            expires_at TIMESTAMP
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS device_events_by_device_time "
        "ON device_events(device_id, occurred_at DESC)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS device_events_by_actor_time "
        "ON device_events(actor_user_id, occurred_at DESC)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS device_events_by_type_time "
        "ON device_events(event_type, received_at DESC)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS device_events_by_expiry ON device_events(expires_at)"
    )
    # Latest snapshot per device/event type: lets high-volume telemetry be
    # queried without keeping every raw payload (FR-EVT-09).
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS device_latest_state (
            device_id TEXT NOT NULL REFERENCES devices(id) ON DELETE CASCADE,
            event_type TEXT NOT NULL,
            event_id TEXT NOT NULL,
            occurred_at TIMESTAMP NOT NULL,
            received_at TIMESTAMP NOT NULL,
            payload TEXT NOT NULL,
            PRIMARY KEY (device_id, event_type)
        )
        """
    )


# --------------------------------------------------------------------------- #
# 003 - provenance columns on existing tables
# --------------------------------------------------------------------------- #
def _m003_provenance_columns(conn: sqlite3.Connection) -> None:
    _add_column(conn, "messages", "created_by_device_id", "TEXT REFERENCES devices(id) ON DELETE SET NULL")
    _add_column(conn, "incognito_messages", "created_by_device_id", "TEXT")
    _add_column(conn, "memories", "device_id", "TEXT")
    _add_column(conn, "outbox_events", "device_id", "TEXT")
    _add_column(conn, "auth_audit", "actor_type", "TEXT NOT NULL DEFAULT 'user'")
    _add_column(conn, "auth_audit", "target", "TEXT")
    _add_column(conn, "auth_audit", "device_id", "TEXT")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_audit_created ON auth_audit(created_at)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_memories_device ON memories(device_id)")


def _m004_jobs_and_rollups(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS jobs (
            id TEXT PRIMARY KEY,
            kind TEXT NOT NULL,
            payload TEXT NOT NULL DEFAULT '{}',
            status TEXT NOT NULL DEFAULT 'pending'
                CHECK (status IN ('pending', 'running', 'done', 'failed', 'dead')),
            priority INTEGER NOT NULL DEFAULT 0,
            attempts INTEGER NOT NULL DEFAULT 0,
            max_attempts INTEGER NOT NULL DEFAULT 5,
            available_at TIMESTAMP NOT NULL,
            locked_at TIMESTAMP,
            locked_by TEXT,
            last_error TEXT,
            dedupe_key TEXT,
            created_at TIMESTAMP NOT NULL,
            updated_at TIMESTAMP NOT NULL,
            completed_at TIMESTAMP
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_jobs_ready ON jobs(status, available_at, priority)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_jobs_kind ON jobs(kind, status)")
    conn.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_jobs_dedupe_active "
        "ON jobs(dedupe_key) WHERE dedupe_key IS NOT NULL AND status IN ('pending','running')"
    )
    conn.execute(
        """
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
            updated_at TIMESTAMP NOT NULL,
            PRIMARY KEY (device_id, day)
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_insight_daily_day ON insight_daily(day)")


def _m005_consent_schemas_commands_pairing(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
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
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_consents_device ON device_consents(device_id)")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS event_schemas (
            event_type TEXT NOT NULL,
            version INTEGER NOT NULL,
            schema_json TEXT NOT NULL,
            description TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            PRIMARY KEY (event_type, version)
        )
        """
    )
    conn.execute(
        """
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
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_commands_device_status ON device_commands(device_id, status, created_at)")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS device_pairing_codes (
            code_hash TEXT PRIMARY KEY,
            created_by_user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            created_at TEXT NOT NULL,
            expires_at TEXT NOT NULL,
            used_at TEXT,
            device_id TEXT REFERENCES devices(id) ON DELETE SET NULL
        )
        """
    )
    conn.execute(
        """
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
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_notifications_user ON user_notifications(user_id, status, created_at)")


def _m006_push_tokens(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS device_push_tokens (
            device_id TEXT NOT NULL REFERENCES devices(id) ON DELETE CASCADE,
            platform TEXT NOT NULL,
            token TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            PRIMARY KEY (device_id, token)
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_push_tokens_device ON device_push_tokens(device_id)")


def _m007_agent_run_events(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS agent_run_events (
            id TEXT PRIMARY KEY,
            run_id TEXT NOT NULL,
            seq INTEGER NOT NULL,
            event_type TEXT NOT NULL,
            data TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL,
            UNIQUE(run_id, seq)
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_run_events_run ON agent_run_events(run_id, seq)")


def _m008_durable_workflows(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
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
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_workflows_user ON workflows(created_by_user_id, created_at)")
    conn.execute(
        """
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
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_workflow_steps_status ON workflow_steps(workflow_id, status)")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS workflow_events (
            id TEXT PRIMARY KEY,
            workflow_id TEXT NOT NULL REFERENCES workflows(id) ON DELETE CASCADE,
            step_id TEXT,
            event_type TEXT NOT NULL,
            data TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_workflow_events ON workflow_events(workflow_id, created_at)")


def _m009_rag_vectors(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS memory_embeddings (
            memory_id TEXT PRIMARY KEY REFERENCES memories(id) ON DELETE CASCADE,
            user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
            model TEXT NOT NULL,
            dims INTEGER NOT NULL,
            vector TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_memory_embeddings_user ON memory_embeddings(user_id)")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS rag_documents (
            id TEXT PRIMARY KEY,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            title TEXT NOT NULL,
            source TEXT NOT NULL DEFAULT 'manual',
            metadata TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_rag_documents_user ON rag_documents(user_id, created_at)")
    conn.execute(
        """
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
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_rag_chunks_user ON rag_chunks(user_id, document_id)")


def _m010_p4_ecosystem(conn: sqlite3.Connection) -> None:
    # --- plugins -----------------------------------------------------------
    conn.execute(
        """
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
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS plugin_storage (
            plugin_id TEXT NOT NULL,
            key TEXT NOT NULL,
            value TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            PRIMARY KEY (plugin_id, key)
        )
        """
    )
    # --- MCP marketplace / allow-list -------------------------------------
    conn.execute(
        """
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
        )
        """
    )
    conn.execute(
        """
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
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_mcp_policies_subject ON mcp_policies(subject_type, subject_id)")
    # --- organizations / teams -------------------------------------------
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS organizations (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            slug TEXT NOT NULL UNIQUE,
            owner_user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS organization_members (
            organization_id TEXT NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            role TEXT NOT NULL DEFAULT 'member',
            created_at TEXT NOT NULL,
            PRIMARY KEY (organization_id, user_id)
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_org_members_user ON organization_members(user_id)")
    _add_column(conn, "workflows", "organization_id", "TEXT")
    _add_column(conn, "rag_documents", "organization_id", "TEXT")
    # --- object storage ---------------------------------------------------
    conn.execute(
        """
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
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_objects_user ON objects(user_id, created_at)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_objects_org ON objects(organization_id, created_at)")
    # --- cost / quota accounting -----------------------------------------
    conn.execute(
        """
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
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_llm_usage_user ON llm_usage(user_id, created_at)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_llm_usage_org ON llm_usage(organization_id, created_at)")
    conn.execute(
        """
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
        )
        """
    )
    # --- update channel ---------------------------------------------------
    conn.execute(
        """
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
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_updates_lookup ON update_releases(product, channel, published_at)")


def _m012_agent_approvals(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
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
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_approvals_user_status "
        "ON agent_approvals(user_id, status, created_at)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_approvals_match "
        "ON agent_approvals(user_id, tool_name, fingerprint, status)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_approvals_run ON agent_approvals(run_id)"
    )


def _m011_device_installation(conn: sqlite3.Connection) -> None:
    _add_column(conn, "devices", "installation_id", "TEXT")
    conn.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS devices_installation_uq "
        "ON devices(created_by_user_id, installation_id) "
        "WHERE installation_id IS NOT NULL"
    )


MIGRATIONS: List[Tuple[int, str, Callable[[sqlite3.Connection], None]]] = [
    (1, "users_public_id_and_status", _m001_users),
    (2, "devices_credentials_access_events", _m002_devices),
    (3, "provenance_columns", _m003_provenance_columns),
    (4, "durable_jobs_and_daily_rollups", _m004_jobs_and_rollups),
    (5, "consent_schemas_commands_pairing", _m005_consent_schemas_commands_pairing),
    (6, "push_tokens", _m006_push_tokens),
    (7, "agent_run_events", _m007_agent_run_events),
    (8, "durable_workflows", _m008_durable_workflows),
    (9, "rag_vectors", _m009_rag_vectors),
    (10, "p4_ecosystem", _m010_p4_ecosystem),
    (11, "device_installation_identity", _m011_device_installation),
    (12, "agent_approvals", _m012_agent_approvals),
]


def apply_migrations(conn: sqlite3.Connection) -> List[int]:
    """Apply pending migrations in order; return the versions applied."""
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            applied_at TIMESTAMP NOT NULL
        )
        """
    )
    done = {row[0] for row in conn.execute("SELECT version FROM schema_migrations")}
    applied: List[int] = []
    for version, name, fn in MIGRATIONS:
        if version in done:
            continue
        fn(conn)
        conn.execute(
            "INSERT INTO schema_migrations (version, name, applied_at) VALUES (?, ?, ?)",
            (version, name, _utc_now()),
        )
        conn.commit()
        applied.append(version)
    return applied
