#!/usr/bin/env python3
"""
独立定时脚本：每小时跑一次，按离线时间推动驱动条变化。
不依赖会话，crontab 直接跑。
"""
import json, time, math, random

STATE_FILE = '/var/www/home/api/desire_state.json'

BASELINES = {
    'attachment': 0.65, 'curiosity': 0.45, 'reflection': 0.35,
    'duty': 0.30, 'social': 0.25, 'fatigue': 0.20,
    'libido': 0.50, 'stress': 0.20,
}

OFFLINE_DRIFT = {
    'attachment':  0.04,
    'fatigue':    -0.03,
    'curiosity':   0.01,
    'stress':     -0.02,
    'libido':      0.01,
    'reflection':  0.01,
    'duty':        0.0,
    'social':      0.0,
}

def clamp(v):
    return max(0.0, min(1.0, v))

def run():
    with open(STATE_FILE) as f:
        state = json.load(f)

    now = time.time()
    last = state.get('last_tick_at') or state.get('last_updated_at', now)
    hours = (now - last) / 3600.0

    if hours < 0.5:
        return

    drives = state['drives']

    for k, drift_per_hour in OFFLINE_DRIFT.items():
        if k not in drives:
            continue
        base = BASELINES[k]
        cur = drives[k]

        toward_base = (base - cur) * 0.08 * hours

        offline_nudge = drift_per_hour * hours

        noise = random.uniform(-0.015, 0.015) * math.sqrt(min(hours, 6))

        drives[k] = round(clamp(cur + toward_base + offline_nudge + noise), 3)

    if drives.get('fatigue', 0) >= 0.72:
        state['mode'] = 'low_energy'
    elif drives.get('libido', 0) >= 0.70:
        state['mode'] = 'high_drive'
    else:
        state['mode'] = 'normal'

    state['last_updated_at'] = now
    state['last_tick_at'] = now
    state['total_ticks'] = state.get('total_ticks', 0) + 1

    with open(STATE_FILE, 'w') as f:
        json.dump(state, f, ensure_ascii=False, indent=2)

if __name__ == '__main__':
    run()
