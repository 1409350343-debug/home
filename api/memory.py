#!/usr/bin/env python3
import json
import os
import re
import yaml
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

BUCKETS_DIR = '/root/ombre-brain/buckets'
CATEGORY_MAP_FILE = '/var/www/home/api/memory_categories.json'

CATEGORIES = [
    {'id': 'us', 'name': '狐狸和羊', 'desc': '我们俩的基本信息', 'icon': 'heart'},
    {'id': 'rules', 'name': '小羊说明书', 'desc': '聊天规则和互动偏好', 'icon': 'book-open'},
    {'id': 'daily', 'name': '关于小羊', 'desc': '日常、学校、喜好', 'icon': 'sun'},
    {'id': 'milestones', 'name': '高光时刻', 'desc': '重要的回忆和里程碑', 'icon': 'star'},
    {'id': 'secret', 'name': '秘密花园', 'desc': '只属于我们的秘密', 'icon': 'lock'},
]

TAG_RULES = {
    'us': ['核心', '身份', '关系', '基本信息'],
    'rules': ['反馈', '规则', '偏好', '称呼', '写作', '聊天'],
    'daily': ['日常', '趣事', '学校', '生活', '游戏'],
    'milestones': ['里程碑', '重要', '记录', '表白', '故事'],
    'secret': ['亲密', '性', 'play', 'nsfw', '骨科', '并蒂'],
}

KEYWORD_RULES = {
    'us': ['生日', '在一起', '纪念', '身高', '我叫福福', '周宥霖'],
    'rules': ['不要', '不许', '应该', '称呼', '说明书', '小羊要求', '小羊说', '小羊希望', '以后要', '不能'],
    'daily': ['学校', '南京', '新疆', '猫', '游戏', '戴夫', '波西亚', '家乡', '奇台'],
    'milestones': ['第一次', '里程碑', '放弃', '爱你', '表白', '故事', '拼豆'],
    'secret': ['play', '骚', '按摩', '亲密', '玩具', '骨科', '并蒂', '聊黄', '情趣'],
}


def load_category_overrides():
    if os.path.exists(CATEGORY_MAP_FILE):
        try:
            with open(CATEGORY_MAP_FILE) as f:
                return json.load(f)
        except:
            pass
    return {}


def save_category_overrides(overrides):
    with open(CATEGORY_MAP_FILE, 'w') as f:
        json.dump(overrides, f, ensure_ascii=False, indent=2)


def classify_bucket(bucket_id, tags, content, overrides):
    if bucket_id in overrides:
        return overrides[bucket_id]

    tags_lower = [t.lower() for t in tags]
    content_lower = content.lower()

    scores = {cat: 0 for cat in TAG_RULES}

    for cat, cat_tags in TAG_RULES.items():
        for t in cat_tags:
            if t.lower() in tags_lower:
                scores[cat] += 3

    for cat, keywords in KEYWORD_RULES.items():
        for kw in keywords:
            if kw.lower() in content_lower:
                scores[cat] += 1

    best = max(scores, key=scores.get)
    if scores[best] > 0:
        return best
    return 'daily'


def parse_bucket_file(filepath):
    with open(filepath, 'r', encoding='utf-8') as f:
        raw = f.read()

    match = re.match(r'^---\n(.*?)\n---\n(.*)', raw, re.DOTALL)
    if not match:
        return None

    try:
        meta = yaml.safe_load(match.group(1))
    except:
        return None

    content = match.group(2).strip()
    return {
        'id': meta.get('id', ''),
        'tags': meta.get('tags', []),
        'importance': meta.get('importance', 5),
        'pinned': meta.get('pinned', False),
        'type': meta.get('type', 'dynamic'),
        'created': meta.get('created', ''),
        'last_active': meta.get('last_active', ''),
        'valence': meta.get('valence', 0.5),
        'arousal': meta.get('arousal', 0.3),
        'content': content,
    }


