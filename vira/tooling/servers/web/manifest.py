from ...manifest import ServerManifest

MANIFEST = ServerManifest(
    id="web",
    title="Web research",
    description="Search, browse and research public web content.",
    version="1.0.0",
    instructions=(
        "Use web.search for discovery, web.browse for a known URL, and "
        "web.research when several sources must be read and cited."
    ),
    category="web",
    tags=["web", "search", "research", "news"],
)
