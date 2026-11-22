from ...manifest import ServerManifest

MANIFEST = ServerManifest(
    id="vira",
    title="VIRA core",
    description="User context, device insights, chat statistics and knowledge search.",
    version="1.0.0",
    instructions=(
        "Use vira.context before personalisation, vira.insights for activity "
        "questions, vira.knowledge_search for saved knowledge, and "
        "vira.chat_statistics only for aggregate counts."
    ),
    category="vira",
    tags=["vira", "context", "insights", "knowledge", "chat"],
)
