"""LMC-5 memory tool — search, add, relate, stats.

Usage:
    python3 lmc5_tool.py search "拼豆"
    python3 lmc5_tool.py search "拼豆" --limit 5
    python3 lmc5_tool.py add --title "猫断奶纱布法" --content "..." --thread relationship --tags 猫,断奶
    python3 lmc5_tool.py relate 12 45 same_topic --reason "都是猫相关"
    python3 lmc5_tool.py breath                    # 开机呼吸，浮几条记忆上来
    python3 lmc5_tool.py auto-relate              # scan all memories, build relations
    python3 lmc5_tool.py stats
    python3 lmc5_tool.py rebuild-fts               # rebuild FTS with jieba segments
"""

import argparse
import json
import re
import sys

sys.path.insert(0, "/root/lmc-5/src")

from lmc5.store import MemoryStore

DB_PATH = "/var/www/home/api/lmc5_memory.db"

try:
    import jieba
    jieba.setLogLevel(20)
    HAS_JIEBA = True
except ImportError:
    HAS_JIEBA = False


def _contains_cjk(text: str) -> bool:
    return bool(re.search(r'[一-鿿㐀-䶿]', text))


def _jieba_cut(text: str) -> list[str]:
    if not HAS_JIEBA:
        return [text]
    words = jieba.lcut(text)
    return [w.strip() for w in words if w.strip() and len(w.strip()) > 0]


def cmd_search(args):
    store = MemoryStore(DB_PATH)
    query = args.query
    limit = args.limit

    results = store.recall(query, limit=limit)

    if not results and HAS_JIEBA and _contains_cjk(query):
        segments = _jieba_cut(query)
        if len(segments) > 1:
            for seg in segments:
                if len(seg) >= 2:
                    extra = store.recall(seg, limit=limit)
                    results.extend(extra)
            seen = set()
            deduped = []
            for r in results:
                mid = r['id']
                if mid not in seen:
                    seen.add(mid)
                    deduped.append(r)
            results = sorted(deduped, key=lambda x: x['score'], reverse=True)[:limit]

    if not results:
        print(f"No results for: {query}")
        store.close()
        return

    for i, r in enumerate(results, 1):
        title = r['title'][:60]
        score = r['score']
        channels = r.get('trace', {}).get('channels', [])
        content_preview = r['content'][:120].replace('\n', ' ')
        tags = r.get('tags', [])
        print(f"[{i}] (id={r['id']}, score={score}) {title}")
        print(f"    channels: {channels}")
        print(f"    tags: {tags}")
        print(f"    {content_preview}")
        print()

    store.close()


def cmd_add(args):
    store = MemoryStore(DB_PATH)
    tags = [t.strip() for t in args.tags.split(',')] if args.tags else []
    valence = float(args.valence) if args.valence else None

    record, is_new = store.add_memory(
        title=args.title,
        content=args.content,
        thread=args.thread or "note",
        category=args.category or "note",
        tags=tags,
        valence=valence,
        source=args.source or "conversation",
    )
    if is_new and record.id is not None and HAS_JIEBA:
        title_seg = args.title
        content_seg = args.content
        if _contains_cjk(title_seg):
            title_seg = title_seg + " " + " ".join(_jieba_cut(title_seg))
        if _contains_cjk(content_seg):
            content_seg = content_seg + " " + " ".join(_jieba_cut(content_seg))
        tags_json = json.dumps(tags, ensure_ascii=False)
        store.conn.execute(
            "INSERT OR REPLACE INTO memories_fts(rowid, title, content, thread, category, tags, fact_key) VALUES (?,?,?,?,?,?,?)",
            (record.id, title_seg, content_seg, args.thread or "note", args.category or "note", tags_json, ""),
        )
        store.conn.commit()
    if is_new:
        print(f"Added memory id={record.id}: {args.title}")
    else:
        print(f"Memory already exists id={record.id}: {args.title}")
    store.close()


def cmd_relate(args):
    store = MemoryStore(DB_PATH)
    rel = store.add_relation(
        source_id=args.source_id,
        target_id=args.target_id,
        relation_type=args.relation_type,
        strength=args.strength,
        reason=args.reason or "",
    )
    print(f"Relation id={rel.id}: {args.source_id} --[{args.relation_type}]--> {args.target_id}")
    store.close()


