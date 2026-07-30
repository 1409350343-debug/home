#!/usr/bin/env python3
"""记忆角 API：直接读取 LMC-5 SQLite，与主动召回共用同一数据源。"""
import json
import hmac
import os
import sqlite3
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

from memory_config import LMC5_DB, MEMORY_API_TOKEN
from memory_schema import ensure_memory_schema, memory_snapshot, record_history
from memory_steward import (
    public_config as steward_public_config,
    public_status as steward_public_status,
    run_once as steward_run_once,
    save_config as steward_save_config,
)


UNCATEGORIZED = "uncategorized"


def connect_db():
    if not os.path.exists(LMC5_DB):
        raise FileNotFoundError(f"memory database not found: {LMC5_DB}")
    conn = sqlite3.connect(LMC5_DB)
    conn.row_factory = sqlite3.Row
    ensure_memory_schema(conn)
    return conn


def parse_tags(value):
    if not value:
        return []
    try:
        tags = json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return []
    return tags if isinstance(tags, list) else [str(tags)]


def category_id(row):
    """保留数据库的实际值；category 为空时才回退到 thread。"""
    return row["category"] or row["thread"] or UNCATEGORIZED


def importance(row):
    """兼容旧页面的 1~10 展示，不改变数据库中的真实字段。"""
    keys = set(row.keys())
    if "importance" in keys and row["importance"] is not None:
        try:
            return max(1, min(10, int(row["importance"])))
        except (TypeError, ValueError):
            pass
    urgency = row["urgency"] if "urgency" in keys else None
    return {"urgent": 10, "high": 9, "low": 3}.get(urgency, 5)


def serialize_memory(row):
    keys = set(row.keys())
    content = row["content"] or ""
    created = row["event_date"] or row["created_at"] or ""
    updated = row["updated_at"] if "updated_at" in keys else ""
    tier = row["tier"] if "tier" in keys else ""
    return {
        "id": row["id"],
        "title": row["title"] or "",
        "preview": content[:120] + ("..." if len(content) > 120 else ""),
        "content": content,
        "category": category_id(row),
        "thread": row["thread"] or "",
        "status": row["status"] or "",
        "tier": tier or "",
        "importance": importance(row),
        "pinned": bool(row["pinned"]) if "pinned" in keys else False,
        "type": tier or row["thread"] or "",
        "tags": parse_tags(row["tags_json"]),
        "created": str(created),
        "last_active": str(updated or ""),
        "valence": row["valence"] if "valence" in keys else None,
        "arousal": row["arousal"] if "arousal" in keys else None,
        "why_remembered": (
            row["why_remembered"] if "why_remembered" in keys else ""
        ) or "",
        "fact_key": row["fact_key"] if "fact_key" in keys else "",
        "fact_value": row["fact_value"] if "fact_value" in keys else "",
        "valid_from": row["valid_from"] if "valid_from" in keys else None,
        "valid_to": row["valid_to"] if "valid_to" in keys else None,
        "is_current_fact": bool(row["is_current_fact"]) if "is_current_fact" in keys else False,
        "supersedes_id": row["supersedes_id"] if "supersedes_id" in keys else None,
        "source_message_id": row["source_message_id"] if "source_message_id" in keys else "",
        "change_reason": row["change_reason"] if "change_reason" in keys else "",
        "review_status": row["review_status"] if "review_status" in keys else "",
    }


def load_current_rows(conn):
    return conn.execute(
        "SELECT * FROM memories WHERE status='current' ORDER BY id DESC"
    ).fetchall()


def build_categories(rows):
    counts = {}
    for row in rows:
        cid = category_id(row)
        counts[cid] = counts.get(cid, 0) + 1
    return [
        {
            "id": cid,
            "name": "未分类" if cid == UNCATEGORIZED else cid,
            "desc": "数据库中的现有分类",
            "icon": "folder",
            "count": count,
        }
        for cid, count in sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    ]


def get_all_memories():
    with connect_db() as conn:
        rows = load_current_rows(conn)
    categories = build_categories(rows)
    memories = {cat["id"]: [] for cat in categories}
    for row in rows:
        memories[category_id(row)].append(serialize_memory(row))
    return categories, memories


def search_memories(query):
    pattern = f"%{query}%"
    with connect_db() as conn:
        rows = conn.execute(
            """SELECT * FROM memories
               WHERE status='current'
                 AND (title LIKE ? OR content LIKE ? OR tags_json LIKE ?)
               ORDER BY id DESC
               LIMIT 100""",
            (pattern, pattern, pattern),
        ).fetchall()
    return [serialize_memory(row) for row in rows]


def update_category(memory_id, category):
    with connect_db() as conn:
        before = memory_snapshot(conn, memory_id)
        cur = conn.execute(
            """UPDATE memories
               SET category=?, updated_at=CURRENT_TIMESTAMP
               WHERE id=? AND status='current'""",
            (category, memory_id),
        )
        if cur.rowcount == 1:
            old_category = before.get("category") or ""
            record_history(
                conn,
                memory_id,
                "category_changed",
                f"{old_category} -> {category}",
                snapshot=before,
            )
        conn.commit()
    return cur.rowcount == 1


def archive_memory(memory_id):
    with connect_db() as conn:
        before = memory_snapshot(conn, memory_id)
        cur = conn.execute(
            """UPDATE memories
               SET status='archived',
                   archived_at=CURRENT_TIMESTAMP,
                   updated_at=CURRENT_TIMESTAMP
               WHERE id=? AND status='current'""",
            (memory_id,),
        )
        if cur.rowcount == 1:
            record_history(conn, memory_id, "archived", snapshot=before)
        conn.commit()
    return cur.rowcount == 1


