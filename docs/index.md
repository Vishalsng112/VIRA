# VIRA Documentation

**VIRA** is a local-first AI server and extensible agent platform for your devices,
tools and knowledge. It gives you a control center, a chat workspace, persistent
memory, permissioned tools, retrieval-augmented knowledge, durable workflows and
specialist agents that can work on real tasks.

![VIRA Server and VIRA Link](assets/VIRA_server_client.svg)

## Two pieces

| Piece | What it is | Where it runs |
|---|---|---|
| **VIRA Server** | API, dashboard, chat, agents, tools, memory, database, scheduler, admin | Docker container (Linux, macOS, Windows) |
| **VIRA Link** | Device companion: collectors, offline ledgers, sync, command polling | Native app on phones and desktops, or its web build |

The browser dashboard and chat are served by VIRA Server and need no separate
install. VIRA Link is only needed on devices whose signals you want to collect.

## Start here

<div class="grid cards" markdown>

-   **I want to run VIRA**

    ---

    Install the server in minutes, then open the dashboard.

    [:octicons-arrow-right-24: Getting started](user/getting-started.md)

-   **I want to build on VIRA**

    ---

    Architecture, plugin SDK, event schemas and design documents.

    [:octicons-arrow-right-24: Developer manual](dev/index.md)

-   **I want to look up an API**

    ---

    HTTP endpoints, event types and configuration keys.

    [:octicons-arrow-right-24: Reference](reference/api.md)

</div>

## How these docs are built

The documentation is **Docs-as-Code**: every page is Markdown in this repository,
reviewed in the same pull request as the code it describes. CI builds the HTML
site you are reading and generates the PDF manuals from the exact same sources —
there is no separately maintained copy.

- **HTML** — rebuilt on every push to `main`
- **PDF** — `VIRA User Manual` and `VIRA Developer Manual`, rebuilt on every
  release and attached to GitHub Releases
- **API reference** — generated from the FastAPI OpenAPI schema, so it cannot
  drift from the code

See [Contributing](dev/contributing.md) for how to add or change a page.
