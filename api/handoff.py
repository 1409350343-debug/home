#!/usr/bin/env python3
"""Unified handoff coordinator for lifeline, CC sessions, model restarts and TG.

The lifeline remains stable long-term context. Each window change gets a private,
ephemeral handoff package. Old transcripts are archived only after the new
session explicitly confirms readiness.
"""
import argparse
import hashlib
import json
import os
import shutil
import tempfile
import time
import uuid
from datetime import datetime
from pathlib import Path


PROJECT_DIR = Path(os.environ.get(
    'HOME_CLAUDE_PROJECT_DIR',
    str(Path.home() / '.claude' / 'projects' / '-var-www-home-api'),
)).expanduser()
PUBLIC_STATE = Path(os.environ.get(
    'HOME_HANDOFF_PUBLIC_STATE',
    '/var/www/home/data/handoff_state.json',
)).expanduser()
STATE_FILE = Path(os.environ.get(
    'HOME_HANDOFF_STATE',
    str(PROJECT_DIR / 'handoff_state.json'),
)).expanduser()
PACKAGE_FILE = Path(os.environ.get(
    'HOME_HANDOFF_PACKAGE',
    str(PROJECT_DIR / 'handoff-current.json'),
)).expanduser()
ARCHIVE_DIR = PROJECT_DIR / 'archived_sessions'
FAILED_DIR = PROJECT_DIR / 'failed_handoffs'
CHAT_FILE = Path(os.environ.get(
    'HOME_CHAT_FILE',
    '/var/www/home/data/reading/chat.json',
)).expanduser()
TIME_STATE_FILE = Path(os.environ.get(
    'HOME_TIME_STATE',
    '/var/www/home/api/time_state.json',
)).expanduser()
DEFAULT_LIFELINES = (
    PROJECT_DIR / 'memory' / 'lifeline.md',
    Path('/root/.claude/projects/-root/memory/lifeline.md'),
)
PENDING_STATES = {'preparing', 'transcript_ready', 'starting', 'awaiting_ready'}


def now_iso():
    return datetime.now().astimezone().isoformat(timespec='seconds')


def atomic_json(path, data, mode=0o600):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix='.handoff-', suffix='.tmp', dir=str(path.parent))
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.chmod(tmp, mode)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def read_json(path, default=None):
    try:
        with open(path, encoding='utf-8') as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return {} if default is None else default


def canonical_lifeline():
    configured = os.environ.get('HOME_LIFELINE_FILE', '').strip()
    candidates = [Path(configured).expanduser()] if configured else list(DEFAULT_LIFELINES)
    return next((p for p in candidates if p.exists()), candidates[0])


def file_hash(path):
    try:
        return hashlib.sha256(Path(path).read_bytes()).hexdigest()
    except OSError:
        return ''


def text_from_event(event):
    message = event.get('message') or {}
    content = message.get('content') if isinstance(message, dict) else ''
    if isinstance(content, str):
        return content.strip()
    if not isinstance(content, list):
        return ''
    parts = []
    for block in content:
        if not isinstance(block, dict):
            continue
        if block.get('type') == 'text' and block.get('text'):
            parts.append(str(block['text']))
    return '\n'.join(parts).strip()


def recent_context(events, limit=8):
    items = []
    for event in events:
        if event.get('type') not in ('user', 'assistant'):
            continue
        text = text_from_event(event)
        if text:
            items.append({
                'role': event.get('type'),
                'text': text[-4000:],
                'uuid': event.get('uuid', ''),
            })
    return items[-limit:]


def pending_tools(events):
    used, done = {}, set()
    for event in events:
        content = (event.get('message') or {}).get('content', [])
        if not isinstance(content, list):
            continue
        for block in content:
            if not isinstance(block, dict):
                continue
            if block.get('type') == 'tool_use':
                used[block.get('id', '')] = block.get('name', '')
            elif block.get('type') == 'tool_result':
                done.add(block.get('tool_use_id', ''))
    return [{'id': key, 'name': name} for key, name in used.items() if key and key not in done]


def chat_cursor():
    messages = read_json(CHAT_FILE, [])
    if not isinstance(messages, list) or not messages:
        return {'last_id': '', 'last_ts': 0, 'waiting': False}
    last = messages[-1]
    user = next((m for m in reversed(messages) if m.get('sender') == '小羊'), None)
    reply = next((m for m in reversed(messages) if m.get('sender') != '小羊'), None)
    waiting = bool(user and (not reply or user.get('ts', 0) > reply.get('ts', 0)))
    return {'last_id': last.get('id', ''), 'last_ts': last.get('ts', 0), 'waiting': waiting}


def temporal_context():
    state = read_json(TIME_STATE_FILE, {})
    return {
        'summary': state.get('ai_context', ''),
        'status': state.get('status', ''),
        'updated_at': state.get('updated_at', 0),
    } if state else {}


