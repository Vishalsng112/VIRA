"""Read-only, schema-aware database tools."""
from __future__ import annotations

import asyncio
from typing import Any

from pydantic import Field

from ...contract import BaseTool, StrictModel, ToolContext, ToolError
from ..common import JsonOutput


def _payload(value: Any) -> JsonOutput:
    if isinstance(value, dict):
        return JsonOutput(payload=value)
    return JsonOutput(payload={"result": value})


class TablesInput(StrictModel):
    query: str = ""
    limit: int = Field(default=20, ge=1, le=40)


class SchemaInput(StrictModel):
    table: str = ""
    search: str = ""
    include_row_counts: bool = False
    limit: int = Field(default=8, ge=1, le=20)


class ExamplesInput(StrictModel):
    pass


class AccountSummaryInput(StrictModel):
    pass


class QueryInput(StrictModel):
    sql: str = Field(min_length=8, max_length=20000)
    limit: int = Field(default=100, ge=1, le=200)


def _require_user(context: ToolContext) -> int:
    if not context.user_id:
        raise ToolError("auth_required", "An authenticated VIRA user is required.")
    return context.user_id


class DatabaseTablesTool(BaseTool):
    namespace = "database"
    name = "tables"
    title = "List database tables"
    description = "List queryable tables with short descriptions."
    when_to_use = "Use first when you need database facts and do not know the table."
    when_not_to_use = "Do not use for values; follow with database.schema and database.query."
    category = "database"
    tags = ("database", "sql", "tables", "schema", "analytics")
    input_model = TablesInput
    output_model = JsonOutput

    async def run(self, params: TablesInput, context: ToolContext) -> JsonOutput:
        from vira.tooling.services import database_query as dbq
        return _payload(await asyncio.to_thread(dbq.table_catalog, params.query, params.limit))


class DatabaseSchemaTool(BaseTool):
    namespace = "database"
    name = "schema"
    title = "Describe database tables"
    description = "Return column types, constraints and relationships for tables."
    when_to_use = "Use before writing custom SQL so column names and types are correct."
    when_not_to_use = "Do not use for row data."
    category = "database"
    tags = ("database", "sql", "schema", "columns", "table", "tables", "devices", "relationships")
    input_model = SchemaInput
    output_model = JsonOutput

    async def run(self, params: SchemaInput, context: ToolContext) -> JsonOutput:
        from vira.tooling.services import database_query as dbq
        return _payload(await asyncio.to_thread(
            dbq.describe_schema,
            params.table, params.search, params.include_row_counts, params.limit,
        ))


class DatabaseExamplesTool(BaseTool):
    namespace = "database"
    name = "examples"
    title = "Show safe SQL examples"
    description = "Return safe example queries for common VIRA questions."
    when_to_use = "Use as a template source before writing aggregate SQL."
    when_not_to_use = "Do not treat examples as live data."
    category = "database"
    tags = ("database", "sql", "examples", "queries")
    input_model = ExamplesInput
    output_model = JsonOutput

    async def run(self, params: ExamplesInput, context: ToolContext) -> JsonOutput:
        from vira.tooling.services import database_query as dbq
        return _payload(dbq.examples())


class DatabaseAccountSummaryTool(BaseTool):
    namespace = "database"
    name = "account_summary"
    title = "Summarise my account"
    description = "Return safe aggregate counts for the signed-in user's account."
    when_to_use = "Use for questions about the caller's devices, usage or activity."
    when_not_to_use = "Do not use to inspect another user's account."
    category = "database"
    tags = ("database", "account", "devices", "usage", "summary")
    input_model = AccountSummaryInput
    output_model = JsonOutput

    async def run(self, params: AccountSummaryInput, context: ToolContext) -> JsonOutput:
        from vira.tooling.services import database_query as dbq
        user_id = _require_user(context)
        return _payload(await asyncio.to_thread(dbq.account_summary, user_id))


class DatabaseQueryTool(BaseTool):
    namespace = "database"
    name = "query"
    title = "Run a read-only SQL query"
    description = "Run one SELECT/WITH statement and return columns and bounded rows."
    when_to_use = "Use after database.schema when a precise aggregate or filtered answer is needed."
    when_not_to_use = "Do not use for writes, schema changes or secret-bearing tables."
    category = "database"
    tags = ("database", "sql", "query", "select", "analytics")
    side_effects = "read"
    timeout_seconds = 30
    input_model = QueryInput
    output_model = JsonOutput

    async def run(self, params: QueryInput, context: ToolContext) -> JsonOutput:
        from vira.tooling.services import database_query as dbq
        user_id = _require_user(context)
        return _payload(await asyncio.to_thread(
            dbq.run_query, params.sql, params.limit, user_id
        ))


TOOLS = [
    DatabaseTablesTool,
    DatabaseSchemaTool,
    DatabaseExamplesTool,
    DatabaseAccountSummaryTool,
    DatabaseQueryTool,
]
