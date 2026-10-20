# mcp_server.py
import shlex
import subprocess
import json
import asyncio
import os
from html.parser import HTMLParser
from urllib.parse import urlparse

import aiohttp
from mcp.server.fastmcp import FastMCP

server = FastMCP("example-tools")


class _ReadableTextParser(HTMLParser):
    """Extract readable text while dropping page chrome and executable content."""

    _ignored_tags = {"script", "style", "noscript", "svg", "template"}

    def __init__(self):
        super().__init__()
        self._ignored_depth = 0
        self.parts: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag.lower() in self._ignored_tags:
            self._ignored_depth += 1

    def handle_endtag(self, tag):
        if tag.lower() in self._ignored_tags and self._ignored_depth:
            self._ignored_depth -= 1

    def handle_data(self, data):
        if not self._ignored_depth:
            text = " ".join(data.split())
            if text:
                self.parts.append(text)


def _extract_readable_text(body: str, limit: int = 12000) -> str:
    parser = _ReadableTextParser()
    parser.feed(body)
    text = " ".join(parser.parts)
    return text[:limit]


@server.tool()
async def web_browse(url: str) -> str:
    """Fetch a public web page and return bounded readable text for research."""
    parsed = urlparse(url.strip())
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        return json.dumps({"error": "Only absolute http:// or https:// URLs are supported."})
    if parsed.username or parsed.password:
        return json.dumps({"error": "URLs containing credentials are not allowed."})
    if parsed.hostname.lower() in {"localhost", "127.0.0.1", "::1"}:
        return json.dumps({"error": "Local URLs are not allowed."})

    timeout = aiohttp.ClientTimeout(total=15, connect=5)
    headers = {"User-Agent": "VIRA research browser/1.0", "Accept": "text/html,text/plain"}
    try:
        async with aiohttp.ClientSession(timeout=timeout, headers=headers) as session:
            async with session.get(url, allow_redirects=True, max_redirects=3) as response:
                content_type = response.headers.get("content-type", "").lower()
                if response.status >= 400:
                    return json.dumps({"url": url, "status": response.status, "error": "Page request failed."})
                if "text/" not in content_type and "html" not in content_type:
                    return json.dumps({
                        "url": str(response.url),
                        "status": response.status,
                        "error": f"Unsupported content type: {content_type or 'unknown'}",
                    })
                body = await response.content.read(1_000_000)
                decoded = body.decode(response.charset or "utf-8", errors="replace")
                text = _extract_readable_text(decoded)
                return json.dumps({
                    "url": str(response.url),
                    "status": response.status,
                    "content_type": content_type,
                    "content": text,
                    "truncated": len(text) >= 12000,
                })
    except (aiohttp.ClientError, asyncio.TimeoutError, UnicodeError) as exc:
        return json.dumps({"url": url, "error": f"Unable to fetch page: {exc}"})

@server.tool()
async def execute_shell(command: str) -> str:
    """Execute an approved read-only command for runtime and system information.

    Commands are tokenized without a shell, so pipes, redirects, substitutions,
    chaining, and background execution are not supported.
    """
    max_output = 12_000
    allowed_commands = {
        "date", "df", "free", "git", "id", "ls", "pwd", "uname", "uptime", "whoami",
    }
    blocked_tokens = {";", "&&", "||", "|", ">", ">>", "<", "$(", "`", "&"}
    try:
        args = shlex.split(command)
    except ValueError as exc:
        return json.dumps({"ok": False, "error": f"Could not parse command: {exc}"})
    if not args:
        return json.dumps({"ok": False, "error": "A command is required."})
    if any(token in blocked_tokens for token in args) or any(
        marker in command for marker in ("$(", ")", "`", "\n", "\r")
    ):
        return json.dumps({"ok": False, "error": "Shell operators and command chaining are not allowed."})

    executable = os.path.basename(args[0])
    if executable not in allowed_commands:
        return json.dumps({
            "ok": False,
            "error": f"Command '{executable}' is not approved.",
            "allowed_commands": sorted(allowed_commands),
        })

    if executable == "git" and (len(args) < 2 or args[1] not in {
        "branch", "diff", "log", "show", "status", "rev-parse",
    }):
        return json.dumps({"ok": False, "error": "Only read-only git subcommands are allowed."})
    if executable == "ls" and any(arg in {"-R", "--recursive"} for arg in args[1:]):
        return json.dumps({"ok": False, "error": "Recursive directory listing is not allowed."})

    try:
        result = await asyncio.to_thread(
            subprocess.run,
            args,
            shell=False,
            cwd=os.getcwd(),
            env={"PATH": os.environ.get("PATH", "")},
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return json.dumps({"ok": False, "error": "Command timed out after 15 seconds."})
    except OSError as exc:
        return json.dumps({"ok": False, "error": f"Command could not be started: {exc}"})

    stdout = result.stdout[:max_output]
    stderr = result.stderr[:max_output]
    return json.dumps({
        "ok": result.returncode == 0,
        "command": args,
        "exit_code": result.returncode,
        "stdout": stdout,
        "stderr": stderr,
        "truncated": len(result.stdout) > max_output or len(result.stderr) > max_output,
    })

if __name__ == "__main__":
    server.run(transport="stdio")