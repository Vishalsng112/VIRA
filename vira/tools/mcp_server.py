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
async def web_search(query: str, max_results: int = 8, region: str = "wt-wt") -> str:
    """Search the web and return a ranked JSON list of {title, url, snippet}.

    Use this FIRST when you need to find pages about a topic, news, or "latest" information.
    Then call web_browse on the most relevant result URLs to read them in full.
    `region` is a DuckDuckGo region code such as "in-en", "us-en" or "wt-wt" (worldwide).
    Never guess URLs when you can search for them.
    """
    import asyncio
    import json
    import os
    import time
    from urllib.parse import parse_qs, urlparse

    import aiohttp
    from bs4 import BeautifulSoup

    # ---- settings ---------------------------------------------------------
    cache_ttl = 300          # seconds a cached result stays valid
    cache_max = 256          # max cached queries
    min_interval = 1.0       # seconds between outbound search requests
    max_query_chars = 300
    browser_ua = (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0 Safari/537.36 VIRA-research/1.0"
    )
    timeout = aiohttp.ClientTimeout(total=20, connect=10)

    # ---- persistent state shared across calls (cache + throttle) ----------
    state = globals().setdefault("_VIRA_SEARCH_STATE", {"cache": {}, "last": 0.0, "lock": None})
    if state["lock"] is None:
        state["lock"] = asyncio.Lock()

    # ---- input validation -------------------------------------------------
    query = " ".join((query or "").split())
    if not query:
        raise ValueError("query must not be empty")
    if len(query) > max_query_chars:
        raise ValueError(f"query too long (max {max_query_chars} characters)")
    max_results = max(1, min(int(max_results), 20))

    chain = [
        name.strip()
        for name in os.getenv("VIRA_SEARCH_BACKENDS", "searxng,ddg_html,brave").split(",")
        if name.strip()
    ]

    cache_key = (tuple(chain), query.lower(), max_results, region)
    hit = state["cache"].get(cache_key)
    if hit and time.monotonic() - hit[0] < cache_ttl:
        return hit[1]

    # ---- helpers ----------------------------------------------------------
    class BackendUnavailable(Exception):
        """Backend not configured (missing URL/key): skipped, not counted as a failure."""

    def describe(exc: BaseException) -> str:
        # asyncio.TimeoutError has an empty str(), so always include the type name.
        msg = str(exc)
        return f"{type(exc).__name__}: {msg}" if msg else type(exc).__name__

    async def http_get(session, url, params=None, headers=None, retries=2) -> str:
        """GET with retry/backoff on timeouts, connection errors, 429 and 5xx."""
        last = "unknown error"
        for attempt in range(retries + 1):
            try:
                async with session.get(url, params=params, headers=headers) as resp:
                    if resp.status == 429 or resp.status >= 500:
                        last = f"HTTP {resp.status}"
                    elif resp.status >= 400:
                        raise RuntimeError(f"HTTP {resp.status}")  # not retryable
                    else:
                        return await resp.text()
            except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
                last = describe(exc)
            if attempt < retries:
                await asyncio.sleep(1.5 ** attempt)
        raise RuntimeError(f"{last} (after {retries + 1} attempts)")

    # ---- backends: each returns [{"title", "url", "snippet"}, ...] --------
    async def searxng(session):
        base = os.getenv("VIRA_SEARXNG_URL", "").rstrip("/")
        if not base:
            raise BackendUnavailable("VIRA_SEARXNG_URL not set")
        body = await http_get(session, f"{base}/search", params={"q": query, "format": "json"})
        try:
            data = json.loads(body)
        except json.JSONDecodeError as exc:
            raise RuntimeError("SearXNG did not return JSON (enable the json format in settings.yml)") from exc
        results = [
            {"title": r.get("title", ""), "url": r.get("url", ""), "snippet": r.get("content", "")}
            for r in data.get("results", [])
            if r.get("url")
        ]
        if not results:
            raise RuntimeError("no results")
        return results[:max_results]

    async def ddg_html(session):
        html = await http_get(
            session,
            "https://html.duckduckgo.com/html/",
            params={"q": query, "kl": region},
            headers={"Accept": "text/html"},
        )
        soup = BeautifulSoup(html, "html.parser")
        results = []
        for block in soup.select("div.result"):
            if "result--ad" in (block.get("class") or []):
                continue
            link = block.select_one("a.result__a")
            if not link or not link.get("href"):
                continue
            href = link["href"]
            if href.startswith("//"):
                href = "https:" + href
            target = parse_qs(urlparse(href).query).get("uddg")  # unwrap DDG redirect link
            snippet = block.select_one(".result__snippet")
            results.append({
                "title": link.get_text(" ", strip=True),
                "url": target[0] if target else href,
                "snippet": snippet.get_text(" ", strip=True) if snippet else "",
            })
            if len(results) >= max_results:
                break
        if not results:
            raise RuntimeError("no results parsed (blocked, CAPTCHA, or page layout changed)")
        return results

    async def brave(session):
        key = os.getenv("BRAVE_API_KEY")
        if not key:
            raise BackendUnavailable("BRAVE_API_KEY not set")
        body = await http_get(
            session,
            "https://api.search.brave.com/res/v1/web/search",
            params={"q": query, "count": min(max_results, 20)},
            headers={"X-Subscription-Token": key, "Accept": "application/json"},
        )
        items = json.loads(body).get("web", {}).get("results", [])
        results = [
            {"title": r.get("title", ""), "url": r.get("url", ""), "snippet": r.get("description", "")}
            for r in items
            if r.get("url")
        ]
        if not results:
            raise RuntimeError("no results")
        return results[:max_results]

    backends = {"searxng": searxng, "ddg_html": ddg_html, "brave": brave}

    # ---- run the fallback chain -------------------------------------------
    problems = []
    async with aiohttp.ClientSession(
        timeout=timeout, headers={"User-Agent": browser_ua}, trust_env=True
    ) as session:
        for name in chain:
            backend = backends.get(name)
            if backend is None:
                problems.append(f"{name}: unknown backend")
                continue
            try:
                async with state["lock"]:  # politeness: space out outbound requests
                    wait = min_interval - (time.monotonic() - state["last"])
                    if wait > 0:
                        await asyncio.sleep(wait)
                    state["last"] = time.monotonic()
                results = await backend(session)
            except BackendUnavailable as exc:
                problems.append(f"{name}: skipped ({exc})")
                continue
            except Exception as exc:  # noqa: BLE001 - fall through to the next backend
                problems.append(f"{name}: {describe(exc)}")
                continue

            payload = json.dumps(
                {"query": query, "backend": name, "results": results}, ensure_ascii=False
            )
            if len(state["cache"]) >= cache_max:
                state["cache"].pop(next(iter(state["cache"])))
            state["cache"][cache_key] = (time.monotonic(), payload)
            return payload

    # Raising (instead of returning JSON) makes MCP report isError=True,
    # so the agent knows the call failed and can retry or change strategy.
    raise RuntimeError(
        "All search backends failed. " + " | ".join(problems)
        + ". Check outbound network access from the server, or set VIRA_SEARXNG_URL / BRAVE_API_KEY."
    )


