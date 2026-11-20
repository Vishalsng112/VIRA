"""Consistent database backup and restore helpers (SQLite baseline)."""
import argparse
import shutil
import sqlite3
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

from vira.auth import database

DEFAULT_BACKUP_DIR = Path("data/backups")


def _stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")


def create_backup(directory: Optional[str] = None, keep: int = 7) -> Path:
    directory = Path(directory or DEFAULT_BACKUP_DIR)
    directory.mkdir(parents=True, exist_ok=True)
    if database.is_postgres():
        destination = directory / f"vira-{_stamp()}.sql"
        subprocess.run(
            ["pg_dump", database.DATABASE_URL, "-f", str(destination)],
            check=True,
        )
        _prune(directory, keep)
        return destination
    destination = directory / f"vira-{_stamp()}.sqlite3"
    source = sqlite3.connect(str(database.DB_PATH))
    try:
        target = sqlite3.connect(str(destination))
        try:
            source.backup(target)
        finally:
            target.close()
    finally:
        source.close()
    _prune(directory, keep)
    return destination


def _prune(directory: Path, keep: int) -> None:
    files = sorted(list(directory.glob("vira-*.sqlite3")) + list(directory.glob("vira-*.sql")), reverse=True)
    for old in files[max(1, keep):]:
        try:
            old.unlink()
        except OSError:
            pass


def list_backups(directory: Optional[str] = None) -> List[Path]:
    directory = Path(directory or DEFAULT_BACKUP_DIR)
    return sorted(list(directory.glob("vira-*.sqlite3")) + list(directory.glob("vira-*.sql")), reverse=True)


def restore_backup(path: str) -> Path:
    """Restore a backup. Stop the API/worker first; keeps a safety copy."""
    source = Path(path)
    if not source.exists():
        raise FileNotFoundError(source)
    if database.is_postgres() and source.suffix == ".sql":
        subprocess.run(["psql", database.DATABASE_URL, "-f", str(source)], check=True)
        return source
    safety = Path(str(database.DB_PATH) + f".pre-restore-{_stamp()}")
    if database.DB_PATH.exists():
        shutil.copy2(database.DB_PATH, safety)
    shutil.copy2(source, database.DB_PATH)
    return safety


def main() -> None:
    parser = argparse.ArgumentParser(prog="vira-backup")
    sub = parser.add_subparsers(dest="cmd", required=True)
    create = sub.add_parser("create")
    create.add_argument("--dir", default=None)
    create.add_argument("--keep", type=int, default=7)
    listing = sub.add_parser("list")
    listing.add_argument("--dir", default=None)
    restore = sub.add_parser("restore")
    restore.add_argument("path")
    args = parser.parse_args()
    if args.cmd == "create":
        print(create_backup(args.dir, args.keep))
    elif args.cmd == "list":
        for item in list_backups(args.dir):
            print(item)
    else:
        print(f"safety copy: {restore_backup(args.path)}")


if __name__ == "__main__":
    main()
