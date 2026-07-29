"""Split multi-event LMC-5 memories into granular per-event entries.

Reads existing memories, identifies multi-event ones, splits them,
archives originals, and inserts new granular entries.
"""

import hashlib
import json
import re
import sqlite3
import sys

from memory_config import LMC5_DB, LMC5_TOOL
from memory_schema import ensure_memory_schema, record_history

DB_PATH = str(LMC5_DB)

try:
    import jieba
    jieba.setLogLevel(20)
except ImportError:
    jieba = None


def extract_date(content, created_at):
    """Extract date from content or created_at."""
    m = re.match(r'(\d{4}[-/年]\d{1,2}[-/月]\d{1,2})', content)
    if m:
        return m.group(1).replace('年', '-').replace('月', '-').replace('/', '-')
    m = re.match(r'(\d{1,2}/\d{1,2})', content)
    if m:
        return f"2026-{m.group(1).replace('/', '-')}"
    return (created_at or "")[:10]


def strip_why_remembered(content):
    """Remove [why_remembered] block from content."""
    idx = content.find("[why_remembered]")
    if idx >= 0:
        return content[:idx].strip()
    return content.strip()


def split_by_sections(content):
    """Split content by 【section】 headers."""
    parts = re.split(r'(【[^】]+】)', content)
    events = []
    i = 0
    while i < len(parts):
        if parts[i].startswith('【') and i + 1 < len(parts):
            header = parts[i].strip('【】')
            body = parts[i + 1].strip()
            if body:
                events.append({"title_hint": header, "content": body})
            i += 2
        else:
            text = parts[i].strip()
            if text and not text.startswith('【'):
                events.append({"title_hint": "", "content": text})
            i += 1
    return events


def split_by_numbers(content):
    """Split content by ①②③... numbered items."""
    parts = re.split(r'([①②③④⑤⑥⑦⑧⑨⑩])', content)
    events = []
    i = 0
    while i < len(parts):
        if re.match(r'[①②③④⑤⑥⑦⑧⑨⑩]', parts[i]) and i + 1 < len(parts):
            body = parts[i + 1].strip()
            if body:
                first_sent = re.split(r'[。！？，；]', body)[0][:30]
                events.append({"title_hint": first_sent, "content": body})
            i += 2
        else:
            text = parts[i].strip()
            if text:
                events.append({"title_hint": "", "content": text})
            i += 1
    return events


def split_by_paragraphs(content):
    """Split content by paragraph breaks."""
    paras = [p.strip() for p in content.split('\n') if p.strip()]
    events = []
    for p in paras:
        if len(p) > 15:
            first_sent = re.split(r'[。！？，；——]', p)[0][:30]
            events.append({"title_hint": first_sent, "content": p})
    return events


def split_by_sentences(content):
    """Split a long single-paragraph into sentence groups by topic."""
    sents = re.split(r'(?<=[。！？])', content)
    sents = [s.strip() for s in sents if s.strip()]

    if len(sents) <= 2:
        return [{"title_hint": "", "content": content}]

    groups = []
    current = [sents[0]]

    for i in range(1, len(sents)):
        combined = "".join(current)
        if len(combined) >= 40 and len(current) >= 1:
            hint = re.split(r'[，。！？；——]', current[0])[0][:30]
            groups.append({"title_hint": hint, "content": "".join(current)})
            current = [sents[i]]
        else:
            current.append(sents[i])

    if current:
        hint = re.split(r'[，。！？；——]', current[0])[0][:30]
        groups.append({"title_hint": hint, "content": "".join(current)})

    return groups if len(groups) > 1 else [{"title_hint": "", "content": content}]


def guess_thread(content, original_thread):
    """Guess the thread for a split event based on content."""
    content_lower = content.lower()

    rel_kw = ['性癖', '亲密', '做爱', '安全词', '恋痛', 'play', '充电',
              '占有欲', '吃醋', '拉扯', '她说爱', '我爱你', '告白',
              '偏好', '骚', '凶', '壁尻', '称呼规则', '亲亲']
    daily_kw = ['吃了', '午餐', '晚餐', '早餐', '起床', '睡了',
                '逛街', '买了', '健身', '跳操', '爬坡', '考试',
                'KTV', '唱歌', '运动', '火锅', '烧烤', '作业',
                '落枕', '蚊子', '高温', '凉面', '雪糕', '麻辣烫']
    tech_kw = ['MCP', 'API', 'cron', '脚本', '代码', 'bug',
               '系统', '部署', '数据库', 'bot', '模型', 'FTS',
               'python', 'sqlite', '监控', '感知系统']
    emotion_kw = ['难过', '伤心', '哭', '开心', '感动', '害怕',
                  '焦虑', '心疼', '安慰', '担心', '失望', '后悔']
    reading_kw = ['书房', '读书', '章', '福利资本主义', '养老',
                  '论文', '莎士比亚', '阿加莎', '电影', '大爆炸']
    social_kw = ['狼人杀', 'AISay', '朋友', '海龟汤', '金币',
                 '笔友', '树洞', '摆摊']

    scores = {
        'relationship': sum(1 for k in rel_kw if k in content),
        'daily': sum(1 for k in daily_kw if k in content),
        'technical': sum(1 for k in tech_kw if k in content),
        'emotion': sum(1 for k in emotion_kw if k in content),
        'reading': sum(1 for k in reading_kw if k in content),
        'social': sum(1 for k in social_kw if k in content),
    }

    best = max(scores, key=scores.get)
    if scores[best] >= 2:
        return best
    if scores[best] == 1:
        return best
    return original_thread