# @server.tool()
# async def web_browse(url: str) -> str:
#     """Fetch a public web page and return bounded readable text for research."""
#     parsed = urlparse(url.strip())
#     if parsed.scheme not in {"http", "https"} or not parsed.hostname:
#         return json.dumps({"error": "Only absolute http:// or https:// URLs are supported."})
#     if parsed.username or parsed.password:
#         return json.dumps({"error": "URLs containing credentials are not allowed."})
#     if parsed.hostname.lower() in {"localhost", "127.0.0.1", "::1"}:
#         return json.dumps({"error": "Local URLs are not allowed."})

#     timeout = aiohttp.ClientTimeout(total=15, connect=5)
#     headers = {"User-Agent": "VIRA research browser/1.0", "Accept": "text/html,text/plain"}
#     try:
#         async with aiohttp.ClientSession(timeout=timeout, headers=headers) as session:
#             async with session.get(url, allow_redirects=True, max_redirects=3) as response:
#                 content_type = response.headers.get("content-type", "").lower()
#                 if response.status >= 400:
#                     return json.dumps({"url": url, "status": response.status, "error": "Page request failed."})
#                 if "text/" not in content_type and "html" not in content_type:
#                     return json.dumps({
#                         "url": str(response.url),
#                         "status": response.status,
#                         "error": f"Unsupported content type: {content_type or 'unknown'}",
#                     })
#                 body = await response.content.read(1_000_000)
#                 decoded = body.decode(response.charset or "utf-8", errors="replace")
#                 text = _extract_readable_text(decoded)
#                 return json.dumps({
#                     "url": str(response.url),
#                     "status": response.status,
#                     "content_type": content_type,
#                     "content": text,
#                     "truncated": len(text) >= 12000,
#                 })
#     except (aiohttp.ClientError, asyncio.TimeoutError, UnicodeError) as exc:
#         return json.dumps({"url": url, "error": f"Unable to fetch page: {exc}"})

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