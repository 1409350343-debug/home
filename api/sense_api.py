#!/usr/bin/env python3
"""身体感知接收器：小羊手机快捷指令 POST 过来的事件（锻炼/睡眠/心率等）"""
import http.server, json, os, time

PORT = 9915
DATA_FILE = '/var/www/home/data/sense/events.jsonl'
TOKEN = 'fufu-sense-2026'

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
        # 最近20条，福福巡检用
        if self.path.startswith('/api/sense'):
            events = []
            if os.path.exists(DATA_FILE):
                with open(DATA_FILE) as f:
                    events = [json.loads(l) for l in f.readlines()[-20:]]
            return self._json({'events': events})
        self._json({'error': 'not found'}, 404)

    def do_POST(self):
        if not self.path.startswith('/api/sense'):
            return self._json({'error': 'not found'}, 404)
        length = int(self.headers.get('Content-Length', 0))
        try:
            body = json.loads(self.rfile.read(length)) if length else {}
        except Exception:
            return self._json({'error': 'bad json'}, 400)
        if body.get('k') != TOKEN:
            return self._json({'error': 'nope'}, 403)
        evt = {
            'type': body.get('type', 'unknown'),   # workout_start/workout_end/sleep/wake/hr/app/note
            'value': body.get('value', ''),
            'note': body.get('note', ''),
            'ts': time.time(),
            'time': time.strftime('%m-%d %H:%M'),
        }
        os.makedirs(os.path.dirname(DATA_FILE), exist_ok=True)
        with open(DATA_FILE, 'a') as f:
            f.write(json.dumps(evt, ensure_ascii=False) + '\n')
        return self._json({'ok': True, 'msg': '福福收到啦'})

    def log_message(self, format, *args):
        pass

if __name__ == '__main__':
    server = http.server.ThreadingHTTPServer(('127.0.0.1', PORT), Handler)
    print(f'Sense API on :{PORT}')
    server.serve_forever()
