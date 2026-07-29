"""Migrate brain-data.json (ombre-brain) → LMC-5 SQLite store."""

import json
import sys

from memory_config import BRAIN_DATA, LMC5_DB, LMC5_SRC
from memory_schema import ensure_memory_schema, record_history

sys.path.insert(0, str(LMC5_SRC))

from lmc5.store import MemoryStore

BRAIN_DATA = str(BRAIN_DATA)
LMC5_DB = str(LMC5_DB)

CATEGORY_MAP = {
    "恋爱": "relationship",
    "居家": "daily",
    "技术": "technical",
    "社交": "social",
    "阅读": "reading",
    "情感": "emotion",
}

def migrate():
    with open(BRAIN_DATA, "r") as f:
        data = json.load(f)

    buckets = data.get("buckets", [])
    print(f"Found {len(buckets)} buckets to migrate")

    store = MemoryStore(LMC5_DB)
    ensure_memory_schema(store.conn)

    imported = 0
    skipped = 0

    for b in buckets:
        title = b.get("title") or b.get("name", "untitled")
        content = b.get("content", "")
        if not content.strip():
            skipped += 1
            continue

        tags = b.get("tags", [])
        category = CATEGORY_MAP.get(b.get("category", ""), "note")
        importance = b.get("importance", 5)
        valence_raw = b.get("valence", 0.5)
        valence = (valence_raw * 2) - 1  # 0~1 → -1~1
        created = b.get("created", "")
        why = b.get("why", "")

        thread = category

        try:
            record, is_new = store.add_memory(
                title=title,
                content=content,
                thread=thread,
                category=category,
                tags=tags,
                valence=max(-1.0, min(1.0, valence)),
                source="ombre-brain-migration",
            )
            # MemoryStore 的公开添加接口没有接收旧时间；迁移后补回原始
            # 创建时间和事件日期，避免旧记忆被当成迁移当天发生的事。
            if record.id is not None:
                why_text = why or "旧系统未记录原因（迁移时保留）"
                created_text = str(created)
                store.conn.execute(
                    """UPDATE memories
                       SET why_remembered = ?,
                           created_at = CASE WHEN ? != '' THEN ? ELSE created_at END,
                           event_date = COALESCE(NULLIF(event_date, ''), ?)
                       WHERE id = ?""",
                    (
                        why_text,
                        created_text,
                        created_text,
                        created_text[:10] if created_text else None,
                        record.id,
                    ),
                )
                if is_new:
                    record_history(
                        store.conn,
                        record.id,
                        "migrated",
                        why_text,
                    )
                store.conn.commit()
            if is_new:
                imported += 1
            else:
                skipped += 1
        except Exception as e:
            print(f"  Error on '{title}': {e}")
            skipped += 1

    store.close()
    print(f"\nMigration complete: {imported} imported, {skipped} skipped")
    print(f"Database: {LMC5_DB}")

if __name__ == "__main__":
    migrate()
