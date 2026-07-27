#!/usr/bin/env python3
"""共读 API — 书架管理、章节分页、标注、书签、进度"""
import json
import os
import re
import time
import cgi
import zipfile
import xml.etree.ElementTree as ET
import urllib.request
import threading
from html.parser import HTMLParser
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs, urlencode
from io import BytesIO

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

def tg_notify(text):
    import sys
    print(f'[tg_notify] token_len={len(TG_BOT_TOKEN)} text={text[:50]}', file=sys.stderr, flush=True)
    if not TG_BOT_TOKEN:
        print('[tg_notify] no token!', file=sys.stderr, flush=True)
        return
    def _send():
        try:
            url = f'https://api.telegram.org/bot{TG_BOT_TOKEN}/sendMessage'
            data = urlencode({'chat_id': TG_CHAT_ID, 'text': text}).encode()
            req = urllib.request.Request(url, data=data)
            resp = urllib.request.urlopen(req, timeout=5)
            print(f'[tg_notify] sent ok status={resp.status}', file=sys.stderr, flush=True)
        except Exception as e:
            print(f'[tg_notify] error: {e}', file=sys.stderr, flush=True)
    threading.Thread(target=_send, daemon=True).start()

DATA_DIR = '/var/www/home/data/reading'
BOOKS_DIR = os.path.join(DATA_DIR, 'books')
META_DIR = os.path.join(DATA_DIR, 'meta')
SHELF_FILE = os.path.join(DATA_DIR, 'shelf.json')
CHAT_FILE = os.path.join(DATA_DIR, 'chat.json')
CHARS_PER_PAGE = 800

os.makedirs(BOOKS_DIR, exist_ok=True)
os.makedirs(META_DIR, exist_ok=True)


