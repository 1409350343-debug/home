#!/usr/bin/env python3
"""CC/TG bridge heartbeat helper.

Existing Monitor can call:
  python3 api/chat_bridge.py heartbeat --state idle
  python3 api/chat_bridge.py heartbeat --state thinking --message-id MESSAGE_ID

It never sends or rewrites chat messages, so the current TG bridge stays intact.
"""
import argparse
import json
import os
import tempfile
import time


DATA_DIR = os.environ.get('HOME_READING_DATA_DIR', '/var/www/home/data/reading')
HEARTBEAT_FILE = os.path.join(DATA_DIR, 'cc_monitor_heartbeat.json')
TIME_STATE_FILE = os.environ.get('HOME_TIME_STATE', '/var/www/home/api/time_state.json')


def temporal_context():
    try:
        with open(TIME_STATE_FILE, encoding='utf-8') as f:
            state = json.load(f)
        return {
            'summary': state.get('ai_context', ''),
            'status': state.get('status', ''),
            'updated_at': state.get('updated_at', 0),
        }
    except (OSError, json.JSONDecodeError):
        return {}


def atomic_write(data):
    os.makedirs(DATA_DIR, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(prefix='.heartbeat-', suffix='.tmp', dir=DATA_DIR)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.chmod(tmp_path, 0o600)
        os.replace(tmp_path, HEARTBEAT_FILE)
    finally:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)


def main():
    parser = argparse.ArgumentParser(description='Update the CC/TG chat bridge heartbeat')
    sub = parser.add_subparsers(dest='command', required=True)
    heartbeat = sub.add_parser('heartbeat')
    heartbeat.add_argument('--state', choices=('idle', 'reading', 'thinking', 'replying', 'error'), default='idle')
    heartbeat.add_argument('--message-id', default='')
    heartbeat.add_argument('--channel', default='tg')
    sub.add_parser('status')
    args = parser.parse_args()

    if args.command == 'heartbeat':
        data = {
            'ts': time.time(),
            'state': args.state,
            'message_id': args.message_id,
            'channel': args.channel,
            'pid': os.getpid(),
            'temporal_context': temporal_context(),
        }
        atomic_write(data)
        print(json.dumps(data, ensure_ascii=False))
        return

    if os.path.exists(HEARTBEAT_FILE):
        with open(HEARTBEAT_FILE, encoding='utf-8') as f:
            print(json.dumps(json.load(f), ensure_ascii=False, indent=2))
    else:
        print(json.dumps({'online': False, 'reason': 'no heartbeat'}, ensure_ascii=False))


if __name__ == '__main__':
    main()