def cmd_auto_relate(args):
    store = MemoryStore(DB_PATH)
    import sqlite3

    rows = store.conn.execute(
        "SELECT id, title, content, thread, category, tags_json FROM memories WHERE status='current' ORDER BY id"
    ).fetchall()

    memories = []
    for row in rows:
        tags = json.loads(row["tags_json"] or "[]")
        memories.append({
            "id": row["id"],
            "title": row["title"],
            "content": row["content"],
            "thread": row["thread"],
            "category": row["category"],
            "tags": tags,
        })

    existing = store.conn.execute("SELECT count(*) FROM relations").fetchone()[0]
    print(f"Memories: {len(memories)}, existing relations: {existing}")

    tag_index = {}
    for m in memories:
        for tag in m["tags"]:
            tag_index.setdefault(tag, []).append(m["id"])

    thread_index = {}
    for m in memories:
        thread_index.setdefault(m["thread"], []).append(m["id"])

    added = 0

    for tag, ids in tag_index.items():
        if len(ids) < 2 or len(ids) > 30:
            continue
        for i in range(len(ids)):
            for j in range(i + 1, len(ids)):
                try:
                    store.add_relation(
                        source_id=ids[i],
                        target_id=ids[j],
                        relation_type="same_topic",
                        strength=0.6,
                        reason=f"shared tag: {tag}",
                    )
                    added += 1
                except (ValueError, sqlite3.IntegrityError):
                    pass

    for thread, ids in thread_index.items():
        if thread == "note" or len(ids) < 2:
            continue
        for i in range(len(ids)):
            for j in range(i + 1, min(i + 5, len(ids))):
                try:
                    store.add_relation(
                        source_id=ids[i],
                        target_id=ids[j],
                        relation_type="in_thread",
                        strength=0.4,
                        reason=f"same thread: {thread}",
                    )
                    added += 1
                except (ValueError, sqlite3.IntegrityError):
                    pass

    print(f"Added {added} relations")
    store.close()


def cmd_rebuild_fts(args):
    if not HAS_JIEBA:
        print("jieba not installed, cannot rebuild FTS with Chinese tokenization")
        return

    store = MemoryStore(DB_PATH)
    rows = store.conn.execute(
        "SELECT id, title, content, thread, category, tags_json, fact_key FROM memories"
    ).fetchall()

    store.conn.execute("DELETE FROM memories_fts")

    for row in rows:
        title = row["title"]
        content = row["content"]
        if _contains_cjk(title):
            title = title + " " + " ".join(_jieba_cut(title))
        if _contains_cjk(content):
            content = content + " " + " ".join(_jieba_cut(content))

        tags = row["tags_json"] or ""
        store.conn.execute(
            "INSERT INTO memories_fts(rowid, title, content, thread, category, tags, fact_key) VALUES (?,?,?,?,?,?,?)",
            (row["id"], title, content, row["thread"], row["category"], tags, row["fact_key"] or ""),
        )

    store.conn.commit()
    print(f"Rebuilt FTS for {len(rows)} memories with jieba segmentation")
    store.close()


BREATH_COLS = "id, title, content, thread, event_date, created_at, valence, hit_count"


