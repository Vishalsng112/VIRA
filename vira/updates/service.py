"""Release channel metadata and update checks (server and client)."""
import re
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from vira import errors
from vira.auth import database

PRODUCTS = ("server", "client")
CHANNELS = ("stable", "beta", "dev")
_VERSION = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)(?:-([0-9A-Za-z.-]+))?(?:\+[0-9A-Za-z.-]+)?$")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def parse_version(value: str):
    match = _VERSION.match((value or "").strip())
    if not match:
        raise errors.ValidationFailed(f"invalid semantic version: {value!r}")
    major, minor, patch = (int(match.group(i)) for i in (1, 2, 3))
    prerelease = match.group(4)
    return major, minor, patch, prerelease


def compare(left: str, right: str) -> int:
    """-1 if left < right, 0 equal, 1 greater (semver ordering)."""
    lmaj, lmin, lpatch, lpre = parse_version(left)
    rmaj, rmin, rpatch, rpre = parse_version(right)
    if (lmaj, lmin, lpatch) != (rmaj, rmin, rpatch):
        return -1 if (lmaj, lmin, lpatch) < (rmaj, rmin, rpatch) else 1
    if lpre is None and rpre is None:
        return 0
    if lpre is None:
        return 1
    if rpre is None:
        return -1
    lparts = lpre.split(".")
    rparts = rpre.split(".")
    for a, b in zip(lparts, rparts):
        if a == b:
            continue
        if a.isdigit() and b.isdigit():
            return -1 if int(a) < int(b) else 1
        if a.isdigit():
            return -1
        if b.isdigit():
            return 1
        return -1 if a < b else 1
    if len(lparts) == len(rparts):
        return 0
    return -1 if len(lparts) < len(rparts) else 1


def publish(product: str, channel: str, version: str, notes: str = "",
            url: str = "", checksum: Optional[str] = None,
            min_version: Optional[str] = None, user_id: Optional[int] = None) -> Dict[str, Any]:
    if product not in PRODUCTS:
        raise errors.ValidationFailed("product must be server or client")
    if channel not in CHANNELS:
        raise errors.ValidationFailed("channel must be stable, beta or dev")
    parse_version(version)
    if min_version:
        parse_version(min_version)
    now = _now()
    release_id = str(uuid.uuid4())
    with database.transaction() as conn:
        existing = conn.execute(
            "SELECT id, published_at FROM update_releases WHERE product = ? AND channel = ? AND version = ?",
            (product, channel, version),
        ).fetchone()
        if existing:
            release_id = existing["id"]
            conn.execute(
                "UPDATE update_releases SET notes = ?, url = ?, checksum = ?, min_version = ?, "
                "published_at = ?, created_by_user_id = ? WHERE id = ?",
                (notes, url, checksum, min_version, now, user_id, release_id),
            )
        else:
            conn.execute(
                "INSERT INTO update_releases (id, product, channel, version, min_version, notes, "
                "url, checksum, published_at, created_by_user_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (release_id, product, channel, version, min_version, notes, url,
                 checksum, now, user_id),
            )
    return get_release(release_id)


def get_release(release_id: str) -> Optional[Dict[str, Any]]:
    with database.get_connection() as conn:
        row = conn.execute("SELECT * FROM update_releases WHERE id = ?", (release_id,)).fetchone()
    return dict(row) if row else None


def list_releases(product: Optional[str] = None, channel: Optional[str] = None,
                  limit: int = 100) -> List[Dict[str, Any]]:
    clauses, values = [], []
    if product:
        clauses.append("product = ?")
        values.append(product)
    if channel:
        clauses.append("channel = ?")
        values.append(channel)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    values.append(min(max(limit, 1), 500))
    with database.get_connection() as conn:
        rows = conn.execute(
            f"SELECT * FROM update_releases {where} ORDER BY published_at DESC LIMIT ?",
            values,
        ).fetchall()
    return [dict(row) for row in rows]


def latest(product: str, channel: str = "stable") -> Optional[Dict[str, Any]]:
    releases = list_releases(product, channel, 100)
    best = None
    for release in releases:
        if best is None or compare(release["version"], best["version"]) > 0:
            best = release
    return best


def check(product: str, channel: str, current_version: str) -> Dict[str, Any]:
    if product not in PRODUCTS:
        raise errors.ValidationFailed("product must be server or client")
    if channel not in CHANNELS:
        raise errors.ValidationFailed("channel must be stable, beta or dev")
    parse_version(current_version)
    release = latest(product, channel)
    if release is None:
        return {"update_available": False, "current_version": current_version,
                "channel": channel, "latest": None}
    available = compare(release["version"], current_version) > 0
    if available and release.get("min_version"):
        try:
            available = compare(current_version, release["min_version"]) >= 0
        except errors.ViraError:
            available = False
    return {
        "update_available": available,
        "current_version": current_version,
        "channel": channel,
        "latest": release if available else None,
        "minimum_version": release.get("min_version"),
    }


def delete(release_id: str) -> bool:
    with database.transaction() as conn:
        cur = conn.execute("DELETE FROM update_releases WHERE id = ?", (release_id,))
        return bool(cur.rowcount)
