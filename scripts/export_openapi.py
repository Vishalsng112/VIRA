#!/usr/bin/env python3
"""Export the VIRA FastAPI OpenAPI schema for the documentation site.

The docs page ``docs/reference/api.md`` renders this file with Swagger UI, so the
published reference cannot drift from the routes in ``vira/api``.

Usage:
    python scripts/export_openapi.py [output_path]

The default output is ``docs/reference/openapi.json``. The file is generated and
git-ignored; CI regenerates it on every documentation build.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT / "docs" / "reference" / "openapi.json"


def main() -> int:
    output = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_OUTPUT

    # Import the app without booting the kernel. Routers are registered during
    # create_app(), so the schema is complete without starting any services.
    sys.path.insert(0, str(ROOT))
    os.environ.setdefault("VIRA_CONFIG", str(ROOT / "config.yaml"))

    from vira.api.app import create_app  # noqa: PLC0415
    from vira.kernel import Kernel  # noqa: PLC0415

    app = create_app(Kernel(config_path=os.environ["VIRA_CONFIG"]))
    schema = app.openapi()

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(schema, indent=2) + "\n", encoding="utf-8")

    paths = len(schema.get("paths", {}))
    print(f"Wrote {paths} API paths to {output.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
