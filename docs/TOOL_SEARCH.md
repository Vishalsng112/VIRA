# Tool Search and Prompt Budgeting

VIRA must not put every tool into every prompt. The current implementation:

1. builds a `ToolCatalog` from tool name, description, schema, category and tags;
2. ranks tools for the user's message;
3. gives the model a small relevant set plus `tool_search`;
4. expands the model's tool set only when it calls `tool_search`;
5. rebuilds the prompt with the expanded set on the next step.

Examples:

- `photoshop` → tools tagged `adobe`/`photoshop`
- `davinci resolve` → tools tagged `davinci-resolve`/`media`
- `device usage focus` → `insights`
- `web news` → web search/research/browse tools

The MCP server also exposes `search_tools` with its own catalogue so standalone
MCP clients can avoid loading every tool.

## Current scoring

- phrase in tool name
- exact tag/token matches
- name token matches
- description token matches
- category match
- fallback to core web/workspace/runtime/insights tools

## Future algorithm

Replace the keyword ranker with a two-stage retriever:

1. **Candidate retrieval**
   - embeddings over tool name + description + app/domain tags
   - hierarchical namespaces (`adobe/photoshop`, `blackmagic/davinci`, `web`)
   - synonym and app-alias expansion
2. **Re-ranking**
   - usage feedback (which tools succeeded for similar tasks)
   - tool cost/latency estimate
   - required-argument similarity
   - user/agent permission filter
   - category diversity
3. **Prompt budgeter**
   - hard cap on tool count and rendered description chars
   - collapse tools into compact one-line specs
   - keep a `tool_search` / `tool_describe` meta-tool
   - only include full schemas for the final shortlist
4. **Learning loop**
   - store (query, selected tools, tool call outcome)
   - periodically rebuild app/domain bundles
   - evaluate retrieval recall on a golden task set

The interfaces are already separated (`ToolCatalog.search/select`, AgentLoop
dynamic expansion), so a vector or hybrid retriever can replace the scorer
without changing agents or the MCP wire contract.
