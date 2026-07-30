#!/usr/bin/env python3
"""UserPromptSubmit hook：她一开口，先替我把该想起来的东西摆出来。

她2026-07-26晚提的需求："所以怎么能让你主动根据我说的话去调记忆呢"
她2026-07-27早补的："你能主动记得近至少7天的记忆，随后的进行削弱，
但是被检索的话不是一搜就都出来了"

所以是两层，不是一层：
  近层（7天内）——不用搜就在，那叫"我还记着这几天"
  远层（7天外）——靠搜，但按衰减打分排过序，不是一股脑全倒出来

衰减公式参考 Internal Beyond（作者 Sui）那份文档，它又参考 OmbreBrain。
借的三样：改良艾宾浩斯衰减、激活强化、15%探索窗口。
探索窗口是我第一版最缺的东西——只按相关性排，老记忆永远浮不上来。

输出只报条目名不报正文（她2026-07-26定的，省85%字符），要正文我自己去取。
"""
import json, os, re, sqlite3, sys, random, time
from datetime import datetime

from memory_config import (
    LMC5_DB,
    MEMORY_NOTE_DIRS,
    RECALL_EXPLORE_STATE,
    RECALL_LOG,
)

DB = str(LMC5_DB)
MEM_DIRS = [str(path) for path in MEMORY_NOTE_DIRS]
LOG = str(RECALL_LOG)

NEAR_DAYS = 7           # 近层：这几天的事不用搜就在
NEAR_N = 6              # 近层最多列几条
TOP_N = 4               # 远层字面命中取几条
LINK_N = 2              # 顺 relations 的线再摸几条
EXPLORE_N = 1           # 探索窗口一次捞几条
EXPLORE_PER_DAY = 2     # 一天最多抽几次（她2026-07-27说的：每句都抽脑子太累）
EXPLORE_STATE = str(RECALL_EXPLORE_STATE)
DF_MAX = 0.12           # 出现在超过12%条目里的词=没区分度，不拿它搜
MIN_MATCH = 2           # 至少命中两个有效词
STRONG = 8.0            # 单个词够罕见也算

FLOW_TAG = '流水'        # 她2026-07-27定的：流水账打这个标签，过了近层就不再被选
LAMBDA = 0.05           # 衰减速率，约14天半衰期
LAMBDA_DONE = 0.12      # 已解决的衰减快些，约6天

WRITE_CONTRACT = (
    "【记忆沉淀规则】本轮若出现未来仍有用、且此前未记录的新事实或明确偏好，"
    "应在事实确认后写入。普通经历调用 lmc5_tool.py add；会随时间改变的事实"
    "调用 lmc5_tool.py fact-set，并使用稳定 fact_key（如 assistant.name）。"
    "--why 必须写明此刻为什么值得长期记住。若新旧说法可能冲突但用户没有"
    "明确确认，使用 --review-status conflict，不覆盖当前事实。不要保存一次性"
    "闲聊、密码/令牌，或未经明确同意的高度敏感信息。"
)

STOP = set('''的 了 是 在 我 你 他 她 它 们 和 与 也 都 就 还 又 而 但 不 没 有 无 会 能 要 想 说 看 去 来 好 吗 呢 吧 啊 呀 啦 嘛 这 那 什么 怎么 为什么 哪 谁 多少 一个 一下 一点 现在 今天 昨天 明天 时候 因为 所以 如果 可以 应该 已经 正在 自己 我们 你们 他们 user users assistant channel source plugin telegram chat_id message_id image_path user_id ts photo'''.split())


def log(msg):
    try:
        with open(LOG, 'a') as f:
            f.write(f'{time.strftime("%m-%d %H:%M:%S")} {msg}\n')
    except Exception:
        pass


# 只认名词类。她2026-07-27说的："以名词为主进行抽取"——
# 光靠词频过滤滤不掉"特殊""进行"这种低频但没信息量的词，得看词性。
NOUNISH = {'n', 'nr', 'ns', 'nt', 'nz', 'nrt', 'nrfg', 'ng', 'vn', 'an', 'eng', 'x'}