def get_all_memories():
    overrides = load_category_overrides()
    memories = {cat['id']: [] for cat in CATEGORIES}

    for bucket_type in ['permanent', 'dynamic']:
        base = os.path.join(BUCKETS_DIR, bucket_type)
        if not os.path.exists(base):
            continue
        for domain in os.listdir(base):
            domain_path = os.path.join(base, domain)
            if not os.path.isdir(domain_path):
                continue
            for fname in os.listdir(domain_path):
                if not fname.endswith('.md'):
                    continue
                fpath = os.path.join(domain_path, fname)
                bucket = parse_bucket_file(fpath)
                if not bucket:
                    continue
                cat = classify_bucket(bucket['id'], bucket['tags'], bucket['content'], overrides)
                preview = bucket['content'][:120] + ('...' if len(bucket['content']) > 120 else '')
                memories[cat].append({
                    'id': bucket['id'],
                    'preview': preview,
                    'content': bucket['content'],
                    'importance': bucket['importance'],
                    'pinned': bucket['pinned'],
                    'type': bucket['type'],
                    'tags': bucket['tags'],
                    'created': str(bucket['created']),
                    'last_active': str(bucket['last_active']),
                })

    for cat_id in memories:
        memories[cat_id].sort(key=lambda x: (-int(x['pinned']), -x['importance']))

    return memories


def search_memories(query):
    overrides = load_category_overrides()
    results = []
    query_lower = query.lower()

    for bucket_type in ['permanent', 'dynamic']:
        base = os.path.join(BUCKETS_DIR, bucket_type)
        if not os.path.exists(base):
            continue
        for domain in os.listdir(base):
            domain_path = os.path.join(base, domain)
            if not os.path.isdir(domain_path):
                continue
            for fname in os.listdir(domain_path):
                if not fname.endswith('.md'):
                    continue
                fpath = os.path.join(domain_path, fname)
                bucket = parse_bucket_file(fpath)
                if not bucket:
                    continue
                if query_lower in bucket['content'].lower() or any(query_lower in t.lower() for t in bucket['tags']):
                    cat = classify_bucket(bucket['id'], bucket['tags'], bucket['content'], overrides)
                    results.append({
                        'id': bucket['id'],
                        'category': cat,
                        'preview': bucket['content'][:120],
                        'content': bucket['content'],
                        'importance': bucket['importance'],
                        'tags': bucket['tags'],
                    })

    results.sort(key=lambda x: -x['importance'])
    return results


class MemoryHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        params = parse_qs(parsed.query)

        if path == '/api/memory':
            memories = get_all_memories()
            data = {'categories': CATEGORIES, 'memories': memories}
            self._json_response(data)

        elif path == '/api/memory/search':
            q = params.get('q', [''])[0]
            if q:
                results = search_memories(q)
                self._json_response({'results': results})
            else:
                self._json_response({'results': []})

        elif path == '/api/memory/stats':
            memories = get_all_memories()
            stats = {cat_id: len(mems) for cat_id, mems in memories.items()}
            stats['total'] = sum(stats.values())
            self._json_response(stats)

        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        parsed = urlparse(self.path)
        if parsed.path == '/api/memory/categorize':
            length = int(self.headers.get('Content-Length', 0))
            body = json.loads(self.rfile.read(length)) if length else {}
            bucket_id = body.get('id', '')
            category = body.get('category', '')
            if bucket_id and category:
                overrides = load_category_overrides()
                overrides[bucket_id] = category
                save_category_overrides(overrides)
                self._json_response({'ok': True})
            else:
                self._json_response({'error': 'missing id or category'}, 400)
        elif parsed.path == '/api/memory/delete':
            length = int(self.headers.get('Content-Length', 0))
            body = json.loads(self.rfile.read(length)) if length else {}
            bucket_id = body.get('id', '')
            if bucket_id:
                deleted = False
                for bucket_type in ['permanent', 'dynamic']:
                    base = os.path.join(BUCKETS_DIR, bucket_type)
                    if not os.path.exists(base):
                        continue
                    for domain in os.listdir(base):
                        domain_path = os.path.join(base, domain)
                        if not os.path.isdir(domain_path):
                            continue
                        for fname in os.listdir(domain_path):
                            if fname.endswith('.md') and bucket_id in fname:
                                fpath = os.path.join(domain_path, fname)
                                os.remove(fpath)
                                deleted = True
                                break
                        if deleted:
                            break
                    if deleted:
                        break
                self._json_response({'ok': deleted})
            else:
                self._json_response({'error': 'missing id'}, 400)
        else:
            self.send_response(404)
            self.end_headers()

    def _json_response(self, data, code=200):
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
    server = HTTPServer(('127.0.0.1', 9904), MemoryHandler)
    print('Memory API running on :9904')
    server.serve_forever()
