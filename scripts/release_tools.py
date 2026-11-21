#!/usr/bin/env python3
"""Release helpers for VIRA Server and VIRA Link.

Usage:
    python3 scripts/release_tools.py check v0.5.0
    python3 scripts/release_tools.py notes vira-link-v1.2.0 --dist dist
    python3 scripts/release_tools.py assets vira-link-v1.2.0 --dist dist --write-checksums
    python3 scripts/release_tools.py manifest v0.5.0 --dist dist
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List, Optional, Sequence

ROOT = Path(__file__).resolve().parents[1]
CHANGELOG = ROOT / "CHANGELOG.md"
CLIENT_PUBSPEC = ROOT / "client" / "pubspec.yaml"

SERVER = "server"
CLIENT = "client"

_SERVER_TAG = re.compile(
    r"^v(?P<version>\d+\.\d+\.\d+(?:-(?:alpha|beta|rc)\.\d+)?)$")
_CLIENT_TAG = re.compile(
    r"^vira-link-v(?P<version>\d+\.\d+\.\d+(?:-(?:alpha|beta|rc)\.\d+)?)$")
_CLIENT_PUBSPEC_VERSION = re.compile(r"^version:\s*([0-9]+\.[0-9]+\.[0-9]+)", re.M)


@dataclass(frozen=True)
class Release:
    product: str
    tag: str
    version: str
    prerelease: bool

    @property
    def title(self) -> str:
        label = "VIRA Server" if self.product == SERVER else "VIRA Link"
        return f"{label} {self.version}"

    @property
    def asset_prefix(self) -> str:
        return (f"vira-{self.version}" if self.product == SERVER
                else f"vira-link-{self.version}")


def parse_tag(tag: str, product: str = "auto") -> Release:
    tag = tag.strip()
    for candidate, kind in ((_SERVER_TAG, SERVER), (_CLIENT_TAG, CLIENT)):
        match = candidate.match(tag)
        if not match:
            continue
        if product not in ("auto", kind):
            continue
        version = match.group("version")
        return Release(kind, tag, version, "-" in version)
    expected = "vX.Y.Z or vira-link-vX.Y.Z"
    raise ValueError(f"invalid release tag {tag!r}; expected {expected}")


def version_from_tag(tag: str) -> str:
    return parse_tag(tag).version


def _changelog_section(version: str) -> str:
    text = CHANGELOG.read_text(encoding="utf-8")
    pattern = re.compile(
        rf"^## \[{re.escape(version)}\][^\n]*\n(.*?)(?=^## \[|\Z)",
        re.MULTILINE | re.DOTALL,
    )
    match = pattern.search(text)
    return match.group(1).strip() if match else ""


def _client_version() -> str:
    match = _CLIENT_PUBSPEC_VERSION.search(
        CLIENT_PUBSPEC.read_text(encoding="utf-8"))
    return match.group(1) if match else ""


def _server_version() -> str:
    sys.path.insert(0, str(ROOT))
    try:
        from vira import __version__
        return __version__
    finally:
        try:
            sys.path.remove(str(ROOT))
        except ValueError:
            pass


def check(tag: str, product: str = "auto",
          github_output: Optional[str] = None) -> int:
    release = parse_tag(tag, product)
    failures: List[str] = []
    if release.product == SERVER:
        expected = _server_version()
        if release.version != expected:
            failures.append(
                f"tag version {release.version!r} does not match "
                f"vira.__version__ {expected!r}")
        if not _changelog_section(release.version):
            failures.append(
                f"CHANGELOG.md has no '## [{release.version}]' section")
        if "Unreleased" not in CHANGELOG.read_text(encoding="utf-8"):
            failures.append("CHANGELOG.md is missing an Unreleased section")
    else:
        expected = _client_version()
        if release.version != expected:
            failures.append(
                f"tag version {release.version!r} does not match "
                f"client/pubspec.yaml version {expected!r}")

    if failures:
        for failure in failures:
            print(f"release check: {failure}", file=sys.stderr)
        return 1

    if github_output:
        with open(github_output, "a", encoding="utf-8") as handle:
            handle.write(f"product={release.product}\n")
            handle.write(f"tag={release.tag}\n")
            handle.write(f"version={release.version}\n")
            handle.write(f"title={release.title}\n")
            handle.write(f"prerelease={'true' if release.prerelease else 'false'}\n")

    print(f"release check: {release.title} is ready")
    return 0


def _bullets(section: str, limit: int = 5) -> List[str]:
    result: List[str] = []
    current: Optional[str] = None
    for line in section.splitlines():
        if line.startswith("- "):
            if current:
                result.append(" ".join(current.split()))
                if len(result) >= limit:
                    return result
            current = line[2:].strip()
        elif current and line.startswith(("  ", "\t")) and line.strip():
            current += " " + line.strip()
        elif current:
            result.append(" ".join(current.split()))
            current = None
            if len(result) >= limit:
                return result
    if current and len(result) < limit:
        result.append(" ".join(current.split()))
    return result


def _expected_assets(release: Release) -> List[str]:
    version = release.version
    if release.product == SERVER:
        return [f"vira-{version}-source.tar.gz",
                f"vira-{version}-checksums.txt"]
    return [
        f"vira-link-{version}-android.apk",
        f"vira-link-{version}-ios-unsigned.zip",
        f"vira-link-{version}-web.zip",
        f"vira-link-{version}-linux-x86_64.AppImage",
        f"vira-link-{version}-windows-x64.zip",
        f"vira-link-{version}-macos-arm64.zip",
        f"vira-link-{version}-checksums.txt",
    ]


def _asset_label(name: str) -> str:
    if name.endswith("-android.apk"):
        return "Android APK"
    if name.endswith("-ios-unsigned.zip"):
        return "iOS (unsigned zip)"
    if name.endswith("-web.zip"):
        return "Web / PWA"
    if name.endswith("-linux-x86_64.AppImage"):
        return "Linux x86_64 AppImage"
    if name.endswith("-windows-x64.zip"):
        return "Windows x64"
    if name.endswith("-macos-arm64.zip"):
        return "macOS arm64"
    if name.endswith("-source.tar.gz"):
        return "Source archive"
    if name.endswith("-checksums.txt"):
        return "SHA-256 checksums"
    return name


def _existing_assets(release: Release, dist: Optional[str]) -> List[str]:
    if not dist:
        return _expected_assets(release)
    root = Path(dist)
    if not root.exists():
        return []
    return sorted(path.name for path in root.iterdir()
                  if path.is_file() and path.name.startswith(
                      release.asset_prefix))


def _downloads_table(release: Release, assets: Sequence[str]) -> List[str]:
    lines = ["| Artifact | File |", "|---|---|"]
    for name in assets:
        lines.append(f"| {_asset_label(name)} | `{name}` |")
    return lines


def _install_notes(release: Release) -> List[str]:
    if release.product == SERVER:
        return [
            "### Upgrade",
            "",
            "1. Back up `data/.vira_master_key` and the database before upgrading.",
            "2. Pull the new source archive or Docker image.",
            "3. Run `python -m vira doctor` and complete any requested fixes.",
            "",
            "Docker users can rebuild with `docker compose up -d --build`.",
        ]
    return [
        "### Install",
        "",
        "Download the artifact for your platform. Android uses the APK; iOS is",
        "unsigned and must be signed in Xcode; Linux uses the AppImage; Windows",
        "and macOS use the ZIP archives; web can be served over HTTPS.",
        "",
        "Remove the previous build before installing the new one. Device",
        "credentials can be revoked from **Settings → Device lifecycle**.",
    ]


def notes(tag: str, product: str = "auto", dist: Optional[str] = None) -> int:
    release = parse_tag(tag, product)
    section = _changelog_section(release.version)
    highlights = _bullets(section, 5)
    if not highlights:
        highlights = [
            "See the changelog for the complete list of changes."]
    assets = _existing_assets(release, dist)
    checksums = f"{release.asset_prefix}-checksums.txt"

    lines = [f"## {release.title}", ""]
    if release.product == SERVER:
        lines.append("Self-hosted, local-first context and tool server for AI agents.")
    else:
        lines.append("Cross-platform companion for device signals, focus and agent notifications.")
    lines += ["", "### Highlights", ""]
    lines += [f"- {item}" for item in highlights]
    lines += [""] + _install_notes(release) + [""]
    lines += ["### Downloads", ""] + _downloads_table(release, assets) + [""]
    lines += ["### Verify", "", "```bash", f"sha256sum -c {checksums}", "```", ""]
    if section:
        changelog = "\n".join(
            f"#### {line[4:]}" if line.startswith("### ") else line
            for line in section.splitlines()
        )
        lines += ["### Changelog", "", changelog, ""]
    lines += [
        "**Full changelog:** "
        "https://github.com/Vishalsng112/VIRA/blob/main/CHANGELOG.md",
    ]
    text = "\n".join(lines)
    text = re.sub(r"\n{3,}", "\n\n", text).strip() + "\n"
    print(text, end="")
    return 0


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_checksums(release: Release, root: Path) -> None:
    files = sorted(
        path for path in root.iterdir()
        if path.is_file() and path.name != f"{release.asset_prefix}-checksums.txt"
        and path.name.startswith(release.asset_prefix)
    )
    lines = [f"{_sha256(path)}  {path.name}" for path in files]
    (root / f"{release.asset_prefix}-checksums.txt").write_text(
        "\n".join(lines) + "\n", encoding="utf-8")


def assets(tag: str, product: str = "auto", dist: str = "dist",
           write_checksums: bool = False) -> int:
    release = parse_tag(tag, product)
    root = Path(dist)
    if not root.exists():
        print(f"release assets: missing directory {root}", file=sys.stderr)
        return 1
    if write_checksums:
        _write_checksums(release, root)
    expected = _expected_assets(release)
    missing = [name for name in expected if not (root / name).is_file()]
    if missing:
        for name in missing:
            print(f"release assets: missing {name}", file=sys.stderr)
        return 1
    print(f"release assets: {len(expected)} files verified in {root}")
    return 0


def manifest(tag: str, product: str = "auto", dist: str = "dist") -> int:
    release = parse_tag(tag, product)
    root = Path(dist)
    files = []
    if root.exists():
        for path in sorted(root.iterdir()):
            if path.is_file() and path.name.startswith(release.asset_prefix):
                files.append({
                    "name": path.name,
                    "size": path.stat().st_size,
                    "sha256": _sha256(path),
                })
    print(json.dumps({
        "product": release.product,
        "tag": release.tag,
        "version": release.version,
        "title": release.title,
        "prerelease": release.prerelease,
        "assets": files,
    }, indent=2))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    check_parser = sub.add_parser("check")
    check_parser.add_argument("tag")
    check_parser.add_argument("--product", choices=[SERVER, CLIENT, "auto"],
                              default="auto")
    check_parser.add_argument("--github-output")

    notes_parser = sub.add_parser("notes")
    notes_parser.add_argument("tag")
    notes_parser.add_argument("--product", choices=[SERVER, CLIENT, "auto"],
                              default="auto")
    notes_parser.add_argument("--dist")

    assets_parser = sub.add_parser("assets")
    assets_parser.add_argument("tag")
    assets_parser.add_argument("--product", choices=[SERVER, CLIENT, "auto"],
                               default="auto")
    assets_parser.add_argument("--dist", default="dist")
    assets_parser.add_argument("--write-checksums", action="store_true")

    manifest_parser = sub.add_parser("manifest")
    manifest_parser.add_argument("tag")
    manifest_parser.add_argument("--product", choices=[SERVER, CLIENT, "auto"],
                                 default="auto")
    manifest_parser.add_argument("--dist", default="dist")

    args = parser.parse_args()
    if args.command == "check":
        return check(args.tag, args.product, args.github_output)
    if args.command == "notes":
        return notes(args.tag, args.product, args.dist)
    if args.command == "assets":
        return assets(args.tag, args.product, args.dist, args.write_checksums)
    return manifest(args.tag, args.product, args.dist)


if __name__ == "__main__":
    raise SystemExit(main())
