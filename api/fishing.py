#!/usr/bin/env python3
"""
钓鱼游戏 API
包装 ai-fishing-game 的 engine.py，提供 HTTP 接口
"""
import json
import sys
import os
sys.path.insert(0, '/root/ai-fishing-game')
import engine

from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs


class FishingHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        params = parse_qs(parsed.query)

        if path == '/api/fishing/status':
            result = engine.cmd('status')
            self._json({'result': result, 'state': self._get_state()})

        elif path == '/api/fishing/encyclopedia':
            result = engine.cmd('encyclopedia')
            self._json({'result': result, 'state': self._get_state()})

        elif path == '/api/fishing/inventory':
            result = engine.cmd('inventory')
            self._json({'result': result, 'state': self._get_state()})

        elif path == '/api/fishing/shop':
            result = engine.cmd('shop')
            self._json({'result': result, 'state': self._get_state()})

        elif path == '/api/fishing/locations':
            result = engine.cmd('goto')
            self._json({'result': result, 'state': self._get_state()})

        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        parsed = urlparse(self.path)
        length = int(self.headers.get('Content-Length', 0))
        body = json.loads(self.rfile.read(length)) if length else {}

        if parsed.path == '/api/fishing/cmd':
            command = body.get('cmd', '')
            if not command:
                self._json({'error': 'missing cmd'}, 400)
                return
            result = engine.cmd(command)
            self._json({'result': result, 'state': self._get_state()})

        else:
            self.send_response(404)
            self.end_headers()

    def _get_state(self):
        try:
            raw = engine.cmd('status')
            json_start = raw.rfind('📊')
            if json_start >= 0:
                json_str = raw[json_start:].split('\n')[0]
                json_str = json_str.replace('📊 ', '').strip()
                return json.loads(json_str)
        except:
            pass
        return {}

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
    server = HTTPServer(('127.0.0.1', 9907), FishingHandler)
    print('Fishing API running on :9907')
    server.serve_forever()
