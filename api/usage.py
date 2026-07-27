#!/usr/bin/env python3
import json
import os
import glob
from collections import defaultdict
from datetime import datetime, timedelta
from http.server import HTTPServer, BaseHTTPRequestHandler

SESSIONS_BASE = '/root/.claude/projects/'
SESSION_WINDOW_HOURS = 5
RATE_LIMITS_FILE = '/tmp/claude-rate-limits.json'

def parse_all_entries():
    files = glob.glob(os.path.join(SESSIONS_BASE, '*', '*.jsonl'))
    entries = []
    for f in files:
        with open(f) as fh:
            for line in fh:
                try:
                    obj = json.loads(line)
                    if obj.get('type') == 'assistant' and 'message' in obj:
                        usage = obj['message'].get('usage', {})
                        ts = obj.get('timestamp', '')
                        if ts and usage.get('input_tokens'):
                            entries.append({
                                'timestamp': ts,
                                'input': usage.get('input_tokens', 0),
                                'output': usage.get('output_tokens', 0),
                                'cache_read': usage.get('cache_read_input_tokens', 0),
                                'cache_create': usage.get('cache_creation_input_tokens', 0),
                            })
                except:
                    pass
    return entries

def get_usage_data():
    entries = parse_all_entries()
    now = datetime.now()
    now_utc = datetime.utcnow()

    session_cutoff = (now_utc - timedelta(hours=SESSION_WINDOW_HOURS)).isoformat() + 'Z'

    # Weekly reset: Saturday 20:00 Beijing time = Saturday 12:00 UTC
    days_since_sat = (now.weekday() - 5) % 7
    last_saturday = now - timedelta(days=days_since_sat)
    last_saturday_reset = last_saturday.replace(hour=20, minute=0, second=0, microsecond=0)
    if last_saturday_reset > now:
        last_saturday_reset -= timedelta(weeks=1)
    week_cutoff_utc = (last_saturday_reset - timedelta(hours=8)).isoformat() + 'Z'

    next_saturday_reset = last_saturday_reset + timedelta(weeks=1)

    session_end = now_utc + timedelta(hours=SESSION_WINDOW_HOURS)

    session_tokens = {'input': 0, 'output': 0, 'cache_read': 0, 'cache_create': 0, 'calls': 0}
    weekly_tokens = {'input': 0, 'output': 0, 'cache_read': 0, 'cache_create': 0, 'calls': 0}
    daily = defaultdict(lambda: {'input': 0, 'output': 0, 'cache_read': 0, 'cache_create': 0, 'calls': 0})

    for e in entries:
        ts = e['timestamp']
        day = ts[:10]
        daily[day]['input'] += e['input']
        daily[day]['output'] += e['output']
        daily[day]['cache_read'] += e['cache_read']
        daily[day]['cache_create'] += e['cache_create']
        daily[day]['calls'] += 1

        if ts >= session_cutoff:
            session_tokens['input'] += e['input']
            session_tokens['output'] += e['output']
            session_tokens['cache_read'] += e['cache_read']
            session_tokens['cache_create'] += e['cache_create']
            session_tokens['calls'] += 1

        if ts >= week_cutoff_utc:
            weekly_tokens['input'] += e['input']
            weekly_tokens['output'] += e['output']
            weekly_tokens['cache_read'] += e['cache_read']
            weekly_tokens['cache_create'] += e['cache_create']
            weekly_tokens['calls'] += 1

    def calc_total(d):
        return d['input'] + d['output'] + d['cache_read'] + d['cache_create']

    # Session reset countdown
    oldest_in_session = None
    for e in entries:
        if e['timestamp'] >= session_cutoff:
            if oldest_in_session is None or e['timestamp'] < oldest_in_session:
                oldest_in_session = e['timestamp']

    if oldest_in_session:
        oldest_dt = datetime.fromisoformat(oldest_in_session.replace('Z', '+00:00').replace('+00:00', ''))
        session_resets_at = oldest_dt + timedelta(hours=SESSION_WINDOW_HOURS)
        session_resets_min = max(0, int((session_resets_at - now_utc).total_seconds() / 60))
    else:
        session_resets_min = SESSION_WINDOW_HOURS * 60

    # Weekly reset countdown
    weekly_resets_str = next_saturday_reset.strftime('%a %H:%M')
    weekly_resets_delta = next_saturday_reset - now
    weekly_resets_hours = max(0, int(weekly_resets_delta.total_seconds() / 3600))

    days_list = []
    for day_str in sorted(daily.keys()):
        d = daily[day_str]
        days_list.append({
            'date': day_str,
            'input_tokens': d['input'],
            'output_tokens': d['output'],
            'cache_read_tokens': d['cache_read'],
            'cache_create_tokens': d['cache_create'],
            'total_tokens': calc_total(d),
            'calls': d['calls']
        })

    official = {}
    try:
        if os.path.exists(RATE_LIMITS_FILE):
            with open(RATE_LIMITS_FILE) as rf:
                official = json.load(rf)
    except:
        pass

    return {
        'session': {
            'input_tokens': session_tokens['input'],
            'output_tokens': session_tokens['output'],
            'cache_read_tokens': session_tokens['cache_read'],
            'cache_create_tokens': session_tokens['cache_create'],
            'total_tokens': calc_total(session_tokens),
            'calls': session_tokens['calls'],
            'resets_in_min': session_resets_min,
            'window_hours': SESSION_WINDOW_HOURS,
        },
        'weekly': {
            'input_tokens': weekly_tokens['input'],
            'output_tokens': weekly_tokens['output'],
            'cache_read_tokens': weekly_tokens['cache_read'],
            'cache_create_tokens': weekly_tokens['cache_create'],
            'total_tokens': calc_total(weekly_tokens),
            'calls': weekly_tokens['calls'],
            'resets_str': weekly_resets_str,
            'resets_in_hours': weekly_resets_hours,
            'week_start': last_saturday_reset.strftime('%Y-%m-%d %H:%M'),
        },
        'daily': days_list,
        'official': official,
    }


class UsageHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        path = self.path.split('?')[0]
        if path == '/api/usage':
            data = get_usage_data()
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            self.wfile.write(json.dumps(data).encode())
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format, *args):
        pass


if __name__ == '__main__':
    server = HTTPServer(('127.0.0.1', 9903), UsageHandler)
    print('Usage API running on :9903')
    server.serve_forever()
