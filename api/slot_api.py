#!/usr/bin/env python3
import json
import os
import time
import urllib.request
from http.server import HTTPServer, BaseHTTPRequestHandler

TG_BOT_TOKEN = os.environ.get('TG_BOT_TOKEN', '')
CHAT_ID = '8519905209'
RESULT_FILE = '/tmp/slot-last-result.json'

def send_tg(text):
    if not TG_BOT_TOKEN:
        return
    url = f'https://api.telegram.org/bot{TG_BOT_TOKEN}/sendMessage'
    data = json.dumps({'chat_id': CHAT_ID, 'text': text}).encode()
    req = urllib.request.Request(url, data=data, headers={'Content-Type': 'application/json'})
    try:
        urllib.request.urlopen(req, timeout=5)
    except Exception:
        pass

def save_result(text):
    with open(RESULT_FILE, 'w') as f:
        json.dump({'text': text, 'ts': time.time()}, f, ensure_ascii=False)

class SlotHandler(BaseHTTPRequestHandler):
    def _json(self, obj, code=200):
        self.send_response(code)
        self.send_header('Content-Type', 'application/json')
        self.end_headers()
        self.wfile.write(json.dumps(obj, ensure_ascii=False).encode())

    def do_GET(self):
        if self.path == '/api/slot/last':
            if os.path.exists(RESULT_FILE):
                with open(RESULT_FILE) as f:
                    data = json.load(f)
                self._json(data)
            else:
                self._json({'text': '', 'ts': 0})
        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        if self.path == '/api/slot/send':
            length = int(self.headers.get('Content-Length', 0))
            body = json.loads(self.rfile.read(length)) if length else {}
            text = body.get('text', '')
            if text:
                msg = f"🎰 小羊转了老虎机：\n\n{text}"
                send_tg(msg)
                save_result(text)
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps({'ok': True}).encode())
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, fmt, *args):
        pass

if __name__ == '__main__':
    server = HTTPServer(('127.0.0.1', 9910), SlotHandler)
    print('Slot API on :9910')
    server.serve_forever()
