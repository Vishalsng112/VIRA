from ...manifest import ServerManifest

MANIFEST = ServerManifest(
    id="workspace",
    title="Workspace files",
    description="Read, write, list and search files inside one workspace root.",
    version="1.0.0",
    instructions=(
        "All paths are relative to the configured workspace root. Read or list "
        "before writing when the existing content matters."
    ),
    category="workspace",
    tags=["files", "workspace", "code", "filesystem"],
)
