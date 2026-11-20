"""Optional PostgreSQL backend for VIRA.

Enable with ``VIRA_DATABASE_URL=postgresql://...`` and install
``psycopg[binary]``.  The schema keeps timestamps as ISO text and adds explicit
``rowid``/``seq`` columns so the existing SQL remains portable.
"""
import re
from typing import Any, Iterable, List, Optional, Sequence


def _translate(sql: str, params: Any = None) -> str:
    sql = sql.replace("?", "%s")
    if isinstance(params, dict) and ":" in sql:
        sql = re.sub(r":([A-Za-z_][A-Za-z0-9_]*)", r"%(\1)s", sql)
    if "INSERT OR IGNORE INTO" in sql:
        sql = sql.replace("INSERT OR IGNORE INTO", "INSERT INTO")
        if "ON CONFLICT" not in sql.upper():
            sql = sql.rstrip().rstrip(";") + " ON CONFLICT DO NOTHING"
    return sql


class PostgresConnection:
    def __init__(self, raw):
        self._raw = raw

    def execute(self, sql: str, params: Optional[Sequence[Any]] = None):
        return self._raw.execute(_translate(sql, params), params or ())

    def executescript(self, script: str) -> None:
        for statement in script.split(";"):
            statement = statement.strip()
            if statement:
                self._raw.execute(statement)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        if exc_type is None:
            self.commit()
        else:
            self.rollback()
        self.close()

    def commit(self) -> None:
        self._raw.commit()

    def rollback(self) -> None:
        self._raw.rollback()

    def close(self) -> None:
        self._raw.close()


def connect(url: str):
    try:
        import psycopg
        from psycopg.rows import dict_row
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError(
            "PostgreSQL support requires psycopg: pip install 'psycopg[binary]'"
        ) from exc
    raw = psycopg.connect(url, autocommit=True, row_factory=dict_row)
    return PostgresConnection(raw)


def schema_sql() -> str:
    from pathlib import Path
    return (Path(__file__).parent / "postgres_schema.sql").read_text(encoding="utf-8")
