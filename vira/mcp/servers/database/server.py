"""MCP stdio entrypoint for the database domain."""
from vira.tooling.mcp import run_stdio
from vira.tooling.servers.database import MANIFEST, TOOLS


def main() -> None:
    run_stdio(MANIFEST, TOOLS)


if __name__ == "__main__":
    main()
