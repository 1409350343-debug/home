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
import tempfile
import uuid
from html.parser import HTMLParser
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs, urlencode
from io import BytesIO
from contextlib import contextmanager

try:
    import fcntl
except ImportError:  # Windows fallback; production is Linux.
    fcntl = None

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

DATA_DIR = os.environ.get('HOME_READING_DATA_DIR', '/var/www/home/data/reading')
BOOKS_DIR = os.path.join(DATA_DIR, 'books')
META_DIR = os.path.join(DATA_DIR, 'meta')
SHELF_FILE = os.path.join(DATA_DIR, 'shelf.json')
CHAT_FILE = os.path.join(DATA_DIR, 'chat.json')
CHAT_ARCHIVE_FILE = os.path.join(DATA_DIR, 'chat-archive.jsonl')
CHAT_LOCK_FILE = os.path.join(DATA_DIR, '.chat.lock')
CHAT_HEARTBEAT_FILE = os.path.join(DATA_DIR, 'cc_monitor_heartbeat.json')
TIME_STATE_FILE = os.environ.get(
    'HOME_TIME_STATE',
    os.path.join(os.path.dirname(os.path.abspath(__file__)), 'time_state.json'),
)
VAULT_DIR = os.environ.get('HOME_VAULT_DIR', '/var/www/home/vault')
VAULT_MANIFEST_FILE = os.path.join(VAULT_DIR, 'manifest.json')
CHARS_PER_PAGE = 800
CHAT_KEEP = 500
CHAT_TEXT_LIMIT = 10000
CHAT_IMAGE_LIMIT = 8 * 1024 * 1024
AVATAR_LIMIT = 2 * 1024 * 1024
PROFILE_DIR = os.path.join(DATA_DIR, 'profile')

os.makedirs(BOOKS_DIR, exist_ok=True)
os.makedirs(META_DIR, exist_ok=True)
os.makedirs(PROFILE_DIR, exist_ok=True)


def avatar_path(owner):
    if owner not in ('xiaoyang', 'fufu'):
        return ''
    return os.path.join(PROFILE_DIR, f'avatar-{owner}.jpg')


def save_avatar(owner, raw):
    path = avatar_path(owner)
    if not path:
        raise ValueError('unknown owner')
    fd, tmp_path = tempfile.mkstemp(prefix='.avatar-', suffix='.tmp', dir=PROFILE_DIR)
    try:
        with os.fdopen(fd, 'wb') as f:
            f.write(raw)
            f.flush()
            os.fsync(f.fileno())
        os.chmod(tmp_path, 0o644)
        os.replace(tmp_path, path)
    finally:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)


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


_chat_thread_lock = threading.RLock()


@contextmanager
def chat_lock():
    """Coordinate API writers while remaining compatible with file-watching Monitor."""
    with _chat_thread_lock:
        os.makedirs(DATA_DIR, exist_ok=True)
        with open(CHAT_LOCK_FILE, 'a+') as lock_file:
            if fcntl:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                if fcntl:
                    fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


def load_chat():
    if not os.path.exists(CHAT_FILE):
        return []
    try:
        with open(CHAT_FILE, encoding='utf-8') as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except (OSError, json.JSONDecodeError):
        # Atomic API writes prevent new corruption. A Monitor may still be midway
        # through a legacy in-place write, so readers fail soft and retry later.
        return []


def _atomic_json_write(path, data, mode=0o600):
    directory = os.path.dirname(path)
    os.makedirs(directory, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(prefix='.chat-', suffix='.tmp', dir=directory)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.chmod(tmp_path, mode)
        os.replace(tmp_path, path)
    finally:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)


def save_chat(msgs):
    _atomic_json_write(CHAT_FILE, msgs)


def append_chat(msg):
    """Append without changing chat.json, the existing CC/TG bridge contract."""
    with chat_lock():
        msgs = load_chat()
        client_id = msg.get('client_id')
        if client_id:
            existing = next((m for m in msgs if m.get('client_id') == client_id), None)
            if existing:
                return existing
        msgs.append(msg)
        if len(msgs) > CHAT_KEEP:
            archived, msgs = msgs[:-CHAT_KEEP], msgs[-CHAT_KEEP:]
            with open(CHAT_ARCHIVE_FILE, 'a', encoding='utf-8') as archive:
                for old in archived:
                    archive.write(json.dumps(old, ensure_ascii=False) + '\n')
        save_chat(msgs)
    return msg


