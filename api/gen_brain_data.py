#!/usr/bin/env python3
"""从 LMC-5 数据库生成 brain-data.json 给记忆屋页面用。"""
import json
import os
import re
import sqlite3
import time

from memory_config import BRAIN_DATA, LIFELINE_CANDIDATES, LMC5_DB
from memory_schema import ensure_memory_schema

LMC5_DB = str(LMC5_DB)
OUT = str(BRAIN_DATA)

def to_ui_valence(value):
    """LMC-5 的 -1~1 情绪值转换为记忆屋使用的 0~1。"""
    if value is None:
        return 0.5
    try:
        normalized = (float(value) + 1.0) / 2.0
    except (TypeError, ValueError):
        return 0.5
    return max(0.0, min(1.0, normalized))


def load_memories():
    conn = sqlite3.connect(LMC5_DB)
    conn.row_factory = sqlite3.Row
    ensure_memory_schema(conn)
    cur = conn.cursor()
    columns = {
        row['name'] for row in conn.execute('PRAGMA table_info(memories)').fetchall()
    }
    tier_column = 'tier' if 'tier' in columns else 'NULL AS tier'
    cur.execute(f'''
        SELECT id, title, content, thread, category, tags_json,
               valence, arousal, hit_count, created_at, updated_at,
               status, why_remembered, fact_key, fact_value, valid_from,
               valid_to, is_current_fact, supersedes_id, change_reason,
               review_status, {tier_column}
        FROM memories
        ORDER BY id DESC
    ''')
    buckets = []
    for row in cur.fetchall():
        tags = []
        if row['tags_json']:
            try:
                tags = json.loads(row['tags_json'])
            except Exception:
                pass

        tier = row['tier'] or ('archive' if row['status'] == 'archived' else 'dynamic')

        buckets.append({
            'id': str(row['id']),
            'name': row['title'] or '',
            'title': row['title'] or row['content'][:14],
            'tier': tier,
            'thread': row['thread'] or '',
            'category': row['category'] or '',
            'status': row['status'] or '',
            'tags': tags if isinstance(tags, list) else [tags],
            'importance': 5,
            'created': row['created_at'] or '',
            'last_active': row['updated_at'] or '',
            'valence': to_ui_valence(row['valence']),
            'activation': int(row['hit_count'] or 0),
            'why': row['why_remembered'] or '',
            'content': row['content'] or '',
            'fact_key': row['fact_key'] or '',
            'fact_value': row['fact_value'] or '',
            'valid_from': row['valid_from'] or '',
            'valid_to': row['valid_to'] or '',
            'is_current_fact': bool(row['is_current_fact']),
            'supersedes_id': row['supersedes_id'],
            'change_reason': row['change_reason'] or '',
            'review_status': row['review_status'] or '',
        })
    conn.close()
    return buckets


def main():
    buckets = load_memories()

    lifeline = ''
    lf_candidates = [str(path) for path in LIFELINE_CANDIDATES]
    lf = next((p for p in lf_candidates if os.path.exists(p)), lf_candidates[0])
    if os.path.exists(lf):
        raw = open(lf, encoding='utf-8').read()
        m = re.match(r'^---\n.*?\n---\n(.*)$', raw, re.S)
        lifeline = (m.group(1) if m else raw).strip()

    json.dump(
        {'buckets': buckets, 'lifeline': lifeline, 'generated': time.time()},
        open(OUT, 'w'), ensure_ascii=False
    )
    print(f'wrote {OUT}: {len(buckets)} memories from LMC-5')


if __name__ == '__main__':
    main()
