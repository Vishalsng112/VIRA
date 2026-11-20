"""VIRA database MCP server.

Exposes read-only, schema-aware tools so the Chatbot and agents can answer
questions such as "how many devices are connected with my account?" without
inventing SQL.  Only SELECT/WITH statements are accepted, the connection is
read-only, and custom queries are restricted to administrators.

Run manually:
    python vira/tools/database_mcp_server.py
"""
import asyncio
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from mcp.server.fastmcp import FastMCP  # noqa: E402

from vira.tools import database_query as dbq  # noqa: E402

server = FastMCP("database_query")


@server.tool()
async def database_tables(query: str = "", limit: int = 20) -> str:
    """List the database tables that can be queried, with descriptions.

    Start here when you need database facts. Filter with words such as
    "devices", "users", "agents", "conversations" or "usage". Then call
    database_schema for the exact columns of the tables you need.

    Args:
        query: Optional words to filter tables by name, description or column.
        limit: Maximum tables to return (1-40).
    """
    return dbq.as_json(await asyncio.to_thread(dbq.table_catalog, query, limit))


@server.tool()
async def database_schema(
    table: str = "",
    search: str = "",
    include_row_counts: bool = False,
    limit: int = 8,
) -> str:
    """Return full columns, types and foreign-key relationships for tables.

    Use this BEFORE writing custom SQL. Secrets are excluded: password hashes,
    credential hashes, session hashes, API keys, tokens and vectors never
    appear. For the signed-in user use {{caller_user_id}} in SQL. With no
    arguments a compact core schema is returned.

    Args:
        table: Exact/partial table name, for example "devices".
        search: Alternative search words, for example "device account".
        include_row_counts: Include a COUNT(*) for each returned table.
        limit: Maximum tables to describe (1-20).
    """
    return dbq.as_json(
        await asyncio.to_thread(
            dbq.describe_schema, table, search, include_row_counts, limit
        )
    )


@server.tool()
async def database_examples() -> str:
    """Show safe example SQL for common questions.

    Includes device counts for the signed-in user and for the whole server,
    active agents, recent conversations, tool-call outcomes and stale devices.
    Use these as templates, then adapt them with database_schema.
    """
    return dbq.as_json(dbq.examples())


@server.tool()
async def database_account_summary(vira_caller_user_id: int | None = None) -> str:
    """Summarise the signed-in user's own account.

    Safe for every user: device counts by status, active devices, queued
    events, conversations, messages, memories, active sessions and unread
    notifications. Use this for "my account", "my devices" or "my usage"
    questions. Never asks for or reveals another user's data.

    Args:
        vira_caller_user_id: Internal identity supplied by VIRA; leave unset.
    """
    return dbq.as_json(await asyncio.to_thread(dbq.account_summary, vira_caller_user_id))


@server.tool()
async def database_query(
    sql: str,
    limit: int = 100,
    vira_caller_user_id: int | None = None,
) -> str:
    """Run one custom read-only SQL query and return columns and rows.

    Rules enforced by the server:
    - Only a single SELECT or WITH query is allowed. INSERT, UPDATE, DELETE,
      DROP, ALTER, CREATE, PRAGMA, ATTACH and every other write operation are
      rejected; the database connection is also opened read-only.
    - Maximum 200 rows are returned. Add ORDER BY and filters for useful results.
    - Secret columns (password, credential, session hashes, tokens, vectors)
      and internal tables are blocked.
    - Custom SQL requires an administrator account. For the signed-in user's
      own data use database_account_summary or the {{caller_user_id}}
      placeholder, for example:
      SELECT COUNT(*) FROM user_device_access WHERE user_id = {{caller_user_id}};

    Workflow: database_tables -> database_schema -> database_query. Prefer
    aggregate queries (COUNT, GROUP BY) for summaries.

    Args:
        sql: A single SELECT/WITH statement.
        limit: Maximum rows (1-200, default 100).
        vira_caller_user_id: Internal identity supplied by VIRA; leave unset.
    """
    return dbq.as_json(
        await asyncio.to_thread(dbq.run_query, sql, limit, vira_caller_user_id)
    )


if __name__ == "__main__":
    server.run(transport="stdio")