def public_view(state):
    allowed = (
        'handoff_id', 'status', 'reason', 'old_session_id', 'new_session_id',
        'target_model', 'created_at', 'updated_at', 'ready_at', 'error',
        'lifeline_hash', 'chat_cursor',
    )
    return {key: state.get(key) for key in allowed if key in state}


def save_state(state):
    state['updated_at'] = now_iso()
    atomic_json(STATE_FILE, state)
    atomic_json(PUBLIC_STATE, public_view(state), mode=0o644)
    return state


def load_state():
    return read_json(STATE_FILE, {})


def pending():
    return load_state().get('status') in PENDING_STATES


def prepare(reason, old_session_id='', new_session_id='', target_model='',
            old_path='', new_path='', events=None, retain_tokens=0):
    current = load_state()
    if current.get('status') in PENDING_STATES:
        raise RuntimeError(f"handoff already pending: {current.get('handoff_id')}")
    lifeline = canonical_lifeline()
    state = {
        'handoff_id': str(uuid.uuid4()),
        'status': 'preparing',
        'reason': reason,
        'old_session_id': old_session_id,
        'new_session_id': new_session_id,
        'target_model': target_model,
        'old_path': str(old_path or ''),
        'new_path': str(new_path or ''),
        'retain_tokens': retain_tokens,
        'lifeline_path': str(lifeline),
        'lifeline_hash': file_hash(lifeline),
        'chat_cursor': chat_cursor(),
        'temporal_context': temporal_context(),
        'recent_context': recent_context(events or []),
        'pending_tools': pending_tools(events or []),
        'created_at': now_iso(),
        'error': '',
    }
    save_state(state)
    atomic_json(PACKAGE_FILE, state)
    return state


def mark_transcript_ready(new_path):
    state = load_state()
    if state.get('status') not in ('preparing', 'transcript_ready'):
        raise RuntimeError('no preparing handoff')
    state['new_path'] = str(new_path)
    state['status'] = 'transcript_ready'
    return save_state(state)


def mark_starting():
    state = load_state()
    if state.get('status') not in ('preparing', 'transcript_ready', 'starting'):
        raise RuntimeError('handoff is not ready to start')
    state['status'] = 'awaiting_ready'
    state['started_at'] = now_iso()
    return save_state(state)


def _archive(path, directory):
    path = Path(path)
    if not path.exists():
        return ''
    directory.mkdir(parents=True, exist_ok=True)
    dest = directory / path.name
    if dest.exists():
        dest = directory / f'{path.stem}-{int(time.time())}{path.suffix}'
    shutil.move(str(path), str(dest))
    return str(dest)


def confirm_ready(session_id='', model=''):
    state = load_state()
    if state.get('status') not in PENDING_STATES:
        return state
    expected = state.get('new_session_id', '')
    if expected and session_id and expected != session_id:
        raise RuntimeError('ready signal came from a different session')
    if expected and not session_id:
        raise RuntimeError('session id is required for transcript handoff')
    state['new_session_id'] = session_id or expected
    state['confirmed_model'] = model
    state['status'] = 'ready'
    state['ready_at'] = now_iso()
    old_path = state.get('old_path')
    if old_path:
        state['archived_old_path'] = _archive(old_path, ARCHIVE_DIR)
    return save_state(state)


def auto_ready_model(model):
    state = load_state()
    if state.get('status') not in PENDING_STATES or state.get('reason') != 'model_switch':
        return state
    expected = (state.get('target_model') or '').lower()
    actual = (model or '').lower()
    if expected and expected.split('[')[0] not in actual:
        return state
    return confirm_ready(model=model)


def rollback(error='handoff failed'):
    state = load_state()
    if state.get('status') not in PENDING_STATES:
        return state
    new_path = state.get('new_path')
    if new_path:
        state['failed_new_path'] = _archive(new_path, FAILED_DIR)
    state['status'] = 'rolled_back'
    state['error'] = error
    state['rolled_back_at'] = now_iso()
    return save_state(state)


def main():
    parser = argparse.ArgumentParser(description='Unified CC handoff coordinator')
    sub = parser.add_subparsers(dest='command', required=True)
    sub.add_parser('status')
    ready = sub.add_parser('ready')
    ready.add_argument('--session-id', default='')
    ready.add_argument('--model', default='')
    auto = sub.add_parser('auto-ready-model')
    auto.add_argument('--model', required=True)
    fail = sub.add_parser('rollback')
    fail.add_argument('--error', default='handoff failed')
    sub.add_parser('starting')
    args = parser.parse_args()
    if args.command == 'status':
        result = load_state()
    elif args.command == 'ready':
        result = confirm_ready(args.session_id, args.model)
    elif args.command == 'auto-ready-model':
        result = auto_ready_model(args.model)
    elif args.command == 'rollback':
        result = rollback(args.error)
    else:
        result = mark_starting()
    print(json.dumps(public_view(result), ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