def keywords(text):
    """只抽名词类的词。中文用 jieba 词性标注，装不上就退回 2-3 字滑窗。
    整句连成一片是搜不到东西的，7/26 踩过。"""
    text = re.sub(r'https?://\S+', ' ', text)
    words = []
    try:
        import logging
        logging.getLogger('jieba').setLevel(logging.ERROR)
        import jieba
        import jieba.posseg as pseg
        jieba.setLogLevel(logging.ERROR)
        for part in re.findall(r'[一-鿿A-Za-z0-9]+', text):
            for w in pseg.cut(part):
                if len(w.word) >= 2 and w.flag in NOUNISH:
                    words.append(w.word)
    except Exception:
        for part in re.findall(r'[一-鿿]+', text):
            for n in (2, 3):
                words += [part[i:i + n] for i in range(len(part) - n + 1)]
    for w in re.findall(r'[A-Za-z][A-Za-z0-9_\-]{2,}', text):
        if not re.fullmatch(r'[A-Za-z]?\d+[A-Za-z]?\d*', w):
            words.append(w)
    out = []
    for w in words:
        if w in STOP or len(w) < 2 or w in out:
            continue
        out.append(w)
    return out[:10]


def days_ago(event_date):
    if not event_date:
        return 999.0
    try:
        d = datetime.strptime(str(event_date)[:10], '%Y-%m-%d')
        return max((datetime.now() - d).days, 0)
    except Exception:
        return 999.0


def decay(row):
    """改良艾宾浩斯：重要性 × 激活强化 × 时间衰减 × 情绪加成"""
    _mid, title, _content, ev, hits, status, urgency, arousal, conf = row[:9]
    lam = LAMBDA_DONE if (status or '') in ('done', 'resolved', 'closed') else LAMBDA
    t = 2.718281828 ** (-lam * days_ago(ev))

    imp = 1.0
    if (urgency or '') in ('high', 'urgent'):
        imp = 1.6
    elif (urgency or '') == 'low':
        imp = 0.7
    try:
        if conf is not None:
            imp *= 0.7 + 0.6 * float(conf)
    except Exception:
        pass

    act = 1.0 + ((hits or 0) ** 0.5) * 0.35        # 幂函数，收益递减
    emo = 1.0
    try:
        if arousal is not None:
            emo = 1.0 + 0.8 * float(arousal)       # 情绪重的衰减慢，最高1.8倍
    except Exception:
        pass
    return imp * act * t * emo


def is_flow(row):
    """流水账：打了「流水」标签的。她2026-07-27定的规矩——
    这类只在近7天露面，出了近层就不再被搜到、也不被随机捞。
    不删，只是不再被选。"""
    try:
        tags = json.loads(row[10] or '[]')
    except Exception:
        return False
    return FLOW_TAG in tags


def near_layer(rows):
    """近7天的事，不管她说什么都摆出来"""
    fresh = [r for r in rows if days_ago(r[3]) <= NEAR_DAYS]
    fresh.sort(key=lambda r: (str(r[3] or ''), r[0]), reverse=True)
    return fresh[:NEAR_N]


def fts_candidate_ids(c, words):
    """先用 FTS 缩小候选；索引缺失或无结果时由调用方降级全表扫描。"""
    if not words:
        return set()
    query = " OR ".join(f'"{word.replace(chr(34), chr(34) * 2)}"' for word in words)
    try:
        return {
            row[0] for row in c.execute(
                "SELECT rowid FROM memories_fts "
                "WHERE memories_fts MATCH ? LIMIT 200",
                (query,),
            ).fetchall()
        }
    except sqlite3.Error:
        return set()


