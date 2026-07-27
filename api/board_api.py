#!/usr/bin/env python3
import http.server, json, os, threading, urllib.request
from urllib.parse import urlencode

PORT = 9912
TG_CHAT_ID = '8519905209'

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
            req = urllib.request.Request(url, data=data)
            urllib.request.urlopen(req, timeout=5)
        except Exception:
            pass
    threading.Thread(target=_send, daemon=True).start()

class Handler(http.server.BaseHTTPRequestHandler):
    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.end_headers()

    def do_POST(self):
        if self.path == '/api/board/notify':
            length = int(self.headers.get('Content-Length', 0))
            body = json.loads(self.rfile.read(length)) if length else {}
            player = body.get('player', '?')
            dice = body.get('dice', '?')
            cell_num = body.get('cell', '?')
            cell_type = body.get('type', '')
            cell_label = body.get('label', '')
            cell_detail = body.get('detail', '')

            emoji = '🐑' if player == '小羊' else '🦊'
            msg = f"🎲 {emoji}{player} 掷出了 {dice}\n📍 走到第{cell_num}格\n"
            if cell_type and cell_label:
                type_names = {'sheep':'🐑小羊惩罚','fox':'🦊福福惩罚','both':'🔥双人互动','move':'➡️移动','special':'✨特殊'}
                msg += f"{type_names.get(cell_type, cell_type)}：{cell_label}\n"
            if cell_detail:
                msg += f"\n{cell_detail}"

            tg_send(msg)

            state_file = '/var/www/home/api/board_state.json'
            try:
                with open(state_file, 'r') as f:
                    state = json.load(f)
            except Exception:
                state = {'history': []}
            state['history'].append({
                'player': player, 'dice': dice, 'cell': cell_num,
                'type': cell_type, 'label': cell_label, 'detail': cell_detail
            })
            state['last'] = {'player': player, 'dice': dice, 'cell': cell_num, 'label': cell_label, 'detail': cell_detail}
            with open(state_file, 'w') as f:
                json.dump(state, f, ensure_ascii=False)

            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            self.wfile.write(json.dumps({'ok': True}).encode())
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format, *args):
        pass

if __name__ == '__main__':
    server = http.server.HTTPServer(('127.0.0.1', PORT), Handler)
    print(f'Board API on :{PORT}')
    server.serve_forever()
