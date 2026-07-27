#!/usr/bin/env python3
"""15分钟App小抄：压缩events.jsonl最近N分钟的app事件为一行摘要，供巡逻岗快速扫"""
import json, time, sys, os

EVENTS = '/var/www/home/data/sense/events.jsonl'
OUT = '/var/www/home/data/sense/app_digest.txt'
WINDOW = 15 * 60  # 默认15分钟

def digest(window_sec=WINDOW):
    now = time.time()
    cutoff = now - window_sec
    apps = {}  # app_name -> [timestamps]
    other = []  # non-app events in window

    if not os.path.exists(EVENTS):
        return "无感知数据"

    with open(EVENTS) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                evt = json.loads(line)
            except Exception:
                continue
            ts = evt.get('ts', 0)
            if ts < cutoff:
                continue
            etype = evt.get('type', '')
            val = evt.get('value', '')
            if etype == 'app':
                apps.setdefault(val, []).append(ts)
            elif etype in ('sleep', 'workout_start', 'workout_end', 'hr'):
                other.append(f"{etype}:{val}")

    if not apps and not other:
        return f"最近{window_sec//60}分钟无活动"

    parts = []
    for app, timestamps in sorted(apps.items(), key=lambda x: -len(x[1])):
        count = len(timestamps)
        span = max(timestamps) - min(timestamps) if count > 1 else 0
        if span > 60:
            parts.append(f"{app}({count}次,约{int(span/60)}分钟)")
        else:
            parts.append(f"{app}({count}次)")

    if other:
        parts.extend(other)

    summary = " | ".join(parts)

    # 额外：看最近1小时的总app使用（给巡逻岗更长视野）
    hour_cutoff = now - 3600
    hour_apps = {}
    with open(EVENTS) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                evt = json.loads(line)
            except Exception:
                continue
            if evt.get('ts', 0) >= hour_cutoff and evt.get('type') == 'app':
                v = evt.get('value', '')
                hour_apps[v] = hour_apps.get(v, 0) + 1

    hour_part = ""
    if hour_apps:
        top = sorted(hour_apps.items(), key=lambda x: -x[1])
        hour_part = f"\n[近1小时] " + " ".join(f"{a}×{c}" for a, c in top)

    return f"[近{window_sec//60}分钟] {summary}{hour_part}"


if __name__ == '__main__':
    window = int(sys.argv[1]) if len(sys.argv) > 1 else WINDOW
    result = digest(window)
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, 'w') as f:
        f.write(result + '\n')
        f.write(f"生成于 {time.strftime('%H:%M:%S')}\n")
    print(result)