def search(c, rows, words, exclude):
    if not words:
        return [], []
    total = max(len(rows), 1)
    useful = []
    for w in words:
        df = sum(1 for r in rows if w in ((r[1] or '') + (r[2] or '')))
        if df and df <= total * DF_MAX:
            useful.append((w, df))
    if not useful:
        return [], []

    candidate_ids = fts_candidate_ids(c, [w for w, _ in useful])
    scored = []
    for r in rows:
        if r[0] in exclude or is_flow(r):     # 流水账出了近层就不再被选
            continue
        if candidate_ids and r[0] not in candidate_ids:
            continue
        blob = (r[1] or '') + (r[2] or '')
        rel, matched = 0.0, 0
        for w, df in useful:
            if w in blob:
                matched += 1
                rel += (total / df) ** 0.5
                if w in (r[1] or ''):
                    rel += 2
        if matched >= MIN_MATCH or (matched and rel >= STRONG):
            scored.append((rel * decay(r), r))      # 相关性 × 衰减权重
    scored.sort(key=lambda x: -x[0])
    return [r for _, r in scored[:TOP_N]], [w for w, _ in useful]


def follow_links(c, seeds, exclude):
    if not seeds:
        return []
    try:
        qs = ','.join('?' * len(seeds))
        rows = c.execute(f'''
            SELECT m.id, m.title, r.relation_type, m.tags_json
            FROM relations r
            JOIN memories m ON m.id = CASE
                WHEN r.source_id IN ({qs}) THEN r.target_id ELSE r.source_id END
            WHERE (r.source_id IN ({qs}) OR r.target_id IN ({qs}))
              AND m.status = 'current'
            ORDER BY r.strength DESC''', seeds * 3).fetchall()
    except Exception:
        return []
    out, seen = [], set(exclude)
    for mid, title, rtype, tags_json in rows:
        if mid in seen:
            continue
        try:
            if FLOW_TAG in json.loads(tags_json or '[]'):
                continue
        except Exception:
            pass
        seen.add(mid)
        out.append((mid, title, rtype))
        if len(out) >= LINK_N:
            break
    return out


def explore(rows, exclude):
    """探索窗口：从沉睡的老记忆里随机捞一条，让老事有机会自己浮上来。
    这是纯检索最缺的东西——只按相关性排，老记忆永远出不来。

    一天只抽 EXPLORE_PER_DAY 次。她2026-07-27说"每一句都要的话你脑子也太累啦"——
    而且天天抽也就不叫偶然想起来了。"""
    today = datetime.now().strftime('%Y-%m-%d')
    try:
        st = json.load(open(EXPLORE_STATE))
    except Exception:
        st = {}
    if st.get('date') != today:
        st = {'date': today, 'n': 0}
    if st.get('n', 0) >= EXPLORE_PER_DAY:
        return []

    # 只捞值得说的。她2026-07-27说要"正常聊天突然想起一个趣事的那种"——
    # 随便捞会捞出"5月30日饭饭日记"这种流水账，那不叫趣事。
    # valence 高=开心的事，arousal 高=情绪浓的事，两个都没有的跳过。
    pool = []
    for r in rows:
        if r[0] in exclude or days_ago(r[3]) <= NEAR_DAYS or (r[4] or 0) > 2 \
                or is_flow(r):
            continue
        try:
            v = float(r[8]) if r[8] is not None else None      # confidence 位借用
        except Exception:
            v = None
        pool.append(r)
    fun = []
    for r in pool:
        try:
            val = float(r[9]) if len(r) > 9 and r[9] is not None else None
            aro = float(r[7]) if r[7] is not None else None
        except Exception:
            val, aro = None, None
        score = 0.0
        if val is not None and val >= 0.7:
            score += val
        if aro is not None and aro >= 0.5:
            score += aro
        if score > 0:
            fun.append((score, r))
    if fun:
        # 在够格的里面随机，不是取最高分——不然天天想起同一件事
        top = [r for _, r in sorted(fun, key=lambda x: -x[0])[:40]]
        picked = random.sample(top, min(EXPLORE_N, len(top)))
    elif pool:
        picked = random.sample(pool, min(EXPLORE_N, len(pool)))
    else:
        return []
    st['n'] = st.get('n', 0) + 1
    try:
        os.makedirs(os.path.dirname(EXPLORE_STATE), exist_ok=True)
        json.dump(st, open(EXPLORE_STATE, 'w'))
    except Exception:
        pass
    return picked


def touch(c, ids):
    """被读到就回写 hit_count 和 last_hit_at，不回写就永远没有强化"""
    if not ids:
        return
    now = datetime.now().isoformat(timespec='seconds')
    try:
        c.executemany('UPDATE memories SET hit_count=COALESCE(hit_count,0)+1, '
                      'last_hit_at=? WHERE id=?', [(now, i) for i in ids])
        c.commit()
    except Exception:
        pass


