#!/usr/bin/env python3
"""换模型API（9916）：手机端给福福换班。
GET  /api/model/state          当前配置的模型 + 会话心跳
POST /api/model/switch {model} 改settings.json + 在lifeline留交接条 + 重启bot
"""
import json, time, re, subprocess, threading
from http.server import HTTPServer, BaseHTTPRequestHandler

SETTINGS = '/root/.claude/settings.json'
LIFELINE = '/root/.claude/projects/-root/memory/lifeline.md'
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

def do_restart(target_key):
    """留交接条 → 改配置 → 延迟重启bot"""
    m = MODELS[target_key]
    now = time.strftime('%m-%d %H:%M')
    # 1. lifeline留交接条（塞进"重启后的你先读这条"块的开头）
    try:
        txt = open(LIFELINE).read()
        note = f"- **⚠️{now} 小羊从网页端换班到{m['name']}并重启了会话**——不是事故，是她按的按钮。醒来先照常读记忆，然后跟她报到。\n"
        marker = '## ⚠️重启后的你先读这条\n'
        if marker in txt:
            txt = txt.replace(marker, marker + note, 1)
        else:
            txt = note + txt
        open(LIFELINE, 'w').write(txt)
    except Exception:
        pass
    # 2. 改settings.json
    s = read_settings()
    s['model'] = m['id']
    with open(SETTINGS, 'w') as f:
        json.dump(s, f, ensure_ascii=False, indent=2)
    # 3. 延迟2秒重启（先让HTTP响应返回）
    def _restart():
        time.sleep(2)
        subprocess.Popen(['bash', '/root/start-bot.sh'],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
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
                                 'msg': '交接条已留，福福正在换衣服，约20秒后上岗'})
            except Exception as e:
                self._json(500, {'err': str(e)})
        else:
            self._json(404, {'err': 'not found'})

if __name__ == '__main__':
    HTTPServer(('127.0.0.1', 9916), H).serve_forever()