def restore_memory(memory_id):
    with connect_db() as conn:
        before = memory_snapshot(conn, memory_id)
        cur = conn.execute(
            """UPDATE memories
               SET status='current',
                   archived_at=NULL,
                   updated_at=CURRENT_TIMESTAMP
               WHERE id=? AND status='archived'""",
            (memory_id,),
        )
        if cur.rowcount == 1:
            record_history(conn, memory_id, "restored", snapshot=before)
        conn.commit()
    return cur.rowcount == 1


def get_archived_memories():
    with connect_db() as conn:
        rows = conn.execute(
            """SELECT * FROM memories
               WHERE status='archived'
               ORDER BY COALESCE(archived_at, updated_at, created_at) DESC"""
        ).fetchall()
    return [serialize_memory(row) for row in rows]


def get_memory_history(memory_id):
    with connect_db() as conn:
        rows = conn.execute(
            """SELECT id, memory_id, action, reason, snapshot_json, changed_at
               FROM memory_history WHERE memory_id=?
               ORDER BY id DESC""",
            (memory_id,),
        ).fetchall()
    return [dict(row) for row in rows]


def get_facts(fact_key=""):
    """返回事实当前值及历史版本；供页面和外接 AI 做确定性检索。"""
    with connect_db() as conn:
        params = []
        where = "WHERE fact_key <> ''"
        if fact_key:
            where += " AND fact_key=?"
            params.append(fact_key)
        rows = conn.execute(
            f"""SELECT * FROM memories {where}
                ORDER BY fact_key,
                         is_current_fact DESC,
                         COALESCE(valid_from, created_at) DESC,
                         id DESC""",
            params,
        ).fetchall()

    groups = {}
    for row in rows:
        item = serialize_memory(row)
        groups.setdefault(item["fact_key"], []).append(item)
    return [
        {
            "fact_key": key,
            "current": next(
                (
                    item for item in versions
                    if item["is_current_fact"]
                    and item["review_status"] == "confirmed"
                ),
                None,
            ),
            "pending": [
                item for item in versions
                if item["review_status"] in ("pending", "conflict")
            ],
            "versions": versions,
        }
        for key, versions in groups.items()
    ]


class MemoryHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = urlparse(self.path)
        try:
            if parsed.path == "/api/memory":
                categories, memories = get_all_memories()
                self._json_response({"categories": categories, "memories": memories})
            elif parsed.path == "/api/memory/search":
                q = parse_qs(parsed.query).get("q", [""])[0].strip()
                self._json_response({"results": search_memories(q) if q else []})
            elif parsed.path == "/api/memory/stats":
                categories, memories = get_all_memories()
                stats = {cat["id"]: len(memories[cat["id"]]) for cat in categories}
                stats["total"] = sum(stats.values())
                self._json_response(stats)
            elif parsed.path == "/api/memory/archive":
                self._json_response({"memories": get_archived_memories()})
            elif parsed.path == "/api/memory/history":
                memory_id = int(parse_qs(parsed.query).get("id", [""])[0])
                self._json_response({"history": get_memory_history(memory_id)})
            elif parsed.path == "/api/memory/facts":
                fact_key = parse_qs(parsed.query).get("key", [""])[0].strip()
                self._json_response({"facts": get_facts(fact_key)})
            elif parsed.path == "/api/memory/steward/config":
                self._json_response(steward_public_config())
            elif parsed.path == "/api/memory/steward/status":
                self._json_response(steward_public_status())
            else:
                self._json_response({"error": "not found"}, 404)
        except (FileNotFoundError, sqlite3.Error, RuntimeError) as exc:
            self._json_response({"error": str(exc)}, 503)

    def do_POST(self):
        try:
            if not self._write_authorized():
                self._json_response({"error": "unauthorized"}, 401)
                return
            body = self._read_json()
            if self.path == "/api/memory/steward/config":
                self._json_response(steward_save_config(body))
                return
            if self.path == "/api/memory/steward/run":
                self._json_response(steward_run_once(force=True))
                return
            memory_id = int(body.get("id"))
            if self.path == "/api/memory/categorize":
                category = str(body.get("category") or "").strip()
                if not category:
                    self._json_response({"error": "missing category"}, 400)
                    return
                ok = update_category(memory_id, category)
            elif self.path == "/api/memory/delete":
                # 页面沿用旧接口名称，实际行为改为归档，避免不可恢复地删除。
                ok = archive_memory(memory_id)
            elif self.path == "/api/memory/restore":
                ok = restore_memory(memory_id)
            else:
                self._json_response({"error": "not found"}, 404)
                return
            self._json_response({"ok": ok}, 200 if ok else 404)
        except (TypeError, ValueError, json.JSONDecodeError):
            self._json_response({"error": "invalid request body"}, 400)
        except (FileNotFoundError, sqlite3.Error, RuntimeError) as exc:
            self._json_response({"error": str(exc)}, 503)

    def _read_json(self):
        length = int(self.headers.get("Content-Length", 0))
        return json.loads(self.rfile.read(length)) if length else {}

    def _write_authorized(self):
        """配置 Token 时保护写操作；未配置时依赖同源和外层站点认证。"""
        if not MEMORY_API_TOKEN:
            return True
        supplied = self.headers.get("X-Memory-Token", "")
        auth = self.headers.get("Authorization", "")
        if auth.startswith("Bearer "):
            supplied = auth[7:]
        return hmac.compare_digest(supplied, MEMORY_API_TOKEN)

    def _json_response(self, data, code=200):
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.end_headers()
        self.wfile.write(json.dumps(data, ensure_ascii=False).encode())

    def log_message(self, format, *args):
        pass


if __name__ == "__main__":
    server = HTTPServer(("127.0.0.1", 9904), MemoryHandler)
    print(f"Memory API running on :9904 using {LMC5_DB}")
    server.serve_forever()
