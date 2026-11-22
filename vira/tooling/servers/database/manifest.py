from ...manifest import ServerManifest

MANIFEST = ServerManifest(
    id="database",
    title="Read-only database",
    description="Schema-aware read-only SQL over VIRA's own database.",
    version="1.0.0",
    instructions=(
        "Never guess column names. Use database.tables, then database.schema, "
        "then database.query. Only SELECT/WITH is accepted and secrets are hidden."
    ),
    category="database",
    tags=["database", "sql", "analytics"],
)
