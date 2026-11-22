from ...manifest import ServerManifest

MANIFEST = ServerManifest(
    id="runtime",
    title="Runtime inspection",
    description="Approved read-only commands for system and repository state.",
    version="1.0.0",
    instructions=(
        "Use runtime.run only for bounded read-only inspection. It never "
        "accepts pipes, redirects, substitutions or write commands."
    ),
    category="runtime",
    tags=["runtime", "shell", "system", "read-only"],
)
