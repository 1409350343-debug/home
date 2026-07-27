#!/usr/bin/env python3
"""从 LMC-5 数据库生成 brain-data.json 给记忆屋页面用。"""
import json
import os
import re
import sqlite3
import time

LMC5_DB = '/var/www/home/api/lmc5_memory.db'
OUT = '/var/www/home/brain-data.json'

THREAD_TO_TIER = {
    'core': 'permanent',
    'note': 'dynamic',
    'feel': 'feel',
    'archive': 'archive',
}
TIER_ZH = {
    'permanent': '核心',
    'dynamic': '流动',
    'feel': '感受',
    'archive': '归档',
}


def load_memories():
    conn = sqlite3.connect(LMC5_DB)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute('''
        SELECT id, title, content, thread, category, tags_json,
               valence, arousal, hit_count, created_at, updated_at,
               status
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

        tier = THREAD_TO_TIER.get(row['thread'] or 'note', 'dynamic')
        if row['status'] == 'archived':
            tier = 'archive'

        buckets.append({
            'id': str(row['id']),
            'name': row['title'] or '',
            'title': row['title'] or row['content'][:14],
            'tier': tier,
            'category': row['category'] or '',
            'tags': tags if isinstance(tags, list) else [tags],
            'importance': 5,
            'created': row['created_at'] or '',
            'last_active': row['updated_at'] or '',
            'valence': float(row['valence'] or 0.5),
            'activation': int(row['hit_count'] or 0),
            'why': '',
            'content': row['content'] or '',
        })
    conn.close()
    return buckets


def main():
    buckets = load_memories()

    lifeline = ''
    lf_candidates = [
        '/root/.claude/projects/-var-www-home-api/memory/lifeline.md',
        '/root/.claude/projects/-root/memory/lifeline.md',
    ]
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
