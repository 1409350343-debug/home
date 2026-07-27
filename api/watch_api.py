#!/usr/bin/env python3
"""共影 API — CoveWatch Phase 1: subtitle-based co-watching."""
import json, os, re, sqlite3, subprocess, glob, time, threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

DB = '/var/www/home/api/watch.db'
SUB_DIR = '/var/www/home/data/watch/subs'
PORT = 9917


def get_db():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA journal_mode=WAL')
    return conn


def init_db():
    os.makedirs(SUB_DIR, exist_ok=True)
    conn = get_db()
    conn.executescript('''
        CREATE TABLE IF NOT EXISTS videos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            url TEXT NOT NULL,
            title TEXT DEFAULT '',
            embed_url TEXT DEFAULT '',
            platform TEXT DEFAULT '',
            vid TEXT DEFAULT '',
            sub_count INTEGER DEFAULT 0,
            sub_lang TEXT DEFAULT '',
            status TEXT DEFAULT 'pending',
            added_at REAL
        );
        CREATE TABLE IF NOT EXISTS subs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            video_id INTEGER NOT NULL,
            seq INTEGER,
            start_ms INTEGER,
            end_ms INTEGER,
            text TEXT,
            FOREIGN KEY(video_id) REFERENCES videos(id)
        );
        CREATE INDEX IF NOT EXISTS idx_subs_video ON subs(video_id, start_ms);
    ''')
    conn.close()


def resolve_short_url(url):
    """Follow redirects for short URLs like b23.tv."""
    try:
        r = subprocess.run(
            ['curl', '-sI', '-L', '-o', '/dev/null', '-w', '%{url_effective}', url],
            capture_output=True, text=True, timeout=15
        )
        if r.returncode == 0 and r.stdout.strip():
            return r.stdout.strip()
    except Exception:
        pass
    return url


def detect_platform(url):
    if 'b23.tv/' in url:
        url = resolve_short_url(url)
    yt = re.search(r'(?:youtube\.com/watch\?v=|youtu\.be/|youtube\.com/embed/)([a-zA-Z0-9_-]{11})', url)
    if yt:
        vid = yt.group(1)
        return 'youtube', vid, f'https://www.youtube.com/embed/{vid}?enablejsapi=1&rel=0'
    bv = re.search(r'(BV[a-zA-Z0-9]{10})', url)
    if bv:
        bvid = bv.group(1)
        return 'bilibili', bvid, f'https://player.bilibili.com/player.html?bvid={bvid}&autoplay=0'
    return 'other', '', ''


def parse_srt(text):
    blocks = re.split(r'\n\n+', text.strip())
    out = []
    for block in blocks:
        lines = block.strip().split('\n')
        if len(lines) < 2:
            continue
        ts_line = None
        text_start = 0
        for i, ln in enumerate(lines):
            if '-->' in ln:
                ts_line = ln
                text_start = i + 1
                break
        if not ts_line:
            continue
        m = re.match(r'(\d+):(\d+):(\d+)[,.](\d+)\s*-->\s*(\d+):(\d+):(\d+)[,.](\d+)', ts_line)
        if not m:
            m2 = re.match(r'(\d+):(\d+)[,.](\d+)\s*-->\s*(\d+):(\d+)[,.](\d+)', ts_line)
            if not m2:
                continue
            g = m2.groups()
            s = int(g[0])*60000 + int(g[1])*1000 + int(g[2])
            e = int(g[3])*60000 + int(g[4])*1000 + int(g[5])
        else:
            g = m.groups()
            s = int(g[0])*3600000 + int(g[1])*60000 + int(g[2])*1000 + int(g[3])
            e = int(g[4])*3600000 + int(g[5])*60000 + int(g[6])*1000 + int(g[7])
        body = re.sub(r'<[^>]+>', '', '\n'.join(lines[text_start:]).strip())
        if body:
            out.append((len(out)+1, s, e, body))
    return out


