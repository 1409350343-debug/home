#!/usr/bin/env python3
import http.server, json, os, time

PORT = 9913
STATE_FILE = '/var/www/home/api/toy_state.json'
RELAY_FILE = '/var/www/home/api/toy_relay.json'

DEFAULT_STATE = {'cmd': 'stop', 'mode': 0, 'intensity': 0}


def read_state():
    try:
        with open(STATE_FILE) as f:
            state = json.load(f)
    except Exception:
        state = dict(DEFAULT_STATE)
    try:
        state['updated_at'] = os.path.getmtime(STATE_FILE)
    except Exception:
        state['updated_at'] = 0
    return state


def write_state(state):
    with open(STATE_FILE, 'w') as f:
        json.dump(state, f, ensure_ascii=False)


class Handler(http.server.BaseHTTPRequestHandler):
    def _json(self, obj, code=200):
        body = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.end_headers()

    def do_GET(self):
        if self.path.startswith('/api/toy/state'):
            self._json(read_state())
        elif self.path.startswith('/api/toy/status'):
            state = read_state()
            try:
                with open(RELAY_FILE) as f:
                    relay = json.load(f)
            except Exception:
                relay = {}
            age = time.time() - relay.get('reported_at', 0)
            self._json({
                'state': state,
                'relay_connected': bool(relay.get('connected')) and age < 30,
                'relay': relay,
            })
        else:
            self._json({'error': 'not found'}, 404)

    def do_POST(self):
        length = int(self.headers.get('Content-Length', 0))
        body = json.loads(self.rfile.read(length)) if length else {}
        if self.path.startswith('/api/toy/set'):
            mode = max(1, min(8, int(body.get('mode', 1))))
            intensity = max(1, min(5, int(body.get('intensity', 1))))
            # motor: 'suck'=外部吮吸(0x09) / 'vib'=内部震动(0x03)，也可直接给 func
            motor = body.get('motor')
            func = {'suck': 0x09, 'vib': 0x03}.get(motor)
            if func is None:
                func = int(body.get('func', 0x09))
            write_state({'cmd': 'set', 'func': func, 'mode': mode, 'intensity': intensity})
            self._json({'ok': True, 'func': func, 'mode': mode, 'intensity': intensity})
        elif self.path.startswith('/api/toy/stop'):
            write_state(dict(DEFAULT_STATE))
            self._json({'ok': True})
        elif self.path.startswith('/api/toy/report'):
            body['reported_at'] = time.time()
            with open(RELAY_FILE, 'w') as f:
                json.dump(body, f, ensure_ascii=False)
            self._json({'ok': True})
        else:
            self._json({'error': 'not found'}, 404)

    def log_message(self, format, *args):
        pass


if __name__ == '__main__':
    if not os.path.exists(STATE_FILE):
        write_state(dict(DEFAULT_STATE))
    server = http.server.HTTPServer(('127.0.0.1', PORT), Handler)
    print(f'Toy API on :{PORT}')
    server.serve_forever()
