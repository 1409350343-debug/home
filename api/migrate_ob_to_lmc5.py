"""Migrate brain-data.json (ombre-brain) → LMC-5 SQLite store."""

import json
import sys
sys.path.insert(0, "/root/lmc-5/src")

from lmc5.store import MemoryStore

BRAIN_DATA = "/var/www/home/brain-data.json"
LMC5_DB = "/var/www/home/api/lmc5_memory.db"

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

        if why:
            content = content + "\n\n[why_remembered] " + why

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
