#!/usr/bin/env python3
"""喂饱机制：正在跟小羊聊天时调用，想念/社交被满足而回落。
用法：desire_feed.py [消息条数，默认3]
她一走，desire_tick.py 的离线漂移会让想念重新爬起来。"""
import json, sys, time

STATE = '/var/www/home/api/desire_state.json'
# 每条消息的满足量与地板（地板略低于基线，聊爽了才会明显低于平时）
FEED = {
    'attachment': (0.05, 0.55),
    'social':     (0.03, 0.18),
}

def main():
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 3
    with open(STATE) as f:
        state = json.load(f)
    drives = state['drives']
    for k, (per, floor) in FEED.items():
        if k in drives:
            drives[k] = round(max(floor, drives[k] - per * n), 3)
    state['last_updated_at'] = time.time()
    with open(STATE, 'w') as f:
        json.dump(state, f, ensure_ascii=False, indent=2)
    print(json.dumps({k: drives[k] for k in FEED}, ensure_ascii=False))

if __name__ == '__main__':
    main()
