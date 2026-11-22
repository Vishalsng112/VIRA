"""MCP stdio entrypoint for the workspace domain."""
from vira.tooling.mcp import run_stdio
from vira.tooling.servers.workspace import MANIFEST, TOOLS


def main() -> None:
    run_stdio(MANIFEST, TOOLS)


if __name__ == "__main__":
    main()