def cmd_breath(args):
    """开机呼吸：从记忆库里浮几条上来（替代旧的 ombre-brain breath）。"""
    store = MemoryStore(DB_PATH)
    picked = []
    seen = set()

    def pick(label, sql):
        for row in store.conn.execute(sql).fetchall():
            if row["id"] not in seen:
                seen.add(row["id"])
                picked.append((label, row))
                return

    # 好回忆优先——她定的方针：多记好的，想起来都是快乐的
    pick("好事", f"""
        SELECT {BREATH_COLS} FROM memories
        WHERE status='current' AND valence >= 0.6
        ORDER BY RANDOM() LIMIT 5
    """)
    # 压箱底的：从最少被想起的50条里随机抽
    pick("好久没想起", f"""
        SELECT * FROM (
            SELECT {BREATH_COLS} FROM memories WHERE status='current'
            ORDER BY hit_count ASC, COALESCE(last_hit_at, created_at) ASC LIMIT 50
        ) ORDER BY RANDOM() LIMIT 5
    """)
    while len(picked) < args.count:
        before = len(picked)
        pick("随手翻到", f"""
            SELECT {BREATH_COLS} FROM memories
            WHERE status='current' ORDER BY RANDOM() LIMIT 10
        """)
        if len(picked) == before:
            break

    total = store.conn.execute(
        "SELECT count(*) FROM memories WHERE status='current'"
    ).fetchone()[0]
    print(f"🫧 呼吸 · {total}条记忆里浮上来{len(picked)}条\n")

    for label, row in picked[:args.count]:
        day = (row["event_date"] or row["created_at"] or "")[:10]
        body = " ".join((row["content"] or "").split())[:150]
        print(f"[{label}] id={row['id']} {day} · {row['title']}")
        print(f"    {body}")
        print()
        store.conn.execute(
            "UPDATE memories SET hit_count = hit_count + 1, "
            "last_hit_at = strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id = ?",
            (row["id"],),
        )
    store.conn.commit()
    store.close()


def cmd_stats(args):
    store = MemoryStore(DB_PATH)
    mc = store.conn.execute("SELECT count(*) FROM memories WHERE status='current'").fetchone()[0]
    mt = store.conn.execute("SELECT count(*) FROM memories").fetchone()[0]
    rc = store.conn.execute("SELECT count(*) FROM relations").fetchone()[0]
    ec = store.conn.execute("SELECT count(*) FROM memory_entities").fetchone()[0]

    threads = store.conn.execute(
        "SELECT thread, count(*) as c FROM memories WHERE status='current' GROUP BY thread ORDER BY c DESC"
    ).fetchall()
    cats = store.conn.execute(
        "SELECT category, count(*) as c FROM memories WHERE status='current' GROUP BY category ORDER BY c DESC"
    ).fetchall()

    top_tags = store.conn.execute("""
        SELECT je.value as tag, count(*) as c
        FROM memories m, json_each(m.tags_json) je
        WHERE m.status='current'
        GROUP BY tag ORDER BY c DESC LIMIT 15
    """).fetchall()

    print(f"Memories: {mc} current / {mt} total")
    print(f"Relations: {rc}")
    print(f"Entities: {ec}")
    print(f"\nThreads:")
    for row in threads:
        print(f"  {row[0]}: {row[1]}")
    print(f"\nCategories:")
    for row in cats:
        print(f"  {row[0]}: {row[1]}")
    print(f"\nTop tags:")
    for row in top_tags:
        print(f"  {row[0]}: {row[1]}")

    store.close()


def main():
    parser = argparse.ArgumentParser(description="LMC-5 memory tool")
    sub = parser.add_subparsers(dest="command")

    p_search = sub.add_parser("search")
    p_search.add_argument("query")
    p_search.add_argument("--limit", type=int, default=5)

    p_add = sub.add_parser("add")
    p_add.add_argument("--title", required=True)
    p_add.add_argument("--content", required=True)
    p_add.add_argument("--thread", default="note")
    p_add.add_argument("--category", default="note")
    p_add.add_argument("--tags", default="")
    p_add.add_argument("--valence", default=None)
    p_add.add_argument("--source", default="conversation")

    p_relate = sub.add_parser("relate")
    p_relate.add_argument("source_id", type=int)
    p_relate.add_argument("target_id", type=int)
    p_relate.add_argument("relation_type")
    p_relate.add_argument("--strength", type=float, default=0.8)
    p_relate.add_argument("--reason", default="")

    p_breath = sub.add_parser("breath")
    p_breath.add_argument("--count", type=int, default=3)

    sub.add_parser("auto-relate")
    sub.add_parser("rebuild-fts")
    sub.add_parser("stats")

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        return

    cmds = {
        "search": cmd_search,
        "add": cmd_add,
        "relate": cmd_relate,
        "breath": cmd_breath,
        "auto-relate": cmd_auto_relate,
        "rebuild-fts": cmd_rebuild_fts,
        "stats": cmd_stats,
    }
    cmds[args.command](args)


if __name__ == "__main__":
    main()