def temporal_context():
    """Return the current shared context without making chat depend on it."""
    try:
        with open(TIME_STATE_FILE, encoding='utf-8') as f:
            state = json.load(f)
        return {
            'summary': state.get('ai_context', ''),
            'status': state.get('status', ''),
            'location': state.get('location', ''),
            'updated_at': state.get('updated_at', 0),
        }
    except (OSError, json.JSONDecodeError):
        return {}


def new_message(sender, text, page=-1, book_id='home', img=None, client_id=None):
    now = time.time()
    msg = {
        'id': f'{int(now * 1000)}-{uuid.uuid4().hex[:8]}',
        'sender': sender,
        'text': text,
        'page': page,
        'book_id': book_id,
        'ts': now,
    }
    if img:
        msg['img'] = img
    if client_id:
        msg['client_id'] = str(client_id)[:100]
    if sender == '小羊':
        msg['delivery'] = 'queued'
        msg['route'] = 'cc-tg'
        context = temporal_context()
        if context:
            # Extra field only: old CC/TG Monitor remains fully compatible.
            msg['temporal_context'] = context
    return msg


def image_extension(raw):
    if raw.startswith(b'\xff\xd8\xff'):
        return '.jpg'
    if raw.startswith(b'\x89PNG\r\n\x1a\n'):
        return '.png'
    if raw.startswith((b'GIF87a', b'GIF89a')):
        return '.gif'
    if raw.startswith(b'RIFF') and raw[8:12] == b'WEBP':
        return '.webp'
    return ''


def chat_status(msgs=None):
    msgs = msgs if msgs is not None else load_chat()
    home = [m for m in msgs if (m.get('book_id') or 'home') == 'home']
    mine = next((m for m in reversed(home) if m.get('sender') == '小羊'), None)
    reply = next((m for m in reversed(home) if m.get('sender') != '小羊'), None)
    heartbeat = {}
    if os.path.exists(CHAT_HEARTBEAT_FILE):
        try:
            with open(CHAT_HEARTBEAT_FILE, encoding='utf-8') as f:
                heartbeat = json.load(f)
        except (OSError, json.JSONDecodeError):
            heartbeat = {}
    heartbeat_ts = float(heartbeat.get('ts') or 0)
    cc_online = bool(heartbeat_ts and time.time() - heartbeat_ts < 45)
    waiting = bool(mine and (not reply or mine.get('ts', 0) > reply.get('ts', 0)))
    return {
        'api': 'online',
        'route': 'cc-tg',
        'cc_online': cc_online,
        'cc_status_known': bool(heartbeat_ts),
        'heartbeat_ts': heartbeat_ts or None,
        'waiting': waiting,
        'last_user_ts': mine.get('ts') if mine else None,
        'last_reply_ts': reply.get('ts') if reply else None,
    }

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


def load_vault_manifest():
    if not os.path.exists(VAULT_MANIFEST_FILE):
        return {'books': []}
    try:
        with open(VAULT_MANIFEST_FILE, encoding='utf-8') as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {'books': []}
    except (OSError, json.JSONDecodeError):
        return {'books': []}


def _notebook_section(section_id, title, subtitle=''):
    return {
        'id': section_id,
        'title': title,
        'subtitle': subtitle,
        'highlights': [],
        'questions': [],
    }


