"""Free, keyless web search + page fetch for the VIRA MCP server.

Search tries several backends in order and returns the first that works, so a
single engine blocking scripted traffic no longer kills the tool:
    searxng (your own instance) -> ddg_html -> ddg_lite -> bing -> mojeek
    -> brave (API key) -> wikipedia (JSON API, always allowed)
Override the order with VIRA_SEARCH_BACKENDS="bing,mojeek,wikipedia".

Debug from a terminal (shows every backend's result or error):
    python vira/tools/webtools.py search "bigg boss contestants"
    python vira/tools/webtools.py fetch https://en.wikipedia.org/wiki/Python
"""
import asyncio
import base64
import ipaddress
import json
import os
import re
import socket
import sys
import time
from typing import Dict, List, Optional, Tuple
from urllib.parse import parse_qs, quote, urljoin, urlparse

import aiohttp

try:
    from bs4 import BeautifulSoup
except ImportError:  # reported at call time, so the MCP server still starts
    BeautifulSoup = None

UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/126.0 Safari/537.36")
BROWSER_HEADERS = {"User-Agent": UA, "Accept-Language": "en-US,en;q=0.9"}
DEFAULT_BACKENDS = "searxng,ddg_html,ddg_lite,bing,mojeek,brave,wikipedia"
CACHE_TTL, CACHE_MAX, MIN_INTERVAL, DEADLINE = 300, 256, 1.0, 40.0
MAX_BODY = 2_000_000
_SEARCH_ENGINE_HOSTS = ("bing.com", "duckduckgo.com", "mojeek.com")
_state = {"cache": {}, "last": 0.0, "lock": None}


class BackendUnavailable(Exception):
    """Backend not configured (missing URL/key): skipped, not a failure."""


class Blocked(RuntimeError):
    """Engine refused scripted traffic (CAPTCHA / 202 / 403 / 429)."""


def _describe(exc: BaseException) -> str:
    msg = str(exc)
    return f"{type(exc).__name__}: {msg}" if msg else type(exc).__name__


def _soup(markup: str):
    if BeautifulSoup is None:
        raise RuntimeError("beautifulsoup4 is not installed (pip install beautifulsoup4)")
    return BeautifulSoup(markup, "html.parser")


# ---------------------------------------------------------------- HTTP
async def _request(session, url, *, params=None, data=None, headers=None, retries=1) -> str:
    last = "unknown error"
    for attempt in range(retries + 1):
        try:
            async with session.request("POST" if data is not None else "GET", url,
                                       params=params, data=data, headers=headers) as resp:
                if resp.status in (202, 403, 429):
                    raise Blocked(f"HTTP {resp.status} (rate-limited or bot-blocked)")
                if resp.status >= 500:
                    last = f"HTTP {resp.status}"
                elif resp.status >= 400:
                    raise RuntimeError(f"HTTP {resp.status}")
                else:
                    return await resp.text(errors="replace")
        except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
            last = _describe(exc)
        if attempt < retries:
            await asyncio.sleep(1)
    raise RuntimeError(f"{last} (after {retries + 1} attempts)")


# ---------------------------------------------------------------- parsers
def _clean_url(href: str) -> Optional[str]:
    """Unwrap DuckDuckGo / Bing redirect links; return None for non-web URLs."""
    if not href:
        return None
    if href.startswith("//"):
        href = "https:" + href
    parsed = urlparse(href)
    qs = parse_qs(parsed.query)
    if "uddg" in qs:  # duckduckgo.com/l/?uddg=<url>
        href = qs["uddg"][0]
    elif parsed.netloc.endswith("bing.com") and parsed.path.startswith("/ck/") and qs.get("u"):
        token = qs["u"][0]
        if token.startswith("a1"):
            try:
                raw = token[2:]
                href = base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4)).decode("utf-8", "replace")
            except Exception:
                return None
    parsed = urlparse(href)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        return None
    if parsed.hostname.endswith(_SEARCH_ENGINE_HOSTS):
        return None  # engine's own links (ads, navigation)
    return href


def _finish(rows, limit: int) -> List[Dict[str, str]]:
    out, seen = [], set()
    for title, href, snippet in rows:
        url = _clean_url(href)
        if not url or url in seen or not title:
            continue
        seen.add(url)
        out.append({"title": title, "url": url, "snippet": snippet})
        if len(out) >= limit:
            break
    return out


def _text(node) -> str:
    return node.get_text(" ", strip=True) if node else ""


