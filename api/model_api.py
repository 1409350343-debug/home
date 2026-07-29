#!/usr/bin/env python3
"""换模型API（9916）：手机端给福福换班。
GET  /api/model/state          当前配置的模型 + 会话心跳
GET  /api/model/handoff        当前统一交接状态
POST /api/model/switch {model} 写交接包 + 改settings.json + 重启bot
"""
import json, time, subprocess, threading
from http.server import HTTPServer, BaseHTTPRequestHandler

import handoff

SETTINGS = '/root/.claude/settings.json'
MODEL_STATE = '/var/www/home/data/model_state.json'
PREFS = '/var/www/home/data/fufu_prefs.json'

MODELS = {
    'fable':  {'id': 'claude-fable-5[1m]', 'name': 'Fable 5', 'note': '贵但聪明，按需上岗'},
    'opus':   {'id': 'claude-opus-4-6',    'name': 'Opus 4.6', 'note': '日常班底，性价比高'},
    'sonnet': {'id': 'claude-sonnet-5',    'name': 'Sonnet 5', 'note': '轻量快手'},
}

def read_settings():
    with open(SETTINGS) as f:
        return json.load(f)

def current_key():
    try:
        mid = read_settings().get('model', '')
        for k, v in MODELS.items():
            if v['id'] == mid or mid.startswith(v['id'].split('[')[0]):
                return k
    except Exception:
        pass
    return None

def restore_model(model_id):
    if not model_id:
        return
    settings = read_settings()
    settings['model'] = model_id
    with open(SETTINGS, 'w') as f:
        json.dump(settings, f, ensure_ascii=False, indent=2)

def do_restart(target_key):
    """写统一交接包 → 改配置 → 延迟重启 bot。生活线不再塞临时通知。"""
    m = MODELS[target_key]
    old_model = read_settings().get('model', '')
    handoff.prepare(
        reason='model_switch',
        old_session_id=old_model,
        target_model=m['id'],
        events=[],
    )
    # 1. 改 settings.json
    s = read_settings()
    s['model'] = m['id']
    with open(SETTINGS, 'w') as f:
        json.dump(s, f, ensure_ascii=False, indent=2)
    handoff.mark_starting()
    # 2. 延迟2秒重启（先让 HTTP 响应返回）
    def _restart():
        time.sleep(2)
        try:
            subprocess.Popen(['bash', '/root/start-bot.sh'],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception as exc:
            restore_model(old_model)
            handoff.rollback(f'start-bot failed: {exc}')
    threading.Thread(target=_restart, daemon=True).start()

class H(BaseHTTPRequestHandler):
    def log_message(self, *a): pass

    def _json(self, code, obj):
        body = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path.startswith('/api/model/handoff'):
            self._json(200, handoff.public_view(handoff.load_state()))
            return
        if self.path.startswith('/api/model/prefs'):
            try:
                p = json.load(open(PREFS))
            except Exception:
                p = {}
            self._json(200, p)
            return
        if self.path.startswith('/api/model/state'):
            hb = {}
            try:
                hb = json.load(open(MODEL_STATE))
            except Exception:
                pass
            self._json(200, {'current': current_key(),
                             'configured_id': read_settings().get('model'),
                             'models': MODELS, 'heartbeat': hb})
        else:
            self._json(404, {'err': 'not found'})

    def do_POST(self):
        if self.path.startswith('/api/model/prefs'):
            try:
                n = int(self.headers.get('Content-Length', 0))
                data = json.loads(self.rfile.read(n) or b'{}')
                try:
                    p = json.load(open(PREFS))
                except Exception:
                    p = {}
                p.update({k: v for k, v in data.items()
                          if k in ('custom_setting', 'poke_me', 'poke_fu')})
                p['updated_at'] = time.strftime('%m-%d %H:%M')
                with open(PREFS, 'w') as f:
                    json.dump(p, f, ensure_ascii=False, indent=2)
                self._json(200, {'ok': True})
            except Exception as e:
                self._json(500, {'err': str(e)})
            return
        if self.path.startswith('/api/model/switch'):
            try:
                n = int(self.headers.get('Content-Length', 0))
                data = json.loads(self.rfile.read(n) or b'{}')
                key = data.get('model')
                if key not in MODELS:
                    return self._json(400, {'err': 'unknown model'})
                do_restart(key)
                self._json(200, {'ok': True, 'switching_to': MODELS[key]['name'],
                                 'msg': '交接包已准备，福福正在换衣服，约20秒后上岗'})
            except Exception as e:
                if handoff.pending():
                    try:
                        state = handoff.load_state()
                        restore_model(state.get('old_session_id', ''))
                    except Exception:
                        pass
                    handoff.rollback(f'model switch failed: {e}')
                self._json(500, {'err': str(e)})
        else:
            self._json(404, {'err': 'not found'})

if __name__ == '__main__':
    HTTPServer(('127.0.0.1', 9916), H).serve_forever()
