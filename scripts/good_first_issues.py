#!/usr/bin/env python3
"""Render the curated good-first-issue backlog.

    python3 scripts/good_first_issues.py
    python3 scripts/good_first_issues.py --write docs/dev/good-first-issues.md
    python3 scripts/good_first_issues.py --gh
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKLOG = ROOT / ".github" / "good-first-issues.json"


def load() -> list:
    entries = json.loads(BACKLOG.read_text(encoding="utf-8"))
    return sorted(entries, key=lambda item: (item.get("area", ""), item.get("id", "")))


def markdown(entries: list) -> str:
    lines = [
        "# Good first issues",
        "",
        "A curated, current list for new contributors. Each task has one outcome,",
        "one or two files to touch and a runnable acceptance check. Create the",
        "GitHub issues from this list with `python3 scripts/good_first_issues.py --gh`.",
        "",
        "| ID | Task | Area | Effort | Acceptance |",
        "|---|---|---|---|---|",
    ]
    for item in entries:
        files = ", ".join(f"`{path}`" for path in item.get("files", []))
        lines.append(
            f"| `{item['id']}` | {item['title']}<br><small>{files}</small> "
            f"| {item.get('area', '')} | {item.get('difficulty', '')} "
            f"| {item.get('acceptance', '')} |"
        )
    lines += [
        "",
        "## How to claim one",
        "",
        "1. Open the matching issue and comment that you are taking it.",
        "2. Read `CONTRIBUTING.md` and the linked code.",
        "3. Make the smallest change that satisfies the acceptance check.",
        "4. Open a PR with the test output and any docs updates.",
        "",
        "Maintainers aim to give an initial response within **three business days**.",
        "If an issue is stale or no longer accurate, say so in the issue rather than",
        "working around it.",
        "",
    ]
    return "\n".join(lines)


def gh_commands(entries: list) -> str:
    commands = []
    for item in entries:
        body = (
            f"Area: {item.get('area', '')}\\n"
            f"Effort: {item.get('difficulty', '')}\\n\\n"
            f"Files: {', '.join(item.get('files', []))}\\n\\n"
            f"Acceptance: {item.get('acceptance', '')}\\n\\n"
            "Please comment before starting so the issue can be assigned."
        )
        labels = " ".join(
            f"--label {json.dumps(label)}" for label in item.get("labels", ["good first issue"])
        )
        commands.append(
            "gh issue create "
            f"--title {json.dumps(item['title'])} "
            f"--body {json.dumps(body)} "
            f"{labels}"
        )
    return "\n".join(commands)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", default=None, help="Write Markdown to this path.")
    parser.add_argument("--gh", action="store_true",
                        help="Print `gh issue create` commands instead of Markdown.")
    args = parser.parse_args()
    entries = load()
    output = gh_commands(entries) if args.gh else markdown(entries)
    if args.write:
        target = Path(args.write)
        if not target.is_absolute():
            target = ROOT / target
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(markdown(entries) + "\n", encoding="utf-8")
        print(f"Wrote {target}")
    else:
        print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
