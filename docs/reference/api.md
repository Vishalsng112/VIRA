# HTTP API reference

VIRA Server exposes a FastAPI application. The reference below is generated from
the live OpenAPI schema, so it always matches the code.

## Interactive API docs

When a server is running, the same schema is available at:

- `/docs` — Swagger UI
- `/redoc` — ReDoc
- `/openapi.json` — raw schema

## Endpoints

<swagger-ui src="openapi.json"/>

!!! note "Generated at build time"
    `openapi.json` on this page is produced by
    `python scripts/export_openapi.py` during the documentation build. It is not
    edited by hand. If the schema is missing here, the build step failed — check
    the `docs` workflow logs.
