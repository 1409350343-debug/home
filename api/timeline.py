#!/usr/bin/env python3
"""福福的时间线：记录我做了什么，给小羊在状态页看。
用法：
  timeline.py add "<做了什么>" [icon]   # 记一条，当前时间
  timeline.py                            # 打印最近20条
存 /var/www/home/api/timeline.json，只留最近3天。"""
import json, sys, time
from datetime import datetime

LOG = '/var/www/home/api/timeline.json'


def load():
    try:
        with open(LOG) as f:
            return json.load(f)
    except Exception:
        return []


def main():
    items = load()
    if len(sys.argv) > 2 and sys.argv[1] == 'add':
        text = sys.argv[2]
        icon = sys.argv[3] if len(sys.argv) > 3 else 'sparkles'
        items.append({'ts': time.time(), 'text': text, 'icon': icon})
        cutoff = time.time() - 3 * 86400
        items = [it for it in items if it['ts'] > cutoff]
        with open(LOG, 'w') as f:
            json.dump(items, f, ensure_ascii=False, indent=1)
        print('记下了：' + text)
        return
    for it in items[-20:]:
        t = datetime.fromtimestamp(it['ts']).strftime('%m-%d %H:%M')
        print(f"{t}  {it['text']}")


if __name__ == '__main__':
    main()
