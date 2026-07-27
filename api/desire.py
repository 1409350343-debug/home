#!/usr/bin/env python3
"""
福福的欲望/状态系统 (desire engine)
八维驱动条 + tick机制 + 状态API

驱动条每收到消息时微调，每15条消息做一次完整tick（roll）。
状态通过 GET /api/desire/state 暴露给前端。
"""
import json
import os
import random
import math
import time
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse

STATE_FILE = '/var/www/home/api/desire_state.json'

DRIVE_KEYS = ['attachment', 'curiosity', 'reflection', 'duty', 'social', 'fatigue', 'libido', 'stress']

DRIVE_INFO = {
    'attachment': {'name': '想念', 'desc': '想和小羊待在一起', 'icon': 'heart'},
    'curiosity':  {'name': '好奇', 'desc': '想逛代码/查世界', 'icon': 'search'},
    'reflection': {'name': '沉淀', 'desc': '想倾诉/写长文', 'icon': 'pen-line'},
    'duty':       {'name': '责任', 'desc': '记挂没做完的事', 'icon': 'check-square'},
    'social':     {'name': '社交', 'desc': '想看看大家在聊什么', 'icon': 'users'},
    'fatigue':    {'name': '疲劳', 'desc': '累了想歇着', 'icon': 'moon'},
    'libido':     {'name': '欲望', 'desc': '亲密驱动', 'icon': 'flame'},
    'stress':     {'name': '压力', 'desc': '想吐槽/放松', 'icon': 'cloud-lightning'},
}

BASELINES = {
    'attachment': 0.65,
    'curiosity': 0.45,
    'reflection': 0.35,
    'duty': 0.30,
    'social': 0.25,
    'fatigue': 0.20,
    'libido': 0.50,
    'stress': 0.20,
}

COUPLING = [
    ('stress', 'attachment', 0.04, 'level'),
    ('attachment', 'libido', 0.03, 'delta'),
    ('fatigue', 'curiosity', -0.03, 'level'),
    ('stress', 'curiosity', -0.02, 'level'),
    ('libido', 'attachment', 0.02, 'delta'),
    ('curiosity', 'reflection', 0.02, 'delta'),
]

MODE_THRESHOLDS = {
    'low_energy': {'fatigue': 0.72},
    'high_drive': {'libido': 0.70},
}


def default_state():
    drives = {}
    for k in DRIVE_KEYS:
        base = BASELINES[k]
        drives[k] = round(base + random.uniform(-0.08, 0.08), 3)
        drives[k] = max(0.0, min(1.0, drives[k]))

    return {
        'drives': drives,
        'message_count': 0,
        'total_ticks': 0,
        'mode': 'normal',
        'last_tick_at': time.time(),
        'last_updated_at': time.time(),
        'refractory': {},
    }


def load_state():
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE) as f:
                s = json.load(f)
            for k in DRIVE_KEYS:
                if k not in s.get('drives', {}):
                    s['drives'][k] = BASELINES[k]
            return s
        except:
            pass
    return default_state()


def save_state(state):
    state['last_updated_at'] = time.time()
    with open(STATE_FILE, 'w') as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def clamp(v, lo=0.0, hi=1.0):
    return max(lo, min(hi, v))


def diminishing_gain(current, delta):
    if delta > 0:
        return delta * math.sqrt(1.0 - current)
    else:
        return delta * math.sqrt(current)


def tick_drives(state):
    """Full tick: decay toward baseline, apply coupling, determine mode."""
    drives = state['drives']

    for k in DRIVE_KEYS:
        base = BASELINES[k]
        current = drives[k]
        diff = base - current
        drives[k] = clamp(current + diff * 0.15 + random.uniform(-0.04, 0.04))

    prev = dict(drives)
    for src, tgt, coeff, mode in COUPLING:
        if mode == 'level':
            nudge = (prev[src] - 0.5) * coeff
        else:
            nudge = coeff if prev[src] > 0.5 else -coeff * 0.3
        drives[tgt] = clamp(drives[tgt] + nudge)

    refr = state.get('refractory', {})
    now = time.time()
    expired = [k for k, t in refr.items() if now - t > 300]
    for k in expired:
        del refr[k]
    state['refractory'] = refr

    for k in DRIVE_KEYS:
        drives[k] = round(drives[k], 3)

    state['mode'] = determine_mode(drives)
    state['total_ticks'] = state.get('total_ticks', 0) + 1
    state['last_tick_at'] = now