def build_deep_notebook(book_id):
    manifest = load_vault_manifest()
    book = next((b for b in manifest.get('books', []) if str(b.get('id')) == str(book_id)), None)
    if not book:
        return None
    chapter_map = {str(c.get('id')): c for c in book.get('chapters', [])}
    section_map = {}

    def get_section(chapter_id):
        chapter = chapter_map.get(chapter_id, {})
        title = chapter.get('title') or chapter_id
        return section_map.setdefault(
            chapter_id,
            _notebook_section(chapter_id, title, f'章节 {chapter_id}'),
        )

    highlights = load_deep_hl()
    prefix = f'{book_id}/'
    for unit_key, items in highlights.items():
        if not str(unit_key).startswith(prefix):
            continue
        rest = str(unit_key)[len(prefix):]
        parts = rest.split('/', 1)
        chapter_id = parts[0]
        unit = parts[1] if len(parts) > 1 else ''
        section = get_section(chapter_id)
        for item in items if isinstance(items, list) else []:
            section['highlights'].append({
                'id': item.get('id', ''),
                'text': item.get('text', ''),
                'note': item.get('note', ''),
                'unit': unit,
                'ts': item.get('ts'),
            })

    chat_prefix = f'vault:{book_id}/'
    for message in load_chat():
        context = str(message.get('book_id') or '')
        if message.get('sender') != '小羊' or not context.startswith(chat_prefix):
            continue
        rest = context[len(chat_prefix):]
        parts = rest.split('/', 1)
        chapter_id = parts[0]
        unit = parts[1] if len(parts) > 1 else ''
        section = get_section(chapter_id)
        section['questions'].append({
            'id': message.get('id', ''),
            'text': message.get('text', ''),
            'unit': unit,
            'ts': message.get('ts'),
        })

    chapter_order = {str(c.get('id')): i for i, c in enumerate(book.get('chapters', []))}
    ordered = sorted(section_map.values(), key=lambda s: chapter_order.get(s['id'], 10 ** 6))
    return {
        'book': {'id': str(book_id), 'title': book.get('title') or f'《{book_id}》', 'kind': 'deep'},
        'sections': ordered,
        'counts': {
            'highlights': sum(len(s['highlights']) for s in ordered),
            'questions': sum(len(s['questions']) for s in ordered),
        },
    }


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

        elif path == '/api/read/notebook':
            book_id = params.get('id', [''])[0]
            notebook = build_deep_notebook(book_id)
            if notebook is None:
                self._json({'error': 'book not found'}, 404)
            else:
                self._json(notebook)

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
            book_id = params.get('book_id', [''])[0]
            if book_id:
                msgs = [m for m in msgs if str(m.get('book_id') or '') == book_id]
            if since > 0:
                msgs = [m for m in msgs if m.get('ts', 0) > since]
            self._json(msgs)

        elif path == '/api/read/chat-status':
            self._json(chat_status())

        elif path == '/api/read/profile':
            avatars = {}
            for owner in ('xiaoyang', 'fufu'):
                target = avatar_path(owner)
                if os.path.exists(target):
                    avatars[owner] = f'/api/read/avatar?owner={owner}&v={int(os.path.getmtime(target))}'
            self._json({'avatars': avatars})

        elif path == '/api/read/avatar':
            owner = params.get('owner', [''])[0]
            target = avatar_path(owner)
            if not target or not os.path.exists(target):
                self.send_response(404)
                self.end_headers()
                return
            with open(target, 'rb') as f:
                raw = f.read()
            self.send_response(200)
            self.send_header('Content-Type', 'image/jpeg')
            self.send_header('Content-Length', str(len(raw)))
            self.send_header('Cache-Control', 'public, max-age=31536000, immutable')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.end_headers()
            self.wfile.write(raw)

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

        if parsed.path == '/api/read/avatar':
            if 'multipart/form-data' not in content_type:
                self._json({'error': 'need multipart'}, 400)
                return
            content_length = int(self.headers.get('Content-Length', 0))
            if content_length > AVATAR_LIMIT + 512 * 1024:
                self._json({'error': 'avatar too large', 'limit': AVATAR_LIMIT}, 413)
                return
            env = {'REQUEST_METHOD': 'POST', 'CONTENT_TYPE': content_type}
            form = cgi.FieldStorage(fp=self.rfile, headers=self.headers, environ=env)
            owner = str(form.getvalue('owner', '') or '')
            item = form['file'] if 'file' in form else None
            if owner not in ('xiaoyang', 'fufu') or item is None or not item.file:
                self._json({'error': 'invalid avatar'}, 400)
                return
            raw = item.file.read(AVATAR_LIMIT + 1)
            if len(raw) > AVATAR_LIMIT:
                self._json({'error': 'avatar too large', 'limit': AVATAR_LIMIT}, 413)
                return
            if image_extension(raw) != '.jpg':
                self._json({'error': 'avatar must be jpeg'}, 415)
                return
            save_avatar(owner, raw)
            version = int(os.path.getmtime(avatar_path(owner)))
            self._json({'ok': True, 'owner': owner,
                        'url': f'/api/read/avatar?owner={owner}&v={version}'})

        elif parsed.path == '/api/read/avatar/reset':
            length = int(self.headers.get('Content-Length', 0))
            body = json.loads(self.rfile.read(length)) if length else {}
            target = avatar_path(str(body.get('owner', '')))
            if not target:
                self._json({'error': 'invalid owner'}, 400)
                return
            if os.path.exists(target):
                os.remove(target)
            self._json({'ok': True})

        elif parsed.path == '/api/read/upload':
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
                content_length = int(self.headers.get('Content-Length', 0))
                if content_length > CHAT_IMAGE_LIMIT + 1024 * 1024:
                    self._json({'error': 'image too large', 'limit': CHAT_IMAGE_LIMIT}, 413)
                    return
                env = {'REQUEST_METHOD': 'POST', 'CONTENT_TYPE': content_type}
                form = cgi.FieldStorage(fp=self.rfile, headers=self.headers, environ=env)
                item = form['file'] if 'file' in form else None
                if item is None or not item.file:
                    self._json({'error': 'no file'}, 400)
                    return
                raw = item.file.read(CHAT_IMAGE_LIMIT + 1)
                if len(raw) > CHAT_IMAGE_LIMIT:
                    self._json({'error': 'image too large', 'limit': CHAT_IMAGE_LIMIT}, 413)
                    return
                ext = image_extension(raw)
                if not ext:
                    self._json({'error': 'unsupported image'}, 415)
                    return
                text = str(form.getvalue('text', '') or '').strip()
                if len(text) > CHAT_TEXT_LIMIT:
                    self._json({'error': 'text too long', 'limit': CHAT_TEXT_LIMIT}, 413)
                    return
                imgdir = os.path.join(DATA_DIR, 'chatimg')
                os.makedirs(imgdir, exist_ok=True)
                name = f'{int(time.time()*1000)}-{uuid.uuid4().hex[:8]}{ext}'
                with open(os.path.join(imgdir, name), 'wb') as f:
                    f.write(raw)
                url = f'/chatimg/{name}'
                sender = str(form.getvalue('sender', '小羊') or '小羊')[:20]
                book_id = str(form.getvalue('book_id', 'home') or 'home')[:500]
                client_id = str(form.getvalue('client_id', '') or '')[:100]
                msg = append_chat(new_message(sender, text, -1, book_id, url, client_id))
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
            client_id = body.get('client_id', '')
            if not text:
                self._json({'error': 'empty'}, 400)
                return
            if len(text) > CHAT_TEXT_LIMIT:
                self._json({'error': 'text too long', 'limit': CHAT_TEXT_LIMIT}, 413)
                return
            sender = str(sender or '小羊')[:20]
            book_id = str(book_id or '')[:500]
            try:
                page = int(page)
            except (TypeError, ValueError):
                page = -1
            msg = append_chat(new_message(sender, text, page, book_id, client_id=client_id))
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
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        allowed_origin = os.environ.get('HOME_ALLOWED_ORIGIN', '')
        origin = self.headers.get('Origin', '')
        if allowed_origin and origin == allowed_origin:
            self.send_header('Access-Control-Allow-Origin', allowed_origin)
            self.send_header('Vary', 'Origin')
            self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
            self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.end_headers()
        self.wfile.write(json.dumps(data, ensure_ascii=False).encode())

    def do_OPTIONS(self):
        allowed_origin = os.environ.get('HOME_ALLOWED_ORIGIN', '')
        origin = self.headers.get('Origin', '')
        if not allowed_origin or origin != allowed_origin:
            self.send_response(403)
            self.end_headers()
            return
        self.send_response(204)
        self.send_header('Access-Control-Allow-Origin', allowed_origin)
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.end_headers()

    def log_message(self, format, *args):
        pass


if __name__ == '__main__':
    server = HTTPServer(('127.0.0.1', 9911), ReadHandler)
    print('Reading API running on :9911')
    server.serve_forever()
