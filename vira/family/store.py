"""Small, SQLite-backed store for the Flutter family client contract."""
import json
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List

from vira.auth import database


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def ensure_schema() -> None:
    with database.get_connection() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS households (
                id TEXT PRIMARY KEY, name TEXT NOT NULL, created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS household_members (
                household_id TEXT NOT NULL REFERENCES households(id) ON DELETE CASCADE,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                role TEXT NOT NULL CHECK(role IN ('admin','adult','child','guest')),
                created_at TEXT NOT NULL,
                PRIMARY KEY(household_id, user_id)
            );
            CREATE TABLE IF NOT EXISTS notebooks (
                id TEXT PRIMARY KEY, household_id TEXT NOT NULL REFERENCES households(id),
                owner_user_id INTEGER NOT NULL REFERENCES users(id), title TEXT NOT NULL,
                visibility TEXT NOT NULL DEFAULT 'household',
                version INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL, deleted_at TEXT
            );
            CREATE TABLE IF NOT EXISTS family_notes (
                id TEXT PRIMARY KEY, household_id TEXT NOT NULL REFERENCES households(id),
                notebook_id TEXT NOT NULL REFERENCES notebooks(id),
                author_user_id INTEGER NOT NULL REFERENCES users(id),
                kind TEXT NOT NULL DEFAULT 'note',
                title TEXT NOT NULL, body_md TEXT NOT NULL DEFAULT '',
                pinned INTEGER NOT NULL DEFAULT 0, version INTEGER NOT NULL DEFAULT 1,
                updated_at TEXT NOT NULL, updated_by INTEGER NOT NULL,
                deleted_at TEXT
            );
            CREATE TABLE IF NOT EXISTS checklist_items (
                id TEXT PRIMARY KEY, household_id TEXT NOT NULL REFERENCES households(id),
                note_id TEXT NOT NULL REFERENCES family_notes(id), text TEXT NOT NULL,
                done INTEGER NOT NULL DEFAULT 0, position TEXT NOT NULL DEFAULT 'a0',
                assignee_user_id INTEGER, version INTEGER NOT NULL DEFAULT 1,
                updated_at TEXT NOT NULL, updated_by INTEGER NOT NULL, deleted_at TEXT
            );
            CREATE TABLE IF NOT EXISTS reminders (
                id TEXT PRIMARY KEY, household_id TEXT NOT NULL REFERENCES households(id),
                created_by_user_id INTEGER NOT NULL, assignee_user_id INTEGER,
                title TEXT NOT NULL, body TEXT NOT NULL DEFAULT '', due_at TEXT NOT NULL,
                timezone TEXT NOT NULL DEFAULT 'UTC', rrule TEXT, urgent INTEGER NOT NULL DEFAULT 0,
                note_id TEXT, item_id TEXT, status TEXT NOT NULL DEFAULT 'active',
                version INTEGER NOT NULL DEFAULT 1, updated_at TEXT NOT NULL,
                updated_by INTEGER NOT NULL, deleted_at TEXT
            );
            CREATE TABLE IF NOT EXISTS sync_op_receipts (
                household_id TEXT NOT NULL, user_id INTEGER NOT NULL, op_id TEXT NOT NULL,
                status TEXT NOT NULL, version INTEGER, result_json TEXT NOT NULL,
                created_at TEXT NOT NULL, PRIMARY KEY (household_id, user_id, op_id)
            );
            CREATE TABLE IF NOT EXISTS family_changes (
                seq INTEGER PRIMARY KEY AUTOINCREMENT, household_id TEXT NOT NULL,
                entity_type TEXT NOT NULL, entity_id TEXT NOT NULL, op TEXT NOT NULL,
                version INTEGER NOT NULL, data TEXT, changed_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS family_changes_household_seq
                ON family_changes(household_id, seq);
            """
        )
        columns = {row["name"] for row in conn.execute("PRAGMA table_info(family_notes)")}
        for name, ddl in (
            ("notebook_id", "TEXT"),
            ("author_user_id", "INTEGER"),
            ("kind", "TEXT NOT NULL DEFAULT 'note'"),
        ):
            if name not in columns:
                conn.execute(f"ALTER TABLE family_notes ADD COLUMN {name} {ddl}")
        legacy = conn.execute(
            "SELECT id, household_id FROM family_notes WHERE notebook_id IS NULL"
        ).fetchall()
        for row in legacy:
            notebook = conn.execute(
                "SELECT id FROM notebooks WHERE household_id=? LIMIT 1",
                (row["household_id"],),
            ).fetchone()
            if not notebook:
                owner = conn.execute(
                    "SELECT user_id FROM household_members WHERE household_id=? LIMIT 1",
                    (row["household_id"],),
                ).fetchone()
                if owner:
                    notebook_id = str(uuid.uuid4())
                    now = _now()
                    conn.execute(
                        "INSERT INTO notebooks VALUES (?, ?, ?, ?, 'household', 1, ?, ?, NULL)",
                        (notebook_id, row["household_id"], owner["user_id"], "Family", now, now),
                    )
                    notebook = {"id": notebook_id}
            if notebook:
                conn.execute(
                    "UPDATE family_notes SET notebook_id=?, author_user_id=COALESCE(author_user_id, updated_by) WHERE id=?",
                    (notebook["id"], row["id"]),
                )


def ensure_household(user_id: int, name: str = "My VIRA family") -> Dict[str, Any]:
    with database.transaction() as conn:
        row = conn.execute(
            """SELECT h.id, h.name, m.role FROM households h
               JOIN household_members m ON m.household_id=h.id
               WHERE m.user_id=? ORDER BY h.created_at LIMIT 1""", (user_id,)
        ).fetchone()
        if row:
            return {"id": row["id"], "name": row["name"], "my_role": row["role"]}
        household_id = str(uuid.uuid4())
        now = _now()
        conn.execute("INSERT INTO households VALUES (?, ?, ?)", (household_id, name, now))
        conn.execute("INSERT INTO household_members VALUES (?, ?, ?, ?)",
                     (household_id, user_id, "admin", now))
        conn.execute(
            "INSERT INTO notebooks VALUES (?, ?, ?, ?, 'household', 1, ?, ?, NULL)",
            (str(uuid.uuid4()), household_id, user_id, "Family", now, now),
        )
        return {"id": household_id, "name": name, "my_role": "admin"}


def list_households(user_id: int) -> List[Dict[str, Any]]:
    ensure_household(user_id)
    with database.get_connection() as conn:
        rows = conn.execute(
            """SELECT h.id, h.name, m.role AS my_role,
                      (SELECT COUNT(*) FROM household_members x WHERE x.household_id=h.id) member_count
               FROM households h JOIN household_members m ON m.household_id=h.id
               WHERE m.user_id=? ORDER BY h.created_at""", (user_id,)
        ).fetchall()
        return [dict(row) for row in rows]


def _member(conn, household_id: str, user_id: int) -> bool:
    return conn.execute(
        "SELECT 1 FROM household_members WHERE household_id=? AND user_id=? AND role IS NOT NULL",
        (household_id, user_id)).fetchone() is not None


def add_member(actor_id: int, household_id: str, user_id: int, role: str = "adult") -> None:
    if role not in {"admin", "adult", "child", "guest"}:
        raise ValueError("Invalid household role")
    with database.transaction() as conn:
        actor = conn.execute(
            "SELECT role FROM household_members WHERE household_id=? AND user_id=?",
            (household_id, actor_id)).fetchone()
        if not actor or actor["role"] != "admin":
            raise PermissionError("Household administrator required")
        conn.execute(
            """INSERT INTO household_members(household_id,user_id,role,created_at)
               VALUES(?,?,?,?) ON CONFLICT(household_id,user_id)
               DO UPDATE SET role=excluded.role""",
            (household_id, user_id, role, _now()),
        )


def members(user_id: int, household_id: str) -> List[Dict[str, Any]]:
    with database.get_connection() as conn:
        if not _member(conn, household_id, user_id):
            raise PermissionError("Household membership required")
        rows = conn.execute(
            """SELECT u.public_id, u.username, m.role, m.created_at
               FROM household_members m JOIN users u ON u.id=m.user_id
               WHERE m.household_id=? ORDER BY m.created_at""", (household_id,)
        ).fetchall()
        return [dict(row) for row in rows]


def update_member(actor_id: int, household_id: str, member_public_id: str, role: str) -> None:
    if role not in {"admin", "adult", "child", "guest"}:
        raise ValueError("Invalid household role")
    with database.transaction() as conn:
        actor = conn.execute(
            "SELECT role FROM household_members WHERE household_id=? AND user_id=?",
            (household_id, actor_id),
        ).fetchone()
        member = conn.execute(
            """SELECT u.id FROM users u JOIN household_members m ON m.user_id=u.id
               WHERE m.household_id=? AND u.public_id=?""",
            (household_id, member_public_id),
        ).fetchone()
        if not actor or actor["role"] != "admin":
            raise PermissionError("Household administrator required")
        if not member:
            raise ValueError("Household member not found")
        if member["id"] == actor_id and role != "admin":
            raise ValueError("Household must retain an administrator")
        conn.execute(
            "UPDATE household_members SET role=? WHERE household_id=? AND user_id=?",
            (role, household_id, member["id"]),
        )


def notebooks(user_id: int, household_id: str) -> List[Dict[str, Any]]:
    with database.get_connection() as conn:
        if not _member(conn, household_id, user_id):
            raise PermissionError("Household membership required")
        rows = conn.execute(
            """SELECT id, title, owner_user_id, visibility, version, created_at, updated_at
               FROM notebooks WHERE household_id=? AND deleted_at IS NULL
               ORDER BY created_at""",
            (household_id,),
        ).fetchall()
        return [dict(row) for row in rows]


def push(user_id: int, household_id: str, ops: List[Dict[str, Any]]) -> Dict[str, Any]:
    with database.transaction() as conn:
        if not _member(conn, household_id, user_id):
            raise PermissionError("Household membership required")
        results = []
        for item in ops[:200]:
            op_id = str(item.get("op_id") or uuid.uuid4())
            receipt = conn.execute(
                "SELECT result_json FROM sync_op_receipts WHERE household_id=? AND user_id=? AND op_id=?",
                (household_id, user_id, op_id),
            ).fetchone()
            if receipt:
                results.append({**json.loads(receipt["result_json"]), "status": "duplicate"})
                continue
            entity_id = str(item.get("entity_id") or item.get("data", {}).get("id") or uuid.uuid4())
            payload = dict(item.get("data") or {})
            now = _now()
            entity_type = str(item.get("entity_type", "note"))
            table = {"note": "family_notes", "checklist_item": "checklist_items",
                     "reminder": "reminders"}.get(entity_type)
            if table is None:
                results.append({"op_id": op_id, "status": "rejected",
                                "error": {"code": "sync.unsupported_entity"}})
                continue
            row = conn.execute(f"SELECT version FROM {table} WHERE id=?", (entity_id,)).fetchone()
            if item.get("op", "upsert") == "delete":
                version = int(row["version"]) + 1 if row else 1
                conn.execute(f"UPDATE {table} SET deleted_at=?, version=?, updated_at=?, updated_by=? WHERE id=?",
                             (now, version, now, user_id, entity_id))
                data = {"id": entity_id, "deleted_at": now}
                op = "delete"
            else:
                base_version = int(item.get("base_version", 0))
                if row and base_version and base_version != int(row["version"]) and entity_type == "note":
                    current = conn.execute("SELECT * FROM family_notes WHERE id=?", (entity_id,)).fetchone()
                    result = {"op_id": op_id, "status": "conflict", "reason": "version_mismatch",
                              "server": {"version": current["version"],
                                         "data": {"id": current["id"], "title": current["title"],
                                                  "body_md": current["body_md"]}}}
                    results.append(result)
                    conn.execute(
                        "INSERT INTO sync_op_receipts VALUES(?,?,?,?,?,?,?)",
                        (household_id, user_id, op_id, "conflict", current["version"],
                         json.dumps(result), now),
                    )
                    continue
                version = int(row["version"]) + 1 if row else 1
                if entity_type == "note":
                    notebook_id = str(payload.get("notebook_id") or
                                      conn.execute("SELECT id FROM notebooks WHERE household_id=? LIMIT 1",
                                                   (household_id,)).fetchone()["id"])
                    conn.execute(
                        """INSERT INTO family_notes(id,household_id,notebook_id,author_user_id,kind,title,body_md,pinned,version,updated_at,updated_by,deleted_at)
                           VALUES(?,?,?,?,?,?,?,?,?,?,?,NULL)
                           ON CONFLICT(id) DO UPDATE SET title=excluded.title,body_md=excluded.body_md,
                           pinned=excluded.pinned,version=excluded.version,updated_at=excluded.updated_at,
                           updated_by=excluded.updated_by,deleted_at=NULL""",
                        (entity_id, household_id, notebook_id, user_id, payload.get("kind", "note"),
                         str(payload.get("title", ""))[:200], str(payload.get("body_md", ""))[:102400],
                         int(bool(payload.get("pinned", False))), version, now, user_id))
                elif entity_type == "checklist_item":
                    conn.execute(
                        """INSERT INTO checklist_items(id,household_id,note_id,text,done,position,assignee_user_id,version,updated_at,updated_by,deleted_at)
                           VALUES(?,?,?,?,?,?,?,?,?,?,NULL)
                           ON CONFLICT(id) DO UPDATE SET text=excluded.text,done=excluded.done,
                           position=excluded.position,assignee_user_id=excluded.assignee_user_id,
                           version=excluded.version,updated_at=excluded.updated_at,updated_by=excluded.updated_by,deleted_at=NULL""",
                        (entity_id, household_id, payload.get("note_id"), str(payload.get("text", ""))[:500],
                         int(bool(payload.get("done", False))), payload.get("position", "a0"),
                         payload.get("assignee_user_id"), version, now, user_id))
                else:
                    conn.execute(
                        """INSERT INTO reminders(id,household_id,created_by_user_id,title,body,due_at,timezone,rrule,urgent,note_id,item_id,status,version,updated_at,updated_by,deleted_at)
                           VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,NULL)
                           ON CONFLICT(id) DO UPDATE SET title=excluded.title,body=excluded.body,
                           due_at=excluded.due_at,timezone=excluded.timezone,rrule=excluded.rrule,
                           urgent=excluded.urgent,status=excluded.status,version=excluded.version,
                           updated_at=excluded.updated_at,updated_by=excluded.updated_by,deleted_at=NULL""",
                        (entity_id, household_id, user_id, str(payload.get("title", ""))[:200],
                         str(payload.get("body", "")), str(payload.get("due_at", now)),
                         str(payload.get("timezone", "UTC")), payload.get("rrule"),
                         int(bool(payload.get("urgent", False))), payload.get("note_id"),
                         payload.get("item_id"), payload.get("status", "active"), version, now, user_id))
                data = {"id": entity_id, "household_id": household_id, **payload, "updated_at": now}
                op = "upsert"
            conn.execute(
                "INSERT INTO family_changes(household_id,entity_type,entity_id,op,version,data,changed_at) VALUES(?,?,?,?,?,?,?)",
                (household_id, entity_type, entity_id, op, version, json.dumps(data), now))
            result = {"op_id": op_id, "entity_id": entity_id, "status": "applied", "version": version}
            conn.execute(
                "INSERT INTO sync_op_receipts VALUES(?,?,?,?,?,?,?)",
                (household_id, user_id, op_id, "applied", version, json.dumps(result), now),
            )
            results.append(result)
        latest = conn.execute("SELECT COALESCE(MAX(seq),0) AS seq FROM family_changes WHERE household_id=?",
                              (household_id,)).fetchone()["seq"]
        return {"results": results, "latest_seq": latest}


def changes(user_id: int, household_id: str, cursor: int, limit: int) -> Dict[str, Any]:
    with database.get_connection() as conn:
        if not _member(conn, household_id, user_id):
            raise PermissionError("Household membership required")
        rows = conn.execute(
            "SELECT seq,entity_type,entity_id,op,version,data,changed_at FROM family_changes "
            "WHERE household_id=? AND seq>? ORDER BY seq LIMIT ?",
            (household_id, cursor, min(max(limit, 1), 500))).fetchall()
        result = [{"seq": r["seq"], "entity_type": r["entity_type"], "entity_id": r["entity_id"],
                   "op": r["op"], "version": r["version"], "data": json.loads(r["data"]) if r["data"] else None,
                   "changed_at": r["changed_at"]} for r in rows]
        return {"household_id": household_id, "snapshot": cursor == 0,
                "changes": result, "next_cursor": result[-1]["seq"] if result else cursor,
                "has_more": len(result) == min(max(limit, 1), 500),
                "server_time": _now()}
