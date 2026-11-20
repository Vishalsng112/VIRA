#!/usr/bin/env python3
"""Run the deterministic agent-platform evaluation and record comparable results.

Examples::

    python3 scripts/evaluate.py
    python3 scripts/evaluate.py --json
    python3 scripts/evaluate.py --write
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from vira.evaluation import run_all  # noqa: E402

DEFAULT_JSON = "docs/dev/evaluations/agent-platform.json"
DEFAULT_MARKDOWN = "docs/dev/evaluations/agent-platform.md"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="Print the JSON report.")
    parser.add_argument("--write", nargs="?", const="both",
                        choices=["both", "json", "markdown"],
                        help="Write results to docs/dev/evaluations/.")
    args = parser.parse_args()

    report = run_all()
    print(report.markdown() if not args.json else json.dumps(report.as_dict(), indent=2))
    if args.write:
        report.write(str(ROOT / DEFAULT_JSON), str(ROOT / DEFAULT_MARKDOWN))
        print(f"Wrote {DEFAULT_JSON} and {DEFAULT_MARKDOWN}")
    return 0 if report.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
