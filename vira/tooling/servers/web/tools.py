"""Web, search and research tools."""
from __future__ import annotations

from pydantic import Field

from ...contract import BaseTool, StrictModel, ToolContext, ToolError
from ..common import TextOutput


class WebSearchInput(StrictModel):
    query: str = Field(min_length=1, max_length=300)
    max_results: int = Field(default=8, ge=1, le=20)
    region: str = Field(default="wt-wt", max_length=20)


class WebBrowseInput(StrictModel):
    url: str = Field(min_length=4, max_length=2048)
    max_chars: int = Field(default=6000, ge=500, le=20000)
    offset: int = Field(default=0, ge=0)


class WebResearchInput(StrictModel):
    question: str = Field(min_length=1, max_length=300)
    pages: int = Field(default=2, ge=1, le=3)


class WebSearchTool(BaseTool):
    namespace = "web"
    name = "search"
    title = "Search the web"
    description = "Search the public web and return titles, URLs and snippets."
    when_to_use = (
        "Use for current events, prices, people, news, or any fact you cannot "
        "verify from local context. Follow up with web.browse for details."
    )
    when_not_to_use = "Do not use for private VIRA data or knowledge-base documents."
    category = "web"
    tags = ("web", "search", "news", "current-events", "internet")
    side_effects = "network"
    timeout_seconds = 45
    input_model = WebSearchInput
    output_model = TextOutput

    async def run(self, params: WebSearchInput, context: ToolContext) -> TextOutput:
        try:
            from vira.tooling.services import webtools
            text = await webtools.search(
                params.query, params.max_results, params.region
            )
            return TextOutput(text=text)
        except (OSError, RuntimeError, ValueError) as exc:
            raise ToolError("web_search_failed", str(exc), retryable=True) from exc


class WebBrowseTool(BaseTool):
    namespace = "web"
    name = "browse"
    title = "Browse a web page"
    description = "Open a public URL and return readable text."
    when_to_use = (
        "Use with a full URL returned by web.search when the snippet is not enough."
    )
    when_not_to_use = "Do not guess URLs and do not use for authenticated/private pages."
    category = "web"
    tags = ("web", "browse", "url", "page", "read")
    aliases = ("open", "url", "page", "read", "link")
    side_effects = "network"
    timeout_seconds = 45
    input_model = WebBrowseInput
    output_model = TextOutput

    async def run(self, params: WebBrowseInput, context: ToolContext) -> TextOutput:
        try:
            from vira.tooling.services import webtools
            text = await webtools.fetch_page(
                params.url, params.max_chars, params.offset
            )
            return TextOutput(
                text=text,
                truncated="offset" in text.lower() and "next" in text.lower(),
            )
        except (OSError, RuntimeError, ValueError) as exc:
            raise ToolError("web_browse_failed", str(exc), retryable=True) from exc


class WebResearchTool(BaseTool):
    namespace = "web"
    name = "research"
    title = "Research a question"
    description = "Search the web, read the top pages and return sourced text."
    when_to_use = (
        "Best first tool for questions that need current facts from multiple sources."
    )
    when_not_to_use = "Do not use when one precise URL is already known; use web.browse."
    category = "web"
    tags = ("web", "research", "sources", "news", "facts")
    side_effects = "network"
    timeout_seconds = 90
    input_model = WebResearchInput
    output_model = TextOutput

    async def run(self, params: WebResearchInput, context: ToolContext) -> TextOutput:
        try:
            from vira.tooling.services import webtools
            text = await webtools.research(params.question, params.pages)
            return TextOutput(text=text)
        except (OSError, RuntimeError, ValueError) as exc:
            raise ToolError("web_research_failed", str(exc), retryable=True) from exc


TOOLS = [WebSearchTool, WebBrowseTool, WebResearchTool]