def fetch_bili_subs(bvid, video_db_id):
    """Fetch bilibili subtitles via API."""
    import urllib.request
    conn = get_db()
    try:
        # Get video info
        api = f'https://api.bilibili.com/x/web-interface/view?bvid={bvid}'
        req = urllib.request.Request(api)
        req.add_header('User-Agent', 'Mozilla/5.0')
        resp = urllib.request.urlopen(req, timeout=15)
        info = json.loads(resp.read())
        data = info.get('data', {})
        title = data.get('title', '')
        cid = data.get('cid', '')

        # Try player API for subtitles
        subs_data = []
        if cid:
            papi = f'https://api.bilibili.com/x/player/v2?bvid={bvid}&cid={cid}'
            req2 = urllib.request.Request(papi)
            req2.add_header('User-Agent', 'Mozilla/5.0')
            resp2 = urllib.request.urlopen(req2, timeout=15)
            pinfo = json.loads(resp2.read())
            subtitle_list = pinfo.get('data', {}).get('subtitle', {}).get('subtitles', [])
            for sub_entry in subtitle_list:
                sub_url = sub_entry.get('subtitle_url', '')
                if sub_url:
                    if sub_url.startswith('//'):
                        sub_url = 'https:' + sub_url
                    req3 = urllib.request.Request(sub_url)
                    req3.add_header('User-Agent', 'Mozilla/5.0')
                    resp3 = urllib.request.urlopen(req3, timeout=15)
                    sub_json = json.loads(resp3.read())
                    for item in sub_json.get('body', []):
                        start_ms = int(float(item.get('from', 0)) * 1000)
                        end_ms = int(float(item.get('to', 0)) * 1000)
                        content = item.get('content', '').strip()
                        if content:
                            subs_data.append((len(subs_data)+1, start_ms, end_ms, content))
                    if subs_data:
                        break

        lang = 'zh' if subs_data else ''
        conn.execute('DELETE FROM subs WHERE video_id=?', (video_db_id,))
        if subs_data:
            conn.executemany(
                'INSERT INTO subs (video_id,seq,start_ms,end_ms,text) VALUES (?,?,?,?,?)',
                [(video_db_id, sq, s, e, t) for sq, s, e, t in subs_data]
            )
        conn.execute(
            'UPDATE videos SET title=?, sub_count=?, sub_lang=?, status=? WHERE id=?',
            (title, len(subs_data), lang, 'ready' if subs_data else 'no_subs', video_db_id)
        )
        conn.commit()
    except Exception as ex:
        conn.execute('UPDATE videos SET status=? WHERE id=?', (f'error:{ex}', video_db_id))
        conn.commit()
    finally:
        conn.close()


def fetch_subs(url, vid, video_db_id):
    """Run yt-dlp to fetch subtitles, store in DB. Runs in background thread."""
    conn = get_db()
    try:
        out_dir = os.path.join(SUB_DIR, vid or str(video_db_id))
        os.makedirs(out_dir, exist_ok=True)

        cmd = [
            '/usr/local/bin/yt-dlp',
            '--write-sub', '--write-auto-sub',
            '--sub-lang', 'zh,zh-Hans,zh-CN,zh-TW,en',
            '--sub-format', 'srt/vtt/best',
            '--skip-download', '--no-warnings',
            '-o', os.path.join(out_dir, '%(id)s.%(ext)s'),
            url
        ]
        subprocess.run(cmd, capture_output=True, text=True, timeout=120)

        title_cmd = ['/usr/local/bin/yt-dlp', '--get-title', '--no-warnings', url]
        tr = subprocess.run(title_cmd, capture_output=True, text=True, timeout=30)
        title = tr.stdout.strip() if tr.returncode == 0 else ''

        sub_files = sorted(
            glob.glob(os.path.join(out_dir, '*.srt')) +
            glob.glob(os.path.join(out_dir, '*.vtt'))
        )

        best_subs = []
        lang = ''
        for sf in sub_files:
            raw = open(sf, encoding='utf-8', errors='replace').read()
            if 'WEBVTT' in raw[:20]:
                raw = re.sub(r'^WEBVTT.*?\n\n', '', raw, count=1, flags=re.S)
            parsed = parse_srt(raw)
            if not parsed:
                continue
            fn = os.path.basename(sf).lower()
            is_zh = any(x in fn for x in ['zh', 'chi', 'cmn'])
            if is_zh or not best_subs:
                best_subs = parsed
                lang = 'zh' if is_zh else 'en'

        # Deduplicate consecutive identical lines
        deduped = []
        prev = ''
        for seq, s, e, txt in best_subs:
            if txt != prev:
                deduped.append((len(deduped)+1, s, e, txt))
                prev = txt

        conn.execute('DELETE FROM subs WHERE video_id=?', (video_db_id,))
        conn.executemany(
            'INSERT INTO subs (video_id,seq,start_ms,end_ms,text) VALUES (?,?,?,?,?)',
            [(video_db_id, sq, s, e, t) for sq, s, e, t in deduped]
        )
        conn.execute(
            'UPDATE videos SET title=?, sub_count=?, sub_lang=?, status=? WHERE id=?',
            (title, len(deduped), lang, 'ready' if deduped else 'no_subs', video_db_id)
        )
        conn.commit()
    except Exception as ex:
        conn.execute('UPDATE videos SET status=? WHERE id=?', (f'error:{ex}', video_db_id))
        conn.commit()
    finally:
        conn.close()


