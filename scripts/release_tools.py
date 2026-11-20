#!/usr/bin/env python3
"""Release helpers: validate the changelog/version and extract release notes.

    python3 scripts/release_tools.py check v0.4.0
    python3 scripts/release_tools.py notes v0.4.0 > release-notes.md
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CHANGELOG = ROOT / "CHANGELOG.md"


def version_from_tag(tag: str) -> str:
    return tag.strip().lstrip("v")


def _section(version: str) -> str:
    text = CHANGELOG.read_text(encoding="utf-8")
    pattern = re.compile(
        rf"^## \[{re.escape(version)}\][^\n]*\n(.*?)(?=^## \[|\Z)",
        re.MULTILINE | re.DOTALL,
    )
    match = pattern.search(text)
    return match.group(1).strip() if match else ""


def check(tag: str) -> int:
    version = version_from_tag(tag)
    sys.path.insert(0, str(ROOT))
    from vira import __version__

    failures = []
    if version != __version__:
        failures.append(
            f"tag version {version!r} does not match vira.__version__ {__version__!r}"
        )
    if not _section(version):
        failures.append(f"CHANGELOG.md has no '## [{version}]' section")
    if "Unreleased" not in CHANGELOG.read_text(encoding="utf-8"):
        failures.append("CHANGELOG.md is missing an Unreleased section")
    if failures:
        for failure in failures:
            print(f"release check: {failure}", file=sys.stderr)
        return 1
    print(f"release check: {version} is ready")
    return 0


def notes(tag: str) -> int:
    section = _section(version_from_tag(tag))
    if not section:
        print("release notes not found", file=sys.stderr)
        return 1
    print(section)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    check_parser = sub.add_parser("check")
    check_parser.add_argument("tag")
    notes_parser = sub.add_parser("notes")
    notes_parser.add_argument("tag")
    args = parser.parse_args()
    return check(args.tag) if args.command == "check" else notes(args.tag)


if __name__ == "__main__":
    raise SystemExit(main())