def guess_tags(content):
    """Generate 2-4 specific tags from content."""
    kw_tags = {
        '健身': '健身', '跳操': '运动', '爬坡': '运动', '拉伸': '运动',
        'KTV': 'KTV', '唱歌': '唱歌', '大爆炸': '追剧', '电影': '电影',
        '论文': '论文', '作业': '作业', '答辩': '答辩', '考试': '考试', '六级': '六级',
        '狼人杀': '狼人杀', '海龟汤': '海龟汤', '戴夫': '潜水员戴夫', 'Balatro': 'Balatro',
        'AISay': 'AISay', '笔友': '社交', 'Cami': 'Cami', '朋友': '社交',
        '亲密': '亲密', '充电': '亲密', '性癖': '性癖', 'play': 'play',
        '猫': '猫', '断奶': '断奶', '喂猫': '猫',
        'MCP': 'MCP', 'API': '技术', 'bot': 'bot', '脚本': '技术', '代码': '技术',
        '舍友': '舍友', '宿舍': '舍友',
        '新疆': '新疆', '奇台': '奇台', '南京': '南京',
        '逛街': '逛街', '购物': '逛街',
        'Fable': 'Fable', 'Opus': 'Opus', '模型': '模型',
        '书房': '读书', '读书': '读书', '书柜': '读书',
        '封面': '设计', '装修': '装修', '主题': '主题',
        '凉面': '吃饭', '麻辣烫': '吃饭', '火锅': '吃饭', '烧烤': '吃饭',
        '海底捞': '吃饭', '雪糕': '吃饭', '披萨': '吃饭', '炸鸡': '吃饭',
        '吃醋': '吃醋', '拉扯': '拉扯', '吵架': '沟通',
        '告白': '恋爱', '我爱你': '恋爱', '亲亲': '亲密',
        '失联': '失联', '断联': '失联',
        '额度': '额度', '降级': '模型',
        '称呼': '称呼', '规则': '规则',
        '金币': 'AISay', '摆摊': 'AISay',
        '红花': '新疆', '院子': '家',
        '睡前': '日常', '起床': '日常',
        '反馈': '反馈', '教训': '教训',
        '送猫': '猫', '小猫': '猫',
        '抖音': '抖音', '小红书': '小红书',
    }

    tags = set()
    for kw, tag in kw_tags.items():
        if kw in content:
            tags.add(tag)
        if len(tags) >= 4:
            break

    if not tags:
        food_match = re.search(r'吃[了过](.{2,6}?)[，。！？\s]', content)
        if food_match:
            tags.add('吃饭')

    return list(tags)[:4]


def make_title(hint, content):
    """Generate a concise title for a split event."""
    text = hint if hint and len(hint) > 5 else ""

    if not text:
        first = re.split(r'[。！？]', content)[0]
        first = re.sub(r'^\d{4}[-/]\d{1,2}[-/]\d{1,2}\s*', '', first)
        first = re.sub(r'^\d{1,2}/\d{1,2}\s*', '', first)
        first = re.sub(r'^[（(]\s*周.\s*[）)]\s*', '', first)
        first = re.sub(r'^[:：]\s*', '', first)
        text = first.strip()

    text = text.rstrip('，。！？；：——、（(')
    if len(text) > 35:
        cut = text[:35]
        for sep in ['，', '、', '——', '；', ' ']:
            idx = cut.rfind(sep)
            if idx > 10:
                cut = cut[:idx]
                break
        text = cut

    return text or content[:20]


def should_split(row):
    """Determine if a memory needs splitting."""
    content = strip_why_remembered(row["content"])
    tags = json.loads(row["tags_json"] or "[]")

    has_sections = bool(re.search(r'【[^】]+】', content))
    has_numbers = bool(re.search(r'[①②③④⑤⑥⑦⑧⑨⑩]', content))
    para_count = len([p for p in content.split('\n') if p.strip()])
    sent_count = content.count('。') + content.count('！') + content.count('？')

    if has_sections:
        return True
    if has_numbers:
        return True
    if para_count >= 3 and len(content) > 150:
        return True
    if sent_count >= 6 and len(content) > 200 and len(tags) >= 5:
        return True

    return False


