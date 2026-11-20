#!/usr/bin/env python3
"""Run a non-destructive backup/restore drill and record the RPO/RTO evidence.

Examples::

    python3 scripts/backup_drill.py
    python3 scripts/backup_drill.py --json
    python3 scripts/backup_drill.py --write docs/dev/runbooks/backup-restore.md
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from vira.ops.drill import render_markdown, run_drill  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--backup-dir", default=None,
                        help="Directory for the drill backup (default: data/backups).")
    parser.add_argument("--work-dir", default=None,
                        help="Temporary directory used for the restored copy.")
    parser.add_argument("--json", action="store_true", help="Print JSON only.")
    parser.add_argument("--write", default=None,
                        help="Write the Markdown drill record to this path.")
    args = parser.parse_args()

    try:
        report = run_drill(args.backup_dir, args.work_dir)
    except Exception as exc:  # noqa: BLE001 - the drill reports, never hides
        print(f"Backup drill failed: {exc}", file=sys.stderr)
        return 1

    markdown = render_markdown(report)
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print(markdown)
    if args.write:
        output = Path(args.write)
        if not output.is_absolute():
            output = ROOT / output
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(markdown + "\n", encoding="utf-8")
        print(f"Wrote {output}")
    return 0 if report.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
