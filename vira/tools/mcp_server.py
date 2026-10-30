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

try:
    from vira.tools import webtools
except ImportError:  # launched as a script: python vira/tools/mcp_server.py
    import webtools

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
async def web_search(query: str, max_results: int = 8, region: str = "wt-wt") -> str:
    """Search the web. Returns a numbered list of title, URL and snippet.

    Use this FIRST for news, recent events, people, prices, or any fact you are not
    sure about. Then call web_browse on the best 1-2 URLs to read the details.
    Put the year in the query for recent events. Never guess URLs.
    """
    return await webtools.search(query, max_results, region)


@server.tool()
async def web_research(question: str, pages: int = 2) -> str:
    """Best single tool for questions needing current facts (news, people, events, lists).

    Searches the web, opens the top pages and returns their text with source URLs.
    Answer from that text and name the sources. Use web_search/web_browse only for follow-ups.
    """
    return await webtools.research(question, pages)


@server.tool()
async def web_browse(url: str, max_chars: int = 6000, offset: int = 0) -> str:
    """Open a public web page and return its readable text (tables as 'a | b | c' rows).

    Pass a full URL taken from web_search results. If the page is long, the reply
    ends with the offset to pass to read the next part.
    """
    return await webtools.fetch_page(url, max_chars, offset)


@server.tool()
async def execute_shell(command: str) -> str:
    """Execute an approved read-only command for runtime and system information.

    Commands are tokenized without a shell, so pipes, redirects, substitutions,
    chaining, and background execution are not supported.
    """
    max_output = 12_000
    allowed_commands = {
        "date", "df", "free", "git", "id", "ls", "pwd", "uname", "uptime", "whoami", "cat", "head", "tail", "wc", "stat", "find", "du", "env", "top", "ps",
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