def parse_ddg_html(html: str, limit: int):
    if "anomaly-modal" in html or "Unfortunately, bots use DuckDuckGo too" in html:
        raise Blocked("DuckDuckGo showed a bot challenge")
    soup = _soup(html)
    rows = []
    for block in soup.select("div.result"):
        if "result--ad" in (block.get("class") or []):
            continue
        link = block.select_one("a.result__a")
        if link:
            rows.append((_text(link), link.get("href", ""), _text(block.select_one(".result__snippet"))))
    return _finish(rows, limit)


def parse_ddg_lite(html: str, limit: int):
    if "anomaly-modal" in html or "bots use DuckDuckGo" in html:
        raise Blocked("DuckDuckGo showed a bot challenge")
    soup = _soup(html)
    rows = []
    for link in soup.select("a.result-link"):
        snippet = link.find_next("td", class_="result-snippet")
        rows.append((_text(link), link.get("href", ""), _text(snippet)))
    return _finish(rows, limit)


def parse_bing(html: str, limit: int):
    soup = _soup(html)
    rows = []
    for item in soup.select("li.b_algo"):
        link = item.select_one("h2 a")
        if link:
            snippet = item.select_one(".b_caption p") or item.select_one("p")
            rows.append((_text(link), link.get("href", ""), _text(snippet)))
    return _finish(rows, limit)


def parse_mojeek(html: str, limit: int):
    soup = _soup(html)
    rows = []
    for item in soup.select("ul.results-standard > li"):
        link = item.select_one("a.title") or item.select_one("h2 a")
        if link:
            rows.append((_text(link), link.get("href", ""), _text(item.select_one("p.s"))))
    return _finish(rows, limit)


# ---------------------------------------------------------------- backends
def _make_backends(query: str, limit: int, region: str):
    cc = region.split("-")[0].upper() if region and region != "wt-wt" else None

    async def searxng(s):
        base = os.getenv("VIRA_SEARXNG_URL", "").rstrip("/")
        if not base:
            raise BackendUnavailable("VIRA_SEARXNG_URL not set")
        body = await _request(s, f"{base}/search", params={"q": query, "format": "json"})
        try:
            data = json.loads(body)
        except json.JSONDecodeError as exc:
            raise RuntimeError("SearXNG did not return JSON (enable json format in settings.yml)") from exc
        rows = [(r.get("title", ""), r.get("url", ""), r.get("content", "")) for r in data.get("results", [])]
        return _finish(rows, limit)

    async def ddg_html(s):
        html = await _request(s, "https://html.duckduckgo.com/html/", data={"q": query, "kl": region},
                              headers={"Referer": "https://html.duckduckgo.com/", "Origin": "https://html.duckduckgo.com"})
        return parse_ddg_html(html, limit)

    async def ddg_lite(s):
        html = await _request(s, "https://lite.duckduckgo.com/lite/", data={"q": query, "kl": region},
                              headers={"Referer": "https://lite.duckduckgo.com/"})
        return parse_ddg_lite(html, limit)

    async def bing(s):
        params = {"q": query, "setlang": "en", "count": min(limit + 5, 30)}
        if cc:
            params["cc"] = cc
        return parse_bing(await _request(s, "https://www.bing.com/search", params=params), limit)

    async def mojeek(s):
        return parse_mojeek(await _request(s, "https://www.mojeek.com/search", params={"q": query}), limit)

    async def brave(s):
        key = os.getenv("BRAVE_API_KEY")
        if not key:
            raise BackendUnavailable("BRAVE_API_KEY not set")
        body = await _request(s, "https://api.search.brave.com/res/v1/web/search",
                              params={"q": query, "count": min(limit, 20)},
                              headers={"X-Subscription-Token": key, "Accept": "application/json"})
        items = json.loads(body).get("web", {}).get("results", [])
        return _finish([(r.get("title", ""), r.get("url", ""), r.get("description", "")) for r in items], limit)

    async def wikipedia(s):
        body = await _request(s, "https://en.wikipedia.org/w/api.php", params={
            "action": "query", "list": "search", "srsearch": query, "srlimit": limit, "format": "json"})
        rows = []
        for r in json.loads(body).get("query", {}).get("search", []):
            title = r.get("title", "")
            rows.append((title, "https://en.wikipedia.org/wiki/" + quote(title.replace(" ", "_")),
                         re.sub(r"<[^>]+>", "", r.get("snippet", ""))))
        return _finish(rows, limit)

    return {"searxng": searxng, "ddg_html": ddg_html, "ddg_lite": ddg_lite, "bing": bing,
            "mojeek": mojeek, "brave": brave, "wikipedia": wikipedia}