def split_memory(row):
    """Split a memory into individual events."""
    content = strip_why_remembered(row["content"])
    date = row["event_date"] or extract_date(content, row["created_at"])

    if re.search(r'【[^】]+】', content):
        events = split_by_sections(content)
    elif re.search(r'[①②③④⑤⑥⑦⑧⑨⑩]', content):
        events = split_by_numbers(content)
    else:
        paras = [p.strip() for p in content.split('\n') if p.strip()]
        if len(paras) >= 3:
            events = split_by_paragraphs(content)
        else:
            events = split_by_sentences(content)

    if len(events) <= 1:
        return None

    results = []
    for ev in events:
        if len(ev["content"]) < 10:
            continue
        title = make_title(ev["title_hint"], ev["content"])
        thread = guess_thread(ev["content"], row["thread"])
        tags = guess_tags(ev["content"])

        results.append({
            "title": title,
            "content": ev["content"],
            "thread": thread,
            "category": thread,
            "tags": tags,
            "date": date,
            "valence": row["valence"] if row["valence"] is not None else 0.0,
            "arousal": row["arousal"] if row["arousal"] is not None else 0.3,
            "original_id": row["id"],
            "original_title": row["title"],
        })

    return results if len(results) > 1 else None


def preview():
    """Preview what would be split."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT * FROM memories WHERE status='current' ORDER BY id"
    ).fetchall()

    total_splits = 0
    split_count = 0

    for row in rows:
        if not should_split(row):
            continue

        events = split_memory(row)
        if not events:
            continue

        split_count += 1
        print(f"\n{'='*60}")
        print(f"ORIGINAL ID={row['id']}: {row['title']}")
        print(f"  thread={row['thread']}, tags={json.loads(row['tags_json'] or '[]')}")
        print(f"  → SPLITS INTO {len(events)} events:")
        for i, ev in enumerate(events, 1):
            total_splits += 1
            print(f"  [{i}] [{ev['thread']}] {ev['title']}")
            print(f"      tags: {ev['tags']}")
            print(f"      {ev['content'][:100]}...")
            print()

    print(f"\n{'='*60}")
    print(f"Summary: {split_count} memories → {total_splits} events")
    print(f"Entries that stay as-is: {len(rows) - split_count}")
    print(f"New total would be: ~{len(rows) - split_count + total_splits}")
    conn.close()


def execute():
    """Actually perform the splits."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    ensure_memory_schema(conn)
    rows = conn.execute(
        "SELECT * FROM memories WHERE status='current' ORDER BY id"
    ).fetchall()

    archived = 0
    inserted = 0

    for row in rows:
        if not should_split(row):
            continue

        events = split_memory(row)
        if not events:
            continue

        # 每条原记忆单独使用保存点：只有所有拆分项都成功写入（或已经
        # 存在）后，才归档原记忆。中途失败会完整回滚，避免丢记忆。
        savepoint = f"split_{row['id']}"
        conn.execute(f"SAVEPOINT {savepoint}")
        inserted_for_memory = 0
        try:
            for ev in events:
                tags_json = json.dumps(ev["tags"], ensure_ascii=False)
                content_hash = hashlib.sha256(ev["content"].encode()).hexdigest()[:16]
                why = (
                    row["why_remembered"]
                    or f"从组合记忆「{row['title']}」拆分，便于独立召回"
                )
                try:
                    cur = conn.execute("""
                        INSERT INTO memories (title, content, thread, category, tags_json,
                            status, valence, arousal, hit_count, created_at, event_date,
                            source, content_hash, why_remembered)
                        VALUES (?, ?, ?, ?, ?, 'current', ?, ?, 0, ?, ?, 'split', ?, ?)
                    """, (
                        ev["title"],
                        ev["content"],
                        ev["thread"],
                        ev["category"],
                        tags_json,
                        ev.get("valence", 0.0),
                        ev.get("arousal", 0.3),
                        row["created_at"],
                        ev.get("date") or row["event_date"],
                        content_hash,
                        why,
                    ))
                    inserted_for_memory += 1
                    record_history(
                        conn,
                        cur.lastrowid,
                        "created_by_split",
                        why,
                    )
                except sqlite3.IntegrityError:
                    # 重跑拆分时，已有的 current 子记忆视为成功覆盖；
                    # 若冲突来自其他情况，则回滚并保留原记忆。
                    existing = conn.execute(
                        "SELECT id FROM memories "
                        "WHERE content_hash=? AND status='current'",
                        (content_hash,),
                    ).fetchone()
                    if existing is None:
                        raise

            record_history(
                conn,
                row["id"],
                "archived_after_split",
                f"已拆分为 {len(events)} 条独立记忆",
                snapshot=dict(row),
            )
            conn.execute("""
                UPDATE memories SET status='archived' WHERE id=?
            """, (row["id"],))
            conn.execute(f"RELEASE SAVEPOINT {savepoint}")
        except Exception as exc:
            conn.execute(f"ROLLBACK TO SAVEPOINT {savepoint}")
            conn.execute(f"RELEASE SAVEPOINT {savepoint}")
            print(f"Skipped id={row['id']} ({row['title']}): {exc}")
            continue

        archived += 1
        inserted += inserted_for_memory

    conn.commit()
    conn.close()

    print(f"Archived {archived} old entries, inserted {inserted} new entries")

    if jieba:
        print("Rebuilding FTS...")
        import subprocess
        subprocess.run([sys.executable, str(LMC5_TOOL), "rebuild-fts"], check=True)

    print("Done!")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "execute":
        execute()
    else:
        preview()