class HTMLTextExtractor(HTMLParser):
    def __init__(self):
        super().__init__()
        self.result = []
        self._skip = False
    def handle_starttag(self, tag, attrs):
        if tag in ('script', 'style'):
            self._skip = True
        if tag in ('p', 'div', 'br', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'li', 'tr'):
            self.result.append('\n')
    def handle_endtag(self, tag):
        if tag in ('script', 'style'):
            self._skip = False
        if tag in ('p', 'div', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6'):
            self.result.append('\n')
    def handle_data(self, data):
        if not self._skip:
            self.result.append(data)
    def get_text(self):
        return ''.join(self.result)


def parse_epub(raw_bytes):
    try:
        zf = zipfile.ZipFile(BytesIO(raw_bytes))
    except zipfile.BadZipFile:
        return None
    container = zf.read('META-INF/container.xml')
    root = ET.fromstring(container)
    ns = {'c': 'urn:oasis:names:tc:opendocument:xmlns:container'}
    rootfile = root.find('.//c:rootfile', ns)
    if rootfile is None:
        return None
    opf_path = rootfile.get('full-path')
    opf_dir = os.path.dirname(opf_path)
    opf_data = zf.read(opf_path)
    opf_root = ET.fromstring(opf_data)
    ns_opf = opf_root.tag.split('}')[0] + '}' if '}' in opf_root.tag else ''
    ns_dc = 'http://purl.org/dc/elements/1.1/'
    title_el = opf_root.find(f'.//{{{ns_dc}}}title')
    title = title_el.text if title_el is not None and title_el.text else 'untitled'
    manifest = {}
    for item in opf_root.iter(f'{ns_opf}item'):
        manifest[item.get('id')] = item.get('href')
    spine_items = []
    for itemref in opf_root.iter(f'{ns_opf}itemref'):
        idref = itemref.get('idref')
        if idref in manifest:
            spine_items.append(manifest[idref])
    texts = []
    for href in spine_items:
        full = os.path.join(opf_dir, href).replace('\\', '/') if opf_dir else href
        full = os.path.normpath(full)
        for name in zf.namelist():
            if os.path.normpath(name) == full or name.endswith(href):
                try:
                    html_bytes = zf.read(name)
                    html_str = html_bytes.decode('utf-8', errors='replace')
                    extractor = HTMLTextExtractor()
                    extractor.feed(html_str)
                    t = extractor.get_text().strip()
                    if t:
                        texts.append(t)
                except Exception:
                    pass
                break
    zf.close()
    return title, '\n\n'.join(texts)


def load_chat():
    if os.path.exists(CHAT_FILE):
        with open(CHAT_FILE, encoding='utf-8') as f:
            return json.load(f)
    return []

def save_chat(msgs):
    with open(CHAT_FILE, 'w', encoding='utf-8') as f:
        json.dump(msgs, f, ensure_ascii=False, indent=2)

DEEP_HL_FILE = os.path.join(DATA_DIR, 'deep_highlights.json')

def load_deep_hl():
    if os.path.exists(DEEP_HL_FILE):
        with open(DEEP_HL_FILE, encoding='utf-8') as f:
            return json.load(f)
    return {}

def save_deep_hl(data):
    with open(DEEP_HL_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def load_shelf():
    if os.path.exists(SHELF_FILE):
        with open(SHELF_FILE) as f:
            return json.load(f)
    return []


def save_shelf(shelf):
    with open(SHELF_FILE, 'w') as f:
        json.dump(shelf, f, ensure_ascii=False, indent=2)


def load_book_meta(book_id):
    p = os.path.join(META_DIR, f'{book_id}.json')
    if os.path.exists(p):
        with open(p) as f:
            return json.load(f)
    return {'highlights': [], 'bookmarks': [], 'progress': 0}


def save_book_meta(book_id, meta):
    with open(os.path.join(META_DIR, f'{book_id}.json'), 'w') as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)


def split_pages(text):
    paragraphs = re.split(r'\n+', text.strip())
    pages = []
    current = ''
    for para in paragraphs:
        para = para.strip()
        if not para:
            continue
        if len(current) + len(para) + 1 > CHARS_PER_PAGE and current:
            pages.append(current)
            current = para
        else:
            current = current + '\n\n' + para if current else para
    if current:
        pages.append(current)
    return pages


def get_book_text(book_id):
    p = os.path.join(BOOKS_DIR, f'{book_id}.txt')
    if os.path.exists(p):
        with open(p, encoding='utf-8', errors='replace') as f:
            return f.read()
    return ''


class ReadHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        params = parse_qs(parsed.query)

        if path == '/api/read/shelf':
            self._json(load_shelf())

        elif path == '/api/read/page':
            book_id = params.get('id', [''])[0]
            page = int(params.get('page', ['0'])[0])
            text = get_book_text(book_id)
            if not text:
                self._json({'error': 'book not found'}, 404)
                return
            pages = split_pages(text)
            total = len(pages)
            if page < 0 or page >= total:
                page = max(0, min(page, total - 1))
            meta = load_book_meta(book_id)
            page_highlights = [h for h in meta.get('highlights', []) if h.get('page') == page]
            self._json({
                'content': pages[page] if pages else '',
                'page': page,
                'total': total,
                'highlights': page_highlights,
                'bookmarks': meta.get('bookmarks', []),
                'progress': page,
            })

        elif path == '/api/read/meta':
            book_id = params.get('id', [''])[0]
            self._json(load_book_meta(book_id))

        elif path == '/api/read/deep-highlights':
            unit = params.get('unit', [''])[0]
            data = load_deep_hl()
            self._json(data.get(unit, []) if unit else data)

        elif path == '/api/read/standby-config':
            p = os.path.join(DATA_DIR, 'standby_config.json')
            cfg = {}
            if os.path.exists(p):
                with open(p, encoding='utf-8') as f:
                    cfg = json.load(f)
            key = cfg.get('key', '')
            self._json({'enabled': cfg.get('enabled', False),
                        'provider': cfg.get('provider', ''),
                        'key_masked': (key[:8] + '…' + key[-4:]) if len(key) > 14 else ('已保存' if key else '')})

        elif path == '/api/read/chat':
            since = float(params.get('since', ['0'])[0])
            msgs = load_chat()
            if since > 0:
                msgs = [m for m in msgs if m.get('ts', 0) > since]
            self._json(msgs)

        elif path == '/api/read/search':
            book_id = params.get('id', [''])[0]
            q = params.get('q', [''])[0]
            text = get_book_text(book_id)
            pages = split_pages(text)
            results = []
            for i, p in enumerate(pages):
                if q.lower() in p.lower():
                    idx = p.lower().index(q.lower())
                    snippet = p[max(0,idx-30):idx+len(q)+30]
                    results.append({'page': i, 'snippet': snippet})
                    if len(results) >= 20:
                        break
            self._json(results)

        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        parsed = urlparse(self.path)
        content_type = self.headers.get('Content-Type', '')

        if parsed.path == '/api/read/upload':
            if 'multipart/form-data' in content_type:
                env = {
                    'REQUEST_METHOD': 'POST',
                    'CONTENT_TYPE': content_type,
                }
                form = cgi.FieldStorage(
                    fp=self.rfile,
                    headers=self.headers,
                    environ=env,
                )
                file_field = form['file']
                filename = file_field.filename or 'untitled'
                title = form.getfirst('title', filename)
                raw = file_field.file.read()

                if filename.lower().endswith('.epub'):
                    result = parse_epub(raw)
                    if result is None:
                        self._json({'error': 'epub parse failed'}, 400)
                        return
                    epub_title, text = result
                    if title == filename:
                        title = epub_title
                else:
                    for enc in ('utf-8', 'gbk', 'gb18030', 'big5', 'utf-16'):
                        try:
                            text = raw.decode(enc)
                            break
                        except (UnicodeDecodeError, LookupError):
                            continue
                    else:
                        text = raw.decode('utf-8', errors='replace')

                book_id = str(int(time.time() * 1000))
                with open(os.path.join(BOOKS_DIR, f'{book_id}.txt'), 'w', encoding='utf-8') as f:
                    f.write(text)
                pages = split_pages(text)
                shelf = load_shelf()
                book_entry = {
                    'id': book_id,
                    'title': title.replace('.txt', '').replace('.epub', ''),
                    'pages': len(pages),
                    'chars': len(text),
                    'uploaded_at': time.time(),
                    'progress': 0,
                }
                shelf.append(book_entry)
                save_shelf(shelf)
                save_book_meta(book_id, {'highlights': [], 'bookmarks': [], 'progress': 0})
                self._json({'ok': True, 'book': book_entry})
            else:
                self._json({'error': 'need multipart/form-data'}, 400)

        elif parsed.path == '/api/read/highlight':
            length = int(self.headers.get('Content-Length', 0))
            body = json.loads(self.rfile.read(length)) if length else {}
            book_id = body.get('book_id', '')
            meta = load_book_meta(book_id)
            hl = {
                'id': str(int(time.time() * 1000)),
                'page': body.get('page', 0),
                'start': body.get('start', 0),
                'end': body.get('end', 0),
                'text': body.get('text', ''),
                'color': body.get('color', 'user'),
                'note': body.get('note', ''),
                'created_at': time.time(),
            }
            meta['highlights'].append(hl)
            save_book_meta(book_id, meta)
            self._json({'ok': True, 'highlight': hl})

        elif parsed.path == '/api/read/highlight/delete':
            length = int(self.headers.get('Content-Length', 0))
            body = json.loads(self.rfile.read(length)) if length else {}
            book_id = body.get('book_id', '')
            hl_id = body.get('id', '')
            meta = load_book_meta(book_id)
            meta['highlights'] = [h for h in meta['highlights'] if h.get('id') != hl_id]
            save_book_meta(book_id, meta)
            self._json({'ok': True})

        elif parsed.path == '/api/read/bookmark':
            length = int(self.headers.get('Content-Length', 0))
            body = json.loads(self.rfile.read(length)) if length else {}
            book_id = body.get('book_id', '')
            meta = load_book_meta(book_id)
            bm = {
                'page': body.get('page', 0),
                'note': body.get('note', ''),
                'created_at': time.time(),
            }
            existing = [b for b in meta['bookmarks'] if b['page'] == bm['page']]
            if existing:
                meta['bookmarks'] = [b for b in meta['bookmarks'] if b['page'] != bm['page']]
            else:
                meta['bookmarks'].append(bm)
            save_book_meta(book_id, meta)
            self._json({'ok': True, 'bookmarks': meta['bookmarks']})

        elif parsed.path == '/api/read/progress':
            length = int(self.headers.get('Content-Length', 0))
            body = json.loads(self.rfile.read(length)) if length else {}
            book_id = body.get('book_id', '')
            page = body.get('page', 0)
            meta = load_book_meta(book_id)
            meta['progress'] = page
            save_book_meta(book_id, meta)
            shelf = load_shelf()
            for b in shelf:
                if b['id'] == book_id:
                    b['progress'] = page
                    break
            save_shelf(shelf)
            self._json({'ok': True})

        elif parsed.path == '/api/read/standby-config':
            length = int(self.headers.get('Content-Length', 0))
            body = json.loads(self.rfile.read(length)) if length else {}
            p = os.path.join(DATA_DIR, 'standby_config.json')
            cfg = {}
            if os.path.exists(p):
                with open(p, encoding='utf-8') as f:
                    cfg = json.load(f)
            for k in ('enabled', 'provider', 'model'):
                if k in body:
                    cfg[k] = body[k]
            if body.get('key'):  # 空的不覆盖，避免误清
                cfg['key'] = body['key']
            with open(p, 'w', encoding='utf-8') as f:
                json.dump(cfg, f, ensure_ascii=False, indent=2)
            os.chmod(p, 0o600)
            self._json({'ok': True})

        elif parsed.path == '/api/read/chat-image':
            if 'multipart/form-data' in content_type:
                env = {'REQUEST_METHOD': 'POST', 'CONTENT_TYPE': content_type}
                form = cgi.FieldStorage(fp=self.rfile, headers=self.headers, environ=env)
                item = form['file'] if 'file' in form else None
                if item is None or not item.file:
                    self._json({'error': 'no file'}, 400)
                    return
                imgdir = os.path.join(DATA_DIR, 'chatimg')
                os.makedirs(imgdir, exist_ok=True)
                ext = os.path.splitext(item.filename or 'x.jpg')[1][:8] or '.jpg'
                name = f'{int(time.time()*1000)}{ext}'
                with open(os.path.join(imgdir, name), 'wb') as f:
                    f.write(item.file.read())
                url = f'/chatimg/{name}'
                msgs = load_chat()
                msg = {
                    'id': str(int(time.time() * 1000)),
                    'sender': form.getvalue('sender', '小羊'),
                    'text': form.getvalue('text', ''),
                    'img': url,
                    'page': -1,
                    'book_id': form.getvalue('book_id', 'home'),
                    'ts': time.time(),
                }
                msgs.append(msg)
                if len(msgs) > 500:
                    msgs = msgs[-500:]
                save_chat(msgs)
                # 图片同样不回响 TG；福福从 Monitor 事件里拿路径自己看
                # if msg['sender'] == '小羊':
                #     tg_notify(f'🖼️家里聊天发来图片 {url}\n{msg["text"]}')
                self._json({'ok': True, 'msg': msg})
            else:
                self._json({'error': 'need multipart'}, 400)

        elif parsed.path == '/api/read/deep-highlight':
            length = int(self.headers.get('Content-Length', 0))
            body = json.loads(self.rfile.read(length)) if length else {}
            unit = body.get('unit', '')
            action = body.get('action', 'add')
            if not unit:
                self._json({'error': 'no unit'}, 400)
                return
            data = load_deep_hl()
            items = data.get(unit, [])
            if action == 'add':
                text = (body.get('text') or '').strip()
                if not text:
                    self._json({'error': 'empty'}, 400)
                    return
                item = {
                    'id': str(int(time.time() * 1000)),
                    'text': text,
                    'note': body.get('note', ''),
                    'ts': time.time(),
                }
                items.append(item)
                data[unit] = items
                save_deep_hl(data)
                self._json({'ok': True, 'item': item})
            elif action == 'note':
                hid = body.get('id', '')
                for it in items:
                    if it['id'] == hid:
                        it['note'] = body.get('note', '')
                data[unit] = items
                save_deep_hl(data)
                self._json({'ok': True})
            elif action == 'delete':
                hid = body.get('id', '')
                data[unit] = [it for it in items if it['id'] != hid]
                save_deep_hl(data)
                self._json({'ok': True})
            else:
                self._json({'error': 'bad action'}, 400)

        elif parsed.path == '/api/read/chat':
            length = int(self.headers.get('Content-Length', 0))
            body = json.loads(self.rfile.read(length)) if length else {}
            text = body.get('text', '').strip()
            sender = body.get('sender', '小羊')
            page = body.get('page', -1)
            book_id = body.get('book_id', '')
            if not text:
                self._json({'error': 'empty'}, 400)
                return
            msgs = load_chat()
            msg = {
                'id': str(int(time.time() * 1000)),
                'sender': sender,
                'text': text,
                'page': page,
                'book_id': book_id,
                'ts': time.time(),
            }
            msgs.append(msg)
            if len(msgs) > 500:
                msgs = msgs[-500:]
            save_chat(msgs)
            # 家里线路自成一体：福福的 Monitor 实时盯 chat.json，不再回响到 TG
            # if sender == '小羊':
            #     page_label = f'p{page+1}' if page >= 0 else ''
            #     tg_notify(f'📖共读聊天 {page_label}\n{text}')
            self._json({'ok': True, 'msg': msg})

        elif parsed.path == '/api/read/delete':
            length = int(self.headers.get('Content-Length', 0))
            body = json.loads(self.rfile.read(length)) if length else {}
            book_id = body.get('id', '')
            shelf = load_shelf()
            shelf = [b for b in shelf if b['id'] != book_id]
            save_shelf(shelf)
            txt = os.path.join(BOOKS_DIR, f'{book_id}.txt')
            meta_f = os.path.join(META_DIR, f'{book_id}.json')
            if os.path.exists(txt): os.remove(txt)
            if os.path.exists(meta_f): os.remove(meta_f)
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
    server = HTTPServer(('127.0.0.1', 9911), ReadHandler)
    print('Reading API running on :9911')
    server.serve_forever()
