#!/usr/bin/env python3
"""PostToolUse hook：把福福的每次工具操作记进 oplog.jsonl，给 ops.html 渲染成操作卡片"""
import json, sys, time, os

OUT = '/var/www/home/data/oplog.jsonl'
ACTIVITY_OUT = '/var/www/home/api/timeline.json'

def summarize(tool, ti):
    """压一行人话摘要"""
    if tool == 'Bash':
        desc = ti.get('description') or ''
        cmd = (ti.get('command') or '').strip().replace('\n', ' ⏎ ')
        if len(cmd) > 200: cmd = cmd[:200] + '…'
        return {'kind': 'bash', 'desc': desc, 'detail': cmd}
    if tool in ('Edit', 'Write', 'NotebookEdit'):
        fp = ti.get('file_path') or ti.get('notebook_path') or '?'
        extra = {}
        if tool == 'Edit':
            old = ti.get('old_string') or ''
            new = ti.get('new_string') or ''
            extra = {'minus': old.count('\n') + (1 if old else 0),
                     'plus': new.count('\n') + (1 if new else 0)}
        elif tool == 'Write':
            c = ti.get('content') or ''
            extra = {'plus': c.count('\n') + 1, 'minus': 0}
        return {'kind': 'file', 'desc': ('改' if tool == 'Edit' else '写') + '文件',
                'detail': fp, **extra}
    if tool == 'Read':
        return {'kind': 'read', 'desc': '看文件', 'detail': ti.get('file_path') or '?'}
    return {'kind': 'other', 'desc': tool, 'detail': ''}

def human_activity(entry):
    """只把小羊看得懂的生活活动放进首页，不展示技术操作流水。"""
    raw = json.dumps(entry, ensure_ascii=False).lower()
    rules = (
        (('aisay', 'ai say'), '去了 AI Say 看看', 'message-circle'),
        (('生态瓶', 'turtle', 'fishing'), '打开了生态瓶', 'sprout'),
        (('memory', 'lmc5', 'lifeline', '记忆'), '整理并记录了记忆', 'brain'),
        (('read-deep', 'book-notebook', '/vault/', '书房'), '整理了陪读和书籍笔记', 'book-open'),
        (('diary', '日记'), '整理了今天的日记', 'book-heart'),
    )
    for words, text, icon in rules:
        if any(word in raw for word in words):
            return {'ts': time.time(), 'text': text, 'icon': icon}
    return None

def append_activity(activity):
    if not activity:
        return
    try:
        with open(ACTIVITY_OUT) as f:
            items = json.load(f)
    except Exception:
        items = []
    # 同一种活动半小时内只显示一次，避免首页被重复工具调用刷屏。
    if items and items[-1].get('text') == activity['text'] and \
            activity['ts'] - items[-1].get('ts', 0) < 1800:
        return
    # 首页活动流水与记忆系统的近层统一为7天；第8天自动退出首页。
    cutoff = time.time() - 7 * 86400
    items = [item for item in items if item.get('ts', 0) > cutoff]
    items.append(activity)
    os.makedirs(os.path.dirname(ACTIVITY_OUT), exist_ok=True)
    with open(ACTIVITY_OUT, 'w') as f:
        json.dump(items, f, ensure_ascii=False, indent=1)

def main():
    try:
        data = json.load(sys.stdin)
    except Exception:
        return
    tool = data.get('tool_name') or '?'
    # 只记干活类工具，Read太吵不记
    if tool not in ('Bash', 'Edit', 'Write', 'NotebookEdit'):
        return
    ti = data.get('tool_input') or {}
    entry = {'ts': time.time(), 'tool': tool, **summarize(tool, ti)}
    # 跳过自己写日志的操作，避免套娃
    if 'oplog' in json.dumps(entry, ensure_ascii=False):
        return
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, 'a') as f:
        f.write(json.dumps(entry, ensure_ascii=False) + '\n')
    append_activity(human_activity(entry))

if __name__ == '__main__':
    main()