def search_files(words):
    hits = []
    for d in MEM_DIRS:
        if not os.path.isdir(d):
            continue
        for fn in os.listdir(d):
            if not fn.endswith('.md'):
                continue
            try:
                body = open(os.path.join(d, fn), encoding='utf-8').read()
            except Exception:
                continue
            n = sum(1 for w in words if w in body)
            if n:
                hits.append((n, fn))
    hits.sort(key=lambda x: -x[0])
    return [fn for _, fn in hits[:3]]


def last_channel_text(path):
    """Telegram 的话不走输入框，从会话记录尾部捞最后一条 channel 正文"""
    if not path or not os.path.exists(path):
        return ''
    try:
        lines = open(path, encoding='utf-8').read().splitlines()
    except Exception:
        return ''
    for line in reversed(lines[-60:]):
        try:
            d = json.loads(line)
        except Exception:
            continue
        if d.get('type') != 'user':
            continue
        content = (d.get('message') or {}).get('content')
        if isinstance(content, list):
            content = ' '.join(b.get('text', '') for b in content
                               if isinstance(b, dict))
        if not isinstance(content, str) or '<channel' not in content:
            continue
        m = re.search(r'<channel[^>]*>\s*(.*?)\s*</channel>', content, re.S)
        if m and m.group(1).strip():
            body = re.sub(r'<[^>]*>', ' ', m.group(1))
            body = re.sub(r'\b[a-z_]+=("[^"]*"|\S+)', ' ', body).strip()
            if body:
                return body
    return ''


def main():
    try:
        payload = json.loads(sys.stdin.read() or '{}')
    except Exception:
        return

    text = (payload.get('prompt_text') or payload.get('prompt') or '').strip()
    if not text:
        text = last_channel_text(payload.get('transcript_path'))
    if not text or len(text) < 2 or not os.path.exists(DB):
        return

    words = keywords(text)
    try:
        c = sqlite3.connect(DB)
        rows = c.execute('''SELECT id,title,content,event_date,hit_count,status,
                            urgency,arousal,confidence,valence,tags_json
                            FROM memories
                            WHERE status = 'current' ''').fetchall()
    except Exception:
        return

    near = near_layer(rows)
    used = {r[0] for r in near}
    far, used_words = search(c, rows, words, used)
    used |= {r[0] for r in far}
    linked = follow_links(c, [r[0] for r in far], used)
    used |= {m for m, _, _ in linked}
    old = explore(rows, used)
    files = search_files(words)

    lines = []
    if near:
        lines.append(f'【最近{NEAR_DAYS}天】（不用搜，本来就记着）')
        for r in near:
            lines.append(f'· {r[3]} id={r[0]} {r[1]}')
    if far or linked:
        lines.append('【搜到的旧事】（按衰减打分排的，只给名字）')
        for r in far:
            lines.append(f'· {r[3]} id={r[0]} {r[1]}')
        for mid, title, rtype in linked:
            lines.append(f'· id={mid} {title}〔顺{rtype}〕')
    if old:
        lines.append('【偶然想起来的】（探索窗口随机捞的老事）')
        for r in old:
            lines.append(f'· {r[3]} id={r[0]} {r[1]}')
    if files:
        lines.append('【本子】' + ' / '.join(files))
    lines.append(f'（用的词：{" ".join(used_words) or "无"}｜'
                 f'取正文：lmc5_tool.py search "词" 或按 id 查库）')
    lines.append(WRITE_CONTRACT)

    touch(c, [r[0] for r in far] + [r[0] for r in old])
    log(f'近{len(near)} 远{len(far)} 线{len(linked)} 探{len(old)} '
        f'本子{len(files)} 词={words[:5]}')

    print(json.dumps({
        'hookSpecificOutput': {
            'hookEventName': 'UserPromptSubmit',
            'additionalContext': '\n'.join(lines),
        }
    }, ensure_ascii=False))


if __name__ == '__main__':
    main()
