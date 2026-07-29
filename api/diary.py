#!/usr/bin/env python3
"""
霖的朋友圈 API
- 随时发帖，不限一天一篇
- 每条帖子有评论区
- 按时间戳命名存储
"""
import json
import os
import time
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
from datetime import datetime

DATA_DIR = '/var/www/home/data/diary'


def post_path(post_id):
    return os.path.join(DATA_DIR, f'{post_id}.json')


def load_post(post_id):
    p = post_path(post_id)
    if os.path.exists(p):
        with open(p) as f:
            return json.load(f)
    return None


def save_post(post):
    p = post_path(post['id'])
    with open(p, 'w') as f:
        json.dump(post, f, ensure_ascii=False, indent=2)

def public_post(post, summary=False):
    """封存期内只返回元数据，避免前端绕过界面直接看到正文。"""
    locked = float(post.get('unlock_at') or 0) > time.time()
    data = {
        'id': post['id'],
        'content': '' if locked else post.get('content', ''),
        'mood': post.get('mood', ''),
        'author': post.get('author', 'sheep'),
        'coauthored': bool(post.get('coauthored')),
        'tags': post.get('tags', []),
        'unlock_at': post.get('unlock_at', 0),
        'locked': locked,
        'entry_date': post.get('entry_date', ''),
        'created_at': post.get('created_at', 0),
        'comment_count': len(post.get('comments', [])),
    }
    if not summary and not locked:
        data['comments'] = post.get('comments', [])
    return data


def list_posts(limit=50):
    posts = []
    if not os.path.exists(DATA_DIR):
        return posts
    files = sorted(os.listdir(DATA_DIR), reverse=True)
    for fname in files[:limit]:
        if not fname.endswith('.json'):
            continue
        try:
            with open(os.path.join(DATA_DIR, fname)) as f:
                post = json.load(f)
            posts.append(public_post(post, summary=True))
        except:
            pass
    posts.sort(key=lambda x: -x['created_at'])
    return posts


class DiaryHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        params = parse_qs(parsed.query)

        if path == '/api/diary':
            posts = list_posts()
            self._json({'posts': posts})

        elif path == '/api/diary/post':
            post_id = params.get('id', [''])[0]
            if post_id:
                post = load_post(post_id)
                if post:
                    self._json(public_post(post))
                else:
                    self._json({'error': 'not found'}, 404)
            else:
                self._json({'error': 'missing id'}, 400)
        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        parsed = urlparse(self.path)
        length = int(self.headers.get('Content-Length', 0))
        body = json.loads(self.rfile.read(length)) if length else {}

        if parsed.path == '/api/diary/write':
            content = body.get('content', '')
            mood = body.get('mood', '')
            author = body.get('author', 'sheep')
            tags = body.get('tags', [])
            unlock_at = float(body.get('unlock_at') or 0)
            now = time.time()
            post_id = str(int(now * 1000))

            post = {
                'id': post_id,
                'content': content,
                'mood': mood,
                'author': author,
                'coauthored': bool(body.get('coauthored')),
                'tags': tags if isinstance(tags, list) else [],
                'unlock_at': unlock_at,
                'entry_date': body.get('entry_date', ''),
                'comments': [],
                'created_at': now,
            }
            save_post(post)
            self._json({'ok': True, 'id': post_id})

        elif parsed.path == '/api/diary/comment':
            post_id = body.get('id', '')
            text = body.get('text', '')
            author = body.get('author', 'sheep')

            if not post_id or not text:
                self._json({'error': 'missing id or text'}, 400)
                return

            post = load_post(post_id)
            if not post:
                self._json({'error': 'post not found'}, 404)
                return

            comment = {
                'cid': int(time.time() * 1000),
                'author': author,
                'text': text,
                'time': time.time(),
            }
            post.setdefault('comments', []).append(comment)
            save_post(post)
            self._json({'ok': True, 'comment': comment})

        elif parsed.path == '/api/diary/delete':
            post_id = body.get('id', '')
            if post_id:
                p = post_path(post_id)
                if os.path.exists(p):
                    os.remove(p)
                    self._json({'ok': True})
                else:
                    self._json({'error': 'not found'}, 404)
            else:
                self._json({'error': 'missing id'}, 400)

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
    server = HTTPServer(('127.0.0.1', 9906), DiaryHandler)
    print('Diary API running on :9906')
    server.serve_forever()