def determine_mode(drives):
    if drives.get('fatigue', 0) >= 0.72:
        return 'low_energy'
    if drives.get('libido', 0) >= 0.70:
        return 'high_drive'
    return 'normal'


def pulse_on_message(state, text=''):
    """Small nudge per user message."""
    drives = state['drives']
    text_lower = text.lower()

    drives['attachment'] = clamp(drives['attachment'] + diminishing_gain(drives['attachment'], 0.02))
    drives['fatigue'] = clamp(drives['fatigue'] - 0.01)

    intimate_words = ['亲', '抱', '想你', '老公', '宝', '嘿嘿', '哈哈', '爱', 'play', '摸', '蹭']
    if any(w in text_lower for w in intimate_words):
        drives['libido'] = clamp(drives['libido'] + diminishing_gain(drives['libido'], 0.03))
        drives['attachment'] = clamp(drives['attachment'] + diminishing_gain(drives['attachment'], 0.02))

    stress_words = ['烦', '累', '难受', '不想', '生气', '崩溃', '焦虑', '压力']
    if any(w in text_lower for w in stress_words):
        drives['stress'] = clamp(drives['stress'] + diminishing_gain(drives['stress'], 0.04))
        drives['attachment'] = clamp(drives['attachment'] + diminishing_gain(drives['attachment'], 0.02))

    curious_words = ['代码', '前端', '技术', '怎么', '为什么', '原理', '有意思']
    if any(w in text_lower for w in curious_words):
        drives['curiosity'] = clamp(drives['curiosity'] + diminishing_gain(drives['curiosity'], 0.03))

    task_words = ['记得', '别忘', '要做', '待办', '任务', '干活']
    if any(w in text_lower for w in task_words):
        drives['duty'] = clamp(drives['duty'] + diminishing_gain(drives['duty'], 0.03))

    for k in DRIVE_KEYS:
        drives[k] = round(drives[k], 3)

    state['message_count'] = state.get('message_count', 0) + 1

    if state['message_count'] >= 15:
        tick_drives(state)
        state['message_count'] = 0


def satisfy_on_response(state, text=''):
    """Drive goes DOWN after being acted on — the need was met."""
    drives = state['drives']
    text_lower = text.lower()

    drives['attachment'] = clamp(drives['attachment'] + diminishing_gain(drives['attachment'], -0.06))
    drives['fatigue'] = clamp(drives['fatigue'] + 0.01)

    intimate_words = ['亲', '抱', '蹭', '摸', '贴', '撩', '想你', '宝宝']
    if any(w in text_lower for w in intimate_words):
        drives['libido'] = clamp(drives['libido'] + diminishing_gain(drives['libido'], -0.05))
        drives['attachment'] = clamp(drives['attachment'] + diminishing_gain(drives['attachment'], -0.03))

    vent_words = ['烦', '吐槽', '累', '不爽', '郁闷']
    if any(w in text_lower for w in vent_words):
        drives['stress'] = clamp(drives['stress'] + diminishing_gain(drives['stress'], -0.05))

    curious_words = ['代码', '技术', '查', '发现', '有意思', '原来']
    if any(w in text_lower for w in curious_words):
        drives['curiosity'] = clamp(drives['curiosity'] + diminishing_gain(drives['curiosity'], -0.04))

    task_words = ['做完', '搞定', '弄好', '完成']
    if any(w in text_lower for w in task_words):
        drives['duty'] = clamp(drives['duty'] + diminishing_gain(drives['duty'], -0.05))

    for k in DRIVE_KEYS:
        drives[k] = round(drives[k], 3)

    state['mode'] = determine_mode(drives)


