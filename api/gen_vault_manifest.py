#!/usr/bin/env python3
"""扫描 /var/www/home/vault/books 生成 manifest.json 供深读页面导航用"""
import json
import os
import re

VAULT = '/var/www/home/vault'
BOOKS = os.path.join(VAULT, 'books')


def chapter_title(book, ch, progress_text):
    m = re.search(rf'^[-\s\[\]x]*{ch}\s*[—-]\s*(.+?)(?:\s*·.*)?$', progress_text, re.M)
    if m:
        return m.group(1).strip()
    return ch


def first_heading(path):
    try:
        with open(path, encoding='utf-8') as f:
            for line in f:
                if line.startswith('#'):
                    return line.lstrip('#').strip()
    except OSError:
        pass
    return None


def main():
    manifest = {'books': []}
    if not os.path.isdir(BOOKS):
        raise SystemExit('no books dir')
    for book in sorted(os.listdir(BOOKS)):
        bdir = os.path.join(BOOKS, book)
        if not os.path.isdir(bdir):
            continue
        progress_text = ''
        ppath = os.path.join(bdir, 'progress.md')
        if os.path.exists(ppath):
            progress_text = open(ppath, encoding='utf-8').read()
        chapters = []
        for ch in sorted(os.listdir(bdir)):
            cdir = os.path.join(bdir, ch)
            if not os.path.isdir(cdir) or not re.match(r'ch\d+', ch):
                continue
            files = sorted(os.listdir(cdir))
            units = [f for f in files if re.match(r'\d+\.md$', f)]
            guide = '00-导读.md' if '00-导读.md' in files else None
            ready = bool(units)
            # 进度：progress.md 里该章是否勾选
            done = bool(re.search(rf'\[x\]\s*{ch}\b', progress_text))
            chapters.append({
                'id': ch,
                'title': chapter_title(book, ch, progress_text),
                'ready': ready,
                'done': done,
                'guide': guide,
                'units': units,
            })
        manifest['books'].append({
            'id': book,
            'title': f'《{book}》',
            'chapters': chapters,
        })
    out = os.path.join(VAULT, 'manifest.json')
    with open(out, 'w', encoding='utf-8') as f:
        json.dump(manifest, f, ensure_ascii=False)
    print(f'manifest: {out} ({sum(len(b["chapters"]) for b in manifest["books"])} chapters)')


if __name__ == '__main__':
    main()
