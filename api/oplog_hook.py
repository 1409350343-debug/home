#!/usr/bin/env python3
"""PostToolUse hook：把福福的每次工具操作记进 oplog.jsonl，给 ops.html 渲染成操作卡片"""
import json, sys, time, os

OUT = '/var/www/home/data/oplog.jsonl'

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

if __name__ == '__main__':
    main()