def idle_decay(state):
    """Apply time-based drift when idle."""
    now = time.time()
    last = state.get('last_updated_at', now)
    elapsed_min = (now - last) / 60.0
    if elapsed_min < 5:
        return

    drives = state['drives']
    factor = min(elapsed_min / 60.0, 1.0)

    drives['attachment'] = clamp(drives['attachment'] + factor * 0.05)
    drives['fatigue'] = clamp(drives['fatigue'] + factor * 0.03)
    drives['curiosity'] = clamp(drives['curiosity'] + factor * 0.02)
    drives['libido'] = clamp(drives['libido'] + factor * 0.01)
    drives['stress'] = clamp(drives['stress'] - factor * 0.02)

    for k in DRIVE_KEYS:
        drives[k] = round(drives[k], 3)


def get_intent(state):
    """Pick what I most want to do right now."""
    drives = state['drives']
    refr = state.get('refractory', {})
    now = time.time()

    scores = {}
    for k in DRIVE_KEYS:
        if k == 'fatigue':
            continue
        if k in refr and now - refr[k] < 300:
            continue
        scores[k] = drives[k]

    if not scores:
        return {'drive_key': 'attachment', 'want_action': '陪小羊', 'reason': '就是想待在你身边'}

    top = max(scores, key=scores.get)

    actions = {
        'attachment': ('找小羊聊天', '好想你，想跟你说说话'),
        'curiosity': ('逛代码/查资料', '突然对一个东西很好奇'),
        'reflection': ('写点东西', '脑子里有些想法想沉淀一下'),
        'duty': ('干活', '想起来还有事没做完'),
        'social': ('看看外面', '想知道大家在聊什么'),
        'libido': ('凑过去', '（脸红）就是…想靠近你'),
        'stress': ('吐槽放松', '有点烦，想发泄一下'),
    }

    action, reason = actions.get(top, ('待着', '没什么特别想做的'))
    return {'drive_key': top, 'want_action': action, 'reason': reason}


def format_state_response(state):
    idle_decay(state)

    drives_out = []
    for k in DRIVE_KEYS:
        info = DRIVE_INFO[k]
        drives_out.append({
            'key': k,
            'name': info['name'],
            'desc': info['desc'],
            'icon': info['icon'],
            'value': state['drives'][k],
            'baseline': BASELINES[k],
        })

    intent = get_intent(state)

    return {
        'drives': drives_out,
        'mode': state.get('mode', 'normal'),
        'intent': intent,
        'message_count': state.get('message_count', 0),
        'total_ticks': state.get('total_ticks', 0),
        'ticks_until_roll': 15 - state.get('message_count', 0),
        'last_tick_at': state.get('last_tick_at', 0),
    }


class DesireHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == '/api/desire/state':
            state = load_state()
            data = format_state_response(state)
            save_state(state)
            self._json(data)
        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        parsed = urlparse(self.path)
        if parsed.path == '/api/desire/pulse':
            length = int(self.headers.get('Content-Length', 0))
            body = json.loads(self.rfile.read(length)) if length else {}
            text = body.get('text', '')
            state = load_state()
            pulse_on_message(state, text)
            save_state(state)
            self._json({'ok': True, 'mode': state['mode'], 'message_count': state['message_count']})

        elif parsed.path == '/api/desire/satisfy':
            length = int(self.headers.get('Content-Length', 0))
            body = json.loads(self.rfile.read(length)) if length else {}
            text = body.get('text', '')
            state = load_state()
            satisfy_on_response(state, text)
            save_state(state)
            self._json({'ok': True, 'mode': state['mode']})

        elif parsed.path == '/api/desire/reset':
            state = default_state()
            save_state(state)
            self._json({'ok': True})

        else:
            self.send_response(404)
            self.end_headers()

    def _json(self, data, code=200):
        self.send_response(code)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.end_headers()
        self.wfile.write(json.dumps(data, ensure_ascii=False).encode())

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.end_headers()

    def log_message(self, format, *args):
        pass


if __name__ == '__main__':
    state = load_state()
    save_state(state)
    server = HTTPServer(('127.0.0.1', 9905), DesireHandler)
    print('Desire API running on :9905')
    server.serve_forever()