def format_results(query: str, backend: str, results: List[Dict[str, str]]) -> str:
    lines = [f'Search results for "{query}" (via {backend}). Open the best URLs with web_browse.']
    for i, r in enumerate(results, 1):
        lines.append(f"{i}. {r['title']}\n   {r['url']}" + (f"\n   {r['snippet'][:300]}" if r["snippet"] else ""))
    return "\n".join(lines)


async def search(query: str, max_results: int = 8, region: str = "wt-wt") -> str:
    query = " ".join((query or "").split())
    if not query:
        raise ValueError("query must not be empty")
    if len(query) > 300:
        raise ValueError("query too long (max 300 characters)")
    limit = max(1, min(int(max_results), 20))
    chain = [n.strip() for n in os.getenv("VIRA_SEARCH_BACKENDS", DEFAULT_BACKENDS).split(",") if n.strip()]

    key = (tuple(chain), query.lower(), limit, region)
    hit = _state["cache"].get(key)
    if hit and time.monotonic() - hit[0] < CACHE_TTL:
        return hit[1]
    if _state["lock"] is None:
        _state["lock"] = asyncio.Lock()

    backends = _make_backends(query, limit, region)
    problems, started = [], time.monotonic()
    timeout = aiohttp.ClientTimeout(total=10, connect=5)
    async with aiohttp.ClientSession(timeout=timeout, headers=BROWSER_HEADERS, trust_env=True) as session:
        for name in chain:
            if time.monotonic() - started > DEADLINE:
                problems.append("stopped: time budget used")
                break
            backend = backends.get(name)
            if backend is None:
                problems.append(f"{name}: unknown backend")
                continue
            try:
                async with _state["lock"]:  # space out outbound requests
                    wait = MIN_INTERVAL - (time.monotonic() - _state["last"])
                    if wait > 0:
                        await asyncio.sleep(wait)
                    _state["last"] = time.monotonic()
                results = await backend(session)
                if not results:
                    raise RuntimeError("no results parsed (blocked or page layout changed)")
            except BackendUnavailable as exc:
                problems.append(f"{name}: skipped ({exc})")
                continue
            except Exception as exc:  # noqa: BLE001 - try the next backend
                problems.append(f"{name}: {_describe(exc)}")
                continue
            payload = format_results(query, name, results)
            if len(_state["cache"]) >= CACHE_MAX:
                _state["cache"].pop(next(iter(_state["cache"])))
            _state["cache"][key] = (time.monotonic(), payload)
            return payload
    raise RuntimeError("All search backends failed: " + " | ".join(problems)
                       + ". Check this machine's internet/proxy access (run: python vira/tools/webtools.py search \"test\").")


# ---------------------------------------------------------------- fetch
_NOISE = ["script", "style", "noscript", "svg", "template", "iframe", "form", "nav", "footer", "aside", "header"]
_NOISE_CSS = ["sup.reference", ".mw-editsection", ".navbox", ".toc", ".mw-jump-link", "[role=navigation]"]


def extract_text(markup: str) -> Tuple[str, str]:
    """(title, readable text). Tables become 'a | b | c' rows; main content preferred."""
    soup = _soup(markup)
    title = _text(soup.title)
    for sel in _NOISE_CSS:
        for el in soup.select(sel):
            el.decompose()
    for tag in soup(_NOISE):
        tag.decompose()
    for tr in soup.find_all("tr"):
        try:
            cells = [_text(c) for c in tr.find_all(["th", "td"])]
            tr.replace_with(soup.new_string(" | ".join(c for c in cells if c) + "\n"))
        except ValueError:  # nested row already replaced
            continue
    root = soup.select_one("#mw-content-text") or soup.find("main") or soup.find("article") or soup.body or soup
    text = root.get_text("\n")
    if len(text.strip()) < 300 and soup.body:
        text = soup.body.get_text("\n")
    lines = [" ".join(line.split()) for line in text.splitlines()]
    return title, re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()


