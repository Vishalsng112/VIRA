# Database tools (read-only)

VIRA ships a dedicated MCP server at `vira/tools/database_mcp_server.py`. It
lets the Chatbot and agents inspect the server database safely, without giving
them write access.

The server is enabled by default in `config.yaml`:

```yaml
database_mcp:
  enabled: true
  permissions: ["read", "execute"]
```

The orchestrator connects it at boot and registers the tools under the
`database_query` namespace.

## Tools

| Tool | Purpose |
|---|---|
| `database_query.database_tables` | List queryable tables, descriptions and key columns. |
| `database_query.database_schema` | Show full columns, types and foreign keys for matching tables. |
| `database_query.database_examples` | Curated SQL templates for common questions. |
| `database_query.database_account_summary` | Safe summary of the signed-in user's own account. |
| `database_query.database_query` | Run one custom `SELECT`/`WITH` query (administrators). |

The intended workflow for the model is:

```text
database_tables -> database_schema -> database_query
```

Example questions and queries:

```sql
-- Devices connected with the signed-in account
SELECT COUNT(DISTINCT d.id) AS devices
FROM devices d
JOIN user_device_access a ON a.device_id = d.id
WHERE a.user_id = {{caller_user_id}}
  AND a.status = 'active'
  AND d.status = 'active';

-- Devices connected with the server
SELECT status, COUNT(*) AS count
FROM devices
GROUP BY status;
```

`{{caller_user_id}}` is replaced by the authenticated caller's user id. The
agent loop injects that identity only for the `database_query.*` tools; the
model never needs to guess or type another user's id.

## Safety

- **Read-only connection**: SQLite is opened with `mode=ro` and
  `PRAGMA query_only = ON`; PostgreSQL sessions use
  `default_transaction_read_only`.
- **One statement only**: `SELECT` and `WITH` are allowed. Multiple statements
  and comments that hide additional statements are rejected.
- **Writes blocked**: `INSERT`, `UPDATE`, `DELETE`, `DROP`, `ALTER`, `CREATE`,
  `PRAGMA`, `ATTACH`, `VACUUM`, `GRANT`, `COPY` and similar keywords are
  rejected before execution.
- **Secret columns and tables hidden**: password hashes, recovery codes,
  session hashes, credential hashes, tokens, vectors and internal tables are
  excluded from the schema and blocked in queries.
- **Row cap and timeout**: at most 200 rows, with a short statement timeout.
- **Role gate**: custom SQL requires an administrator account. Every user can
  call `database_account_summary`, which only returns their own aggregate
  information.
- Every call still goes through the normal tool permission and audit path.

## Testing

```bash
python3 -m unittest vira.tests.test_database_query -v
```

The tests cover schema filtering, write rejection, secret-column rejection,
caller-scoped placeholders and the account summary.
