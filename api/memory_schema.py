"""LMC-5 记忆库的向后兼容扩展。

只补充小窝需要的字段、历史表和索引，不修改已有字段内容。
"""
import json
import sqlite3


def table_columns(conn, table):
    return {
        row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()
    }


def ensure_memory_schema(conn):
    columns = table_columns(conn, "memories")
    if not columns:
        raise sqlite3.OperationalError("memories table does not exist")

    additions = {
        "why_remembered": "TEXT NOT NULL DEFAULT ''",
        "archived_at": "TEXT",
    }
    for name, declaration in additions.items():
        if name not in columns:
            conn.execute(f"ALTER TABLE memories ADD COLUMN {name} {declaration}")

    conn.execute(
        """CREATE TABLE IF NOT EXISTS memory_history (
               id INTEGER PRIMARY KEY AUTOINCREMENT,
               memory_id INTEGER NOT NULL,
               action TEXT NOT NULL,
               reason TEXT NOT NULL DEFAULT '',
               snapshot_json TEXT NOT NULL DEFAULT '{}',
               changed_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
           )"""
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_memories_status ON memories(status)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_memory_history_memory "
        "ON memory_history(memory_id, changed_at DESC)"
    )
    conn.commit()


def memory_snapshot(conn, memory_id):
    row = conn.execute(
        "SELECT * FROM memories WHERE id=?", (memory_id,)
    ).fetchone()
    if row is None:
        return {}
    if isinstance(row, sqlite3.Row):
        return dict(row)
    columns = [item[0] for item in conn.execute(
        "SELECT * FROM memories WHERE id=? LIMIT 0", (memory_id,)
    ).description]
    return dict(zip(columns, row))


def record_history(conn, memory_id, action, reason="", snapshot=None):
    if snapshot is None:
        snapshot = memory_snapshot(conn, memory_id)
    conn.execute(
        """INSERT INTO memory_history
               (memory_id, action, reason, snapshot_json)
           VALUES (?, ?, ?, ?)""",
        (
            memory_id,
            action,
            reason or "",
            json.dumps(snapshot, ensure_ascii=False, default=str),
        ),
    )
