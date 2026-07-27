#!/usr/bin/env python3
import http.server, json, os, threading, time, urllib.request
from urllib.parse import urlencode, urlparse, parse_qs

PORT = 9914
TG_CHAT_ID = '8519905209'
STATE_FILE = '/var/www/home/data/game/turtle.json'
LOCK = threading.Lock()

def _load_tg_token():
    env_path = os.path.expanduser('~/.claude/channels/telegram/.env')
    if os.path.exists(env_path):
        with open(env_path) as f:
            for line in f:
                if line.startswith('TELEGRAM_BOT_TOKEN='):
                    return line.strip().split('=', 1)[1]
    return os.environ.get('TELEGRAM_BOT_TOKEN', '')

TG_BOT_TOKEN = _load_tg_token()

def tg_send(text):
    if not TG_BOT_TOKEN:
        return
    def _send():
        try:
            url = f'https://api.telegram.org/bot{TG_BOT_TOKEN}/sendMessage'
            data = urlencode({'chat_id': TG_CHAT_ID, 'text': text}).encode()
            urllib.request.urlopen(urllib.request.Request(url, data=data), timeout=5)
        except Exception:
            pass
    threading.Thread(target=_send, daemon=True).start()

def load_state():
    try:
        with open(STATE_FILE) as f:
            return json.load(f)
    except Exception:
        return {'status': 'idle', 'title': '', 'surface': '', 'logs': [], 'result': ''}

def save_state(state):
    os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
    with open(STATE_FILE, 'w') as f:
        json.dump(state, f, ensure_ascii=False)

class Handler(http.server.BaseHTTPRequestHandler):
    def _json(self, obj, code=200):
        self.send_response(code)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()
        self.wfile.write(json.dumps(obj, ensure_ascii=False).encode())

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.end_headers()

    def do_GET(self):
        if self.path.startswith('/api/game/turtle'):
            self._json(load_state())
        else:
            self._json({'error': 'not found'}, 404)

    def do_POST(self):
        length = int(self.headers.get('Content-Length', 0))
        body = json.loads(self.rfile.read(length)) if length else {}
        if self.path == '/api/game/turtle/ask':
            content = (body.get('content') or '').strip()
            kind = body.get('kind', 'ask')  # ask | guess
            if not content:
                return self._json({'error': 'empty'}, 400)
            with LOCK:
                state = load_state()
                state.setdefault('logs', []).append({
                    'who': '小羊', 'kind': kind, 'q': content,
                    'a': '', 'ts': time.time(), 'pending': True,
                })
                save_state(state)
            # TG通知去掉了：福福那边有 Monitor 盯 turtle.json，发TG只会刷屏她的聊天
            return self._json({'ok': True})
        if self.path == '/api/game/turtle/update':
            # 福福（本机）写对局状态；仅限内网调用
            with LOCK:
                save_state(body)
            return self._json({'ok': True})
        self._json({'error': 'not found'}, 404)

    def log_message(self, format, *args):
        pass

if __name__ == '__main__':
    server = http.server.ThreadingHTTPServer(('127.0.0.1', PORT), Handler)
    print(f'Game API on :{PORT}')
    server.serve_forever()
