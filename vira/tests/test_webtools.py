import base64
import unittest
from unittest import mock

from vira.tools import webtools as w

DDG_HTML = """<div class="result results_links"><a class="result__a"
 href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fexample.org%2Fa&rut=x">Example A</a>
 <a class="result__snippet">Snippet A</a></div>
<div class="result result--ad"><a class="result__a" href="https://ad.example/">AD</a></div>
<div class="result"><a class="result__a" href="https://example.org/b">Example B</a></div>"""

DDG_LITE = """<table><tr><td><a rel="nofollow" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fexample.org%2Fa" class='result-link'>Lite A</a></td></tr>
<tr><td class='result-snippet'>Lite snippet</td></tr></table>"""

_TOKEN = "a1" + base64.urlsafe_b64encode(b"https://en.wikipedia.org/wiki/Bigg_Boss").decode().rstrip("=")
BING = f"""<ol><li class="b_algo"><h2><a href="https://www.bing.com/ck/a?!&&p=1&u={_TOKEN}&ntb=1">Bigg Boss - Wikipedia</a></h2>
<div class="b_caption"><p>Reality show.</p></div></li>
<li class="b_algo"><h2><a href="https://example.com/x">Direct</a></h2><p>Plain para</p></li></ol>"""

MOJEEK = """<ul class="results-standard"><li><h2><a class="title" href="https://example.net/m">Mojeek hit</a></h2>
<p class="s">Mojeek snippet</p></li></ul>"""

PAGE = """<html><head><title>Show</title><script>var x=1</script></head><body>
<nav>Home | About</nav><div id="mw-content-text"><h1>Contestants</h1>
<table><tr><th>Name</th><th>Age</th></tr><tr><td>Asha</td><td>25</td></tr></table>
<p>Main text.<sup class="reference">[1]</sup></p></div><footer>Copyright</footer></body></html>"""


class ParserTests(unittest.TestCase):
    def test_ddg_html_unwraps_redirects_and_skips_ads(self):
        r = w.parse_ddg_html(DDG_HTML, 5)
        self.assertEqual([x["url"] for x in r], ["https://example.org/a", "https://example.org/b"])
        self.assertEqual(r[0]["snippet"], "Snippet A")

    def test_ddg_challenge_is_reported_as_blocked(self):
        with self.assertRaises(w.Blocked):
            w.parse_ddg_html('<div class="anomaly-modal">x</div>', 5)

    def test_ddg_lite(self):
        r = w.parse_ddg_lite(DDG_LITE, 5)
        self.assertEqual((r[0]["title"], r[0]["url"], r[0]["snippet"]),
                         ("Lite A", "https://example.org/a", "Lite snippet"))

    def test_bing_unwraps_tracking_links(self):
        r = w.parse_bing(BING, 5)
        self.assertEqual(r[0]["url"], "https://en.wikipedia.org/wiki/Bigg_Boss")
        self.assertEqual(r[1]["url"], "https://example.com/x")

    def test_mojeek(self):
        self.assertEqual(w.parse_mojeek(MOJEEK, 5)[0]["url"], "https://example.net/m")

    def test_limit_and_dedupe(self):
        rows = [("t", "https://a.io/", "")] * 3 + [("u", "https://b.io/", "")]
        self.assertEqual(len(w._finish(rows, 5)), 2)


class ExtractTests(unittest.TestCase):
    def test_extract_text_tables_and_noise(self):
        title, text = w.extract_text(PAGE)
        self.assertEqual(title, "Show")
        self.assertIn("Name | Age", text)
        self.assertIn("Asha | 25", text)
        self.assertIn("Main text.", text)
        for junk in ("var x", "Home | About", "Copyright", "[1]"):
            self.assertNotIn(junk, text)


class SearchChainTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        w._state["cache"].clear()
        w.MIN_INTERVAL = 0

    async def test_falls_through_blocked_backends(self):
        async def blocked(s): raise w.Blocked("HTTP 202")
        async def unset(s): raise w.BackendUnavailable("no key")
        async def good(s): return [{"title": "T", "url": "https://x.io/", "snippet": "S"}]
        fake = {"a": blocked, "b": unset, "c": good}
        with mock.patch.object(w, "_make_backends", return_value=fake), \
                mock.patch.dict("os.environ", {"VIRA_SEARCH_BACKENDS": "a,b,c"}):
            out = await w.search("anything")
        self.assertIn("via c", out)
        self.assertIn("https://x.io/", out)

    async def test_all_fail_raises_with_reasons(self):
        async def blocked(s): raise w.Blocked("HTTP 202")
        with mock.patch.object(w, "_make_backends", return_value={"a": blocked}), \
                mock.patch.dict("os.environ", {"VIRA_SEARCH_BACKENDS": "a"}):
            with self.assertRaises(RuntimeError) as ctx:
                await w.search("anything2")
        self.assertIn("a: Blocked: HTTP 202", str(ctx.exception))


class ResearchTests(unittest.IsolatedAsyncioTestCase):
    async def test_research_opens_top_pages_and_skips_broken_ones(self):
        listing = w.format_results("q", "bing", [
            {"title": "A", "url": "https://a.io/1", "snippet": "s"},
            {"title": "B", "url": "https://b.io/2", "snippet": ""},
            {"title": "C", "url": "https://c.io/3", "snippet": "s"}])
        self.assertEqual(w._URL_RE.findall(listing), ["https://a.io/1", "https://b.io/2", "https://c.io/3"])

        async def fake_fetch(url, max_chars=0, offset=0):
            if "a.io" in url:
                raise RuntimeError("HTTP 404")
            return f"URL: {url}\ntext"
        with mock.patch.object(w, "search", mock.AsyncMock(return_value=listing)), \
                mock.patch.object(w, "fetch_page", fake_fetch):
            out = await w.research("q", pages=2)
        self.assertIn("SOURCE 1: URL: https://b.io/2", out)
        self.assertIn("SOURCE 2: URL: https://c.io/3", out)
        self.assertNotIn("a.io", out.split("SOURCE", 1)[1])

    async def test_research_reports_when_nothing_readable(self):
        listing = w.format_results("q", "bing", [{"title": "A", "url": "https://a.io/1", "snippet": ""}])
        async def boom(*a, **k): raise RuntimeError("HTTP 403")
        with mock.patch.object(w, "search", mock.AsyncMock(return_value=listing)), mock.patch.object(w, "fetch_page", boom):
            with self.assertRaises(RuntimeError) as ctx:
                await w.research("q")
        self.assertIn("no result page could be read", str(ctx.exception))


class SafetyTests(unittest.IsolatedAsyncioTestCase):
    async def test_private_and_odd_urls_are_rejected(self):
        for url in ("http://127.0.0.1/", "http://10.1.2.3/x", "http://192.168.0.1/", "ftp://example.org/",
                    "https://user:pw@example.org/", "file:///etc/passwd"):
            with self.assertRaises(ValueError, msg=url):
                await w._check_public(url)


if __name__ == "__main__":
    unittest.main()