def ms_to_ts(ms):
    s = ms // 1000
    return f'{s//3600:02d}:{(s%3600)//60:02d}:{s%60:02d}'


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        p = urlparse(self.path)
        qs = parse_qs(p.query)

        if p.path == '/api/watch/list':
            conn = get_db()
            rows = conn.execute(
                'SELECT id,url,title,embed_url,platform,vid,sub_count,sub_lang,status,added_at '
                'FROM videos ORDER BY id DESC'
            ).fetchall()
            conn.close()
            self._json([dict(r) for r in rows])

        elif p.path == '/api/watch/subs':
            vid = qs.get('id', [''])[0]
            if not vid:
                return self._json({'error': 'need id'}, 400)
            conn = get_db()
            rows = conn.execute(
                'SELECT seq,start_ms,end_ms,text FROM subs WHERE video_id=? ORDER BY start_ms',
                (vid,)
            ).fetchall()
            conn.close()
            self._json([dict(r) for r in rows])

        elif p.path == '/api/watch/window':
            vid = qs.get('id', [''])[0]
            t = int(qs.get('t', ['0'])[0])
            win = int(qs.get('win', ['120000'])[0])
            if not vid:
                return self._json({'error': 'need id'}, 400)
            conn = get_db()
            rows = conn.execute(
                'SELECT seq,start_ms,end_ms,text FROM subs '
                'WHERE video_id=? AND end_ms>=? AND start_ms<=? ORDER BY start_ms',
                (vid, t - win, t + win)
            ).fetchall()
            conn.close()
            self._json([dict(r) for r in rows])

        elif p.path == '/api/watch/context':
            vid = qs.get('id', [''])[0]
            t = int(qs.get('t', ['0'])[0])
            win = int(qs.get('win', ['180000'])[0])
            if not vid:
                return self._json({'error': 'need id'}, 400)
            conn = get_db()
            video = conn.execute('SELECT title FROM videos WHERE id=?', (vid,)).fetchone()
            rows = conn.execute(
                'SELECT start_ms,text FROM subs '
                'WHERE video_id=? AND end_ms>=? AND start_ms<=? ORDER BY start_ms',
                (vid, t - win, t + win)
            ).fetchall()
            conn.close()
            title = video['title'] if video else ''
            lines = [f'[{ms_to_ts(r["start_ms"])}] {r["text"]}' for r in rows]
            ctx = f'正在看《{title}》，当前 {ms_to_ts(t)} 附近的字幕：\n' + '\n'.join(lines)
            self._json({'context': ctx, 'title': title, 'line_count': len(lines)})

        else:
            self._json({'error': 'not found'}, 404)

    def do_POST(self):
        length = int(self.headers.get('Content-Length', 0))
        body = json.loads(self.rfile.read(length)) if length else {}

        if self.path == '/api/watch/add':
            url = body.get('url', '').strip()
            if not url:
                return self._json({'error': 'need url'}, 400)
            platform, vid, embed_url = detect_platform(url)
            if not embed_url:
                return self._json({'error': f'暂不支持这个平台，目前支持YouTube和B站'}, 400)
            conn = get_db()
            cur = conn.execute(
                'INSERT INTO videos (url,embed_url,platform,vid,status,added_at) VALUES (?,?,?,?,?,?)',
                (url, embed_url, platform, vid, 'fetching', time.time())
            )
            db_id = cur.lastrowid
            conn.commit()
            conn.close()
            if platform == 'bilibili':
                threading.Thread(target=fetch_bili_subs, args=(vid, db_id), daemon=True).start()
            else:
                threading.Thread(target=fetch_subs, args=(url, vid, db_id), daemon=True).start()
            self._json({'id': db_id, 'status': 'fetching', 'embed_url': embed_url})

        elif self.path == '/api/watch/delete':
            vid = body.get('id')
            if not vid:
                return self._json({'error': 'need id'}, 400)
            conn = get_db()
            conn.execute('DELETE FROM subs WHERE video_id=?', (vid,))
            conn.execute('DELETE FROM videos WHERE id=?', (vid,))
            conn.commit()
            conn.close()
            self._json({'ok': True})

        else:
            self._json({'error': 'not found'}, 404)

    def _json(self, data, code=200):
        out = json.dumps(data, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET,POST,OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.end_headers()
        self.wfile.write(out)

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET,POST,OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.end_headers()

    def log_message(self, fmt, *args):
        pass


if __name__ == '__main__':
    init_db()
    srv = HTTPServer(('127.0.0.1', PORT), Handler)
    print(f'CoveWatch API on :{PORT}')
    srv.serve_forever()