async def _check_public(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise ValueError("Only absolute http:// or https:// URLs are supported.")
    if parsed.username or parsed.password:
        raise ValueError("URLs containing credentials are not allowed.")
    host = parsed.hostname
    try:
        infos = await asyncio.get_running_loop().getaddrinfo(host, parsed.port or 443, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise RuntimeError(f"Could not resolve host '{host}'. Do not guess URLs: use web_search and "
                           "open a URL from its results.") from exc
    for info in infos:
        ip = ipaddress.ip_address(info[4][0].split("%")[0])
        if not ip.is_global:
            raise ValueError("Local or private network addresses are not allowed.")


async def fetch_page(url: str, max_chars: int = 6000, offset: int = 0) -> str:
    url = (url or "").strip()
    if url and "://" not in url:
        url = "https://" + url  # models often drop the scheme
    max_chars = max(500, min(int(max_chars), 20000))
    offset = max(0, int(offset))
    timeout = aiohttp.ClientTimeout(total=20, connect=8)
    async with aiohttp.ClientSession(timeout=timeout, headers={**BROWSER_HEADERS, "Accept": "text/html,text/plain,*/*;q=0.8"},
                                     trust_env=True) as session:
        current = url
        for _ in range(5):  # follow redirects manually so every hop is re-checked
            await _check_public(current)
            try:
                async with session.get(current, allow_redirects=False) as resp:
                    if resp.status in (301, 302, 303, 307, 308) and resp.headers.get("Location"):
                        current = urljoin(current, resp.headers["Location"])
                        continue
                    if resp.status >= 400:
                        raise RuntimeError(f"HTTP {resp.status} for {current}. Do not guess URLs: use web_search and "
                                           "open a URL from its results.")
                    ctype = resp.headers.get("content-type", "").lower()
                    if not any(t in ctype for t in ("text/", "html", "json", "xml")):
                        raise RuntimeError(f"Unsupported content type '{ctype or 'unknown'}' (PDFs/binaries are not supported).")
                    chunks, size = [], 0
                    async for part in resp.content.iter_chunked(65536):
                        chunks.append(part)
                        size += len(part)
                        if size >= MAX_BODY:
                            break
                    markup = b"".join(chunks).decode(resp.charset or "utf-8", errors="replace")
                    final = str(resp.url)
                break
            except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
                raise RuntimeError(f"Unable to fetch {current}: {_describe(exc)}") from exc
        else:
            raise RuntimeError("Too many redirects.")
    if "html" in ctype:
        title, text = extract_text(markup)
    else:
        title, text = "", markup.strip()
    if not text:
        raise RuntimeError("Page has no readable text (it may need JavaScript). Try another source.")
    chunk = text[offset:offset + max_chars]
    if not chunk:
        raise RuntimeError(f"offset {offset} is past the end of the page ({len(text)} chars).")
    end = offset + len(chunk)
    head = f"URL: {final}\nTitle: {title}\nShowing characters {offset}-{end} of {len(text)}\n\n"
    more = f"\n\n[More content available: call web_browse again with offset={end}]" if end < len(text) else ""
    return head + chunk + more


_URL_RE = re.compile(r"^\s*\d+\.\s.*\n\s+(https?://\S+)", re.M)


async def research(query: str, pages: int = 2, chars: int = 2500) -> str:
    """One call for small models: search, open the top pages, return their text."""
    found = await search(query, max_results=6)
    urls = _URL_RE.findall(found)
    pages = max(1, min(int(pages), 3))
    chars = max(800, min(int(chars), 6000))
    out, errors = [found.split("\n", 1)[0]], []
    for url in urls:
        if len(out) > pages:
            break
        try:
            page = await fetch_page(url, max_chars=chars)
        except Exception as exc:  # noqa: BLE001 - skip unreadable pages
            errors.append(f"{url}: {_describe(exc)[:120]}")
            continue
        out.append(f"=== SOURCE {len(out)}: {page}")
    if len(out) == 1:
        raise RuntimeError("Search worked but no result page could be read: " + " | ".join(errors[:4])
                           + "\nResults:\n" + found)
    return "\n\n".join(out)


# ---------------------------------------------------------------- CLI diagnosis
async def _diagnose_search(query: str) -> None:
    backends = _make_backends(query, 5, "wt-wt")
    timeout = aiohttp.ClientTimeout(total=10, connect=5)
    async with aiohttp.ClientSession(timeout=timeout, headers=BROWSER_HEADERS, trust_env=True) as s:
        for name, fn in backends.items():
            try:
                res = await fn(s)
                print(f"[ OK ] {name:10} {len(res)} results" + (f"  e.g. {res[0]['title'][:60]} -> {res[0]['url']}" if res else "  (empty!)"))
            except BackendUnavailable as exc:
                print(f"[skip] {name:10} {exc}")
            except Exception as exc:  # noqa: BLE001
                print(f"[FAIL] {name:10} {_describe(exc)}")


if __name__ == "__main__":
    if len(sys.argv) >= 3 and sys.argv[1] == "search":
        asyncio.run(_diagnose_search(" ".join(sys.argv[2:])))
    elif len(sys.argv) >= 3 and sys.argv[1] == "fetch":
        print(asyncio.run(fetch_page(sys.argv[2]))[:3000])
    else:
        print(__doc__)
