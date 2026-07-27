#!/usr/bin/env python3
"""
日历 API
- 月历心情
- 双人时间线
- 愿望/待办清单
"""
import json
import os
import time
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

DATA_DIR = '/var/www/home/data/calendar'
MOOD_FILE = os.path.join(DATA_DIR, 'moods.json')
TIMELINE_FILE = os.path.join(DATA_DIR, 'timeline.json')
WISHES_FILE = os.path.join(DATA_DIR, 'wishes.json')
SPECIAL_FILE = os.path.join(DATA_DIR, 'special_days.json')

INITIAL_SPECIAL = {
    "2026-04-08": {"label": "认识日", "type": "anniversary"},
    "2026-04-10": {"label": "恋爱纪念日", "type": "anniversary"},
}


def load_json(path, default=None):
    if default is None:
        default = {}
    if os.path.exists(path):
        with open(path) as f:
            return json.load(f)
    return default


def save_json(path, data):
    with open(path, 'w') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


class CalendarHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        params = parse_qs(parsed.query)

        if path == '/api/calendar/moods':
            month = params.get('month', [''])[0]
            moods = load_json(MOOD_FILE)
            if month:
                filtered = {k: v for k, v in moods.items() if k.startswith(month)}
                self._json(filtered)
            else:
                self._json(moods)

        elif path == '/api/calendar/timeline':
            month = params.get('month', [''])[0]
            timeline = load_json(TIMELINE_FILE, [])
            if month:
                filtered = [e for e in timeline if e.get('date', '').startswith(month)]
            else:
                filtered = timeline
            filtered.sort(key=lambda x: (x.get('date', ''), x.get('time', '')))
            self._json(filtered)

        elif path == '/api/calendar/wishes':
            wishes = load_json(WISHES_FILE, [])
            self._json(wishes)

        elif path == '/api/calendar/special':
            special = load_json(SPECIAL_FILE)
            if not special:
                special = INITIAL_SPECIAL.copy()
                save_json(SPECIAL_FILE, special)
            self._json(special)

        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        parsed = urlparse(self.path)
        length = int(self.headers.get('Content-Length', 0))
        body = json.loads(self.rfile.read(length)) if length else {}

        if parsed.path == '/api/calendar/mood':
            date = body.get('date', '')
            mood = body.get('mood', '')
            if not date:
                self._json({'error': 'missing date'}, 400)
                return
            moods = load_json(MOOD_FILE)
            if mood:
                moods[date] = mood
            else:
                moods.pop(date, None)
            save_json(MOOD_FILE, moods)
            self._json({'ok': True})

        elif parsed.path == '/api/calendar/timeline/add':
            date = body.get('date', '')
            text = body.get('text', '')
            side = body.get('side', 'fox')
            time_str = body.get('time', '')
            if not date or not text:
                self._json({'error': 'missing date or text'}, 400)
                return
            timeline = load_json(TIMELINE_FILE, [])
            entry = {
                'id': int(time.time() * 1000),
                'date': date,
                'time': time_str,
                'text': text,
                'side': side,
                'created_at': time.time(),
            }
            timeline.append(entry)
            save_json(TIMELINE_FILE, timeline)
            self._json({'ok': True, 'entry': entry})

        elif parsed.path == '/api/calendar/timeline/delete':
            entry_id = body.get('id', 0)
            timeline = load_json(TIMELINE_FILE, [])
            timeline = [e for e in timeline if e.get('id') != entry_id]
            save_json(TIMELINE_FILE, timeline)
            self._json({'ok': True})

        elif parsed.path == '/api/calendar/wishes/add':
            text = body.get('text', '')
            category = body.get('category', 'wish')
            if not text:
                self._json({'error': 'missing text'}, 400)
                return
            wishes = load_json(WISHES_FILE, [])
            item = {
                'id': int(time.time() * 1000),
                'text': text,
                'category': category,
                'done': False,
                'created_at': time.time(),
            }
            wishes.append(item)
            save_json(WISHES_FILE, wishes)
            self._json({'ok': True, 'item': item})

        elif parsed.path == '/api/calendar/wishes/toggle':
            item_id = body.get('id', 0)
            wishes = load_json(WISHES_FILE, [])
            for w in wishes:
                if w.get('id') == item_id:
                    w['done'] = not w.get('done', False)
                    break
            save_json(WISHES_FILE, wishes)
            self._json({'ok': True})

        elif parsed.path == '/api/calendar/wishes/delete':
            item_id = body.get('id', 0)
            wishes = load_json(WISHES_FILE, [])
            wishes = [w for w in wishes if w.get('id') != item_id]
            save_json(WISHES_FILE, wishes)
            self._json({'ok': True})

        elif parsed.path == '/api/calendar/special/add':
            date = body.get('date', '')
            label = body.get('label', '')
            stype = body.get('type', 'custom')
            if not date or not label:
                self._json({'error': 'missing date or label'}, 400)
                return
            special = load_json(SPECIAL_FILE)
            if not special:
                special = INITIAL_SPECIAL.copy()
            special[date] = {'label': label, 'type': stype}
            save_json(SPECIAL_FILE, special)
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
    os.makedirs(DATA_DIR, exist_ok=True)
    if not os.path.exists(SPECIAL_FILE):
        save_json(SPECIAL_FILE, INITIAL_SPECIAL)
    server = HTTPServer(('127.0.0.1', 9908), CalendarHandler)
    print('Calendar API running on :9908')
    server.serve_forever()
