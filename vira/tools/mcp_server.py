# mcp_server.py
import shlex
import subprocess
from mcp.server.fastmcp import FastMCP

server = FastMCP("example-tools")

@server.tool()
async def web_browse(url: str) -> str:
    """Fetch a web page (placeholder)."""
    return f"<html><body>Content of {url}</body></html>"

@server.tool()
async def execute_shell(command: str) -> str:
    """Execute a shell command and return its output."""
    try:
        args = shlex.split(command)
    except ValueError as exc:
        return f"Could not parse command: {exc}"
    result = subprocess.run(args, shell=False, capture_output=True, text=True, timeout=30)
    return result.stdout + result.stderr

if __name__ == "__main__":
    server.run(transport="stdio")