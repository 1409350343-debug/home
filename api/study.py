#!/usr/bin/env python3
"""
书房 API
- 杂学冷知识
- 专业知识
"""
import json
import os
import time
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

DATA_DIR = '/var/www/home/data/study'
NOTES_FILE = os.path.join(DATA_DIR, 'notes.json')


def load_notes():
    if os.path.exists(NOTES_FILE):
        with open(NOTES_FILE) as f:
            return json.load(f)
    return []


def save_notes(notes):
    with open(NOTES_FILE, 'w') as f:
        json.dump(notes, f, ensure_ascii=False, indent=2)


class StudyHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        params = parse_qs(parsed.query)

        if path == '/api/study/notes':
            cat = params.get('cat', [''])[0]
            notes = load_notes()
            if cat:
                notes = [n for n in notes if n.get('category') == cat]
            notes.sort(key=lambda x: -x.get('created_at', 0))
            self._json(notes)

        elif path == '/api/study/stats':
            notes = load_notes()
            trivia = len([n for n in notes if n.get('category') == 'trivia'])
            pro = len([n for n in notes if n.get('category') == 'professional'])
            self._json({'trivia': trivia, 'professional': pro, 'total': len(notes)})

        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        parsed = urlparse(self.path)
        length = int(self.headers.get('Content-Length', 0))
        body = json.loads(self.rfile.read(length)) if length else {}

        if parsed.path == '/api/study/add':
            title = body.get('title', '')
            content = body.get('content', '')
            category = body.get('category', 'trivia')
            tags = body.get('tags', [])
            if not title or not content:
                self._json({'error': 'missing title or content'}, 400)
                return
            notes = load_notes()
            note = {
                'id': int(time.time() * 1000),
                'title': title,
                'content': content,
                'category': category,
                'tags': tags,
                'created_at': time.time(),
            }
            notes.append(note)
            save_notes(notes)
            self._json({'ok': True, 'note': note})

        elif parsed.path == '/api/study/delete':
            note_id = body.get('id', 0)
            notes = load_notes()
            notes = [n for n in notes if n.get('id') != note_id]
            save_notes(notes)
            self._json({'ok': True})

        elif parsed.path == '/api/study/edit':
            note_id = body.get('id', 0)
            notes = load_notes()
            for n in notes:
                if n.get('id') == note_id:
                    if 'title' in body:
                        n['title'] = body['title']
                    if 'content' in body:
                        n['content'] = body['content']
                    if 'category' in body:
                        n['category'] = body['category']
                    if 'tags' in body:
                        n['tags'] = body['tags']
                    break
            save_notes(notes)
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
    server = HTTPServer(('127.0.0.1', 9909), StudyHandler)
    print('Study API running on :9909')
    server.serve_forever()
