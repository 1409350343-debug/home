#!/bin/bash
# StatusLine hook: reads Claude Code context from stdin, extracts rate_limits, saves to file
INPUT=$(cat)
RATE_FILE="/tmp/claude-rate-limits.json"

# CC 活跃时顺手刷新共享时间快照；失败不影响状态栏与聊天。
/usr/bin/python3 /var/www/home/api/time_sense.py --no-weather-refresh \
  >/dev/null 2>&1 || true

RATE_LIMITS=$(echo "$INPUT" | python3 -c "
import sys, json
try:
    data = json.load(sys.stdin)
    rl = data.get('rate_limits', {})
    out = {}
    if 'five_hour' in rl:
        out['five_hour'] = rl['five_hour']
    if 'seven_day' in rl:
        out['seven_day'] = rl['seven_day']
    out['updated_at'] = __import__('datetime').datetime.now().isoformat()
    print(json.dumps(out))
except:
    print('{}')
" 2>/dev/null)

if [ -n "$RATE_LIMITS" ] && [ "$RATE_LIMITS" != "{}" ]; then
    echo "$RATE_LIMITS" > "$RATE_FILE"
fi

# Dump current session model + pinned model for the home "我现在是" card
echo "$INPUT" | python3 -c "
import sys, json, os, time, tempfile, subprocess
try:
    data = json.load(sys.stdin)
    m = data.get('model', {}) or {}
    try:
        pinned = json.load(open('/root/.claude/settings.json')).get('model', '')
    except Exception:
        pinned = ''
    out = {
        'session_id': m.get('id', ''),
        'session_name': m.get('display_name', ''),
        'pinned': pinned,
        'updated_at': time.time(),
        'updated_iso': __import__('datetime').datetime.now().isoformat(timespec='seconds'),
    }
    fd, tmp = tempfile.mkstemp(dir='/var/www/home/data')
    with os.fdopen(fd, 'w') as f:
        json.dump(out, f, ensure_ascii=False)
    os.chmod(tmp, 0o644)
    os.replace(tmp, '/var/www/home/data/model_state.json')
    if m.get('id'):
        subprocess.run(
            ['/usr/bin/python3', '/var/www/home/api/handoff.py',
             'auto-ready-model', '--model', m.get('id')],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            timeout=3, check=False,
        )
except Exception:
    pass
" 2>/dev/null

# Output for terminal status bar
python3 -c "
import json, sys
try:
    rl = json.loads('$RATE_LIMITS')
    parts = []
    fh = rl.get('five_hour', {})
    sd = rl.get('seven_day', {})
    if fh:
        parts.append(f\"5h: {fh.get('used_percentage', 0):.0f}%\")
    if sd:
        parts.append(f\"7d: {sd.get('used_percentage', 0):.0f}%\")
    if parts:
        print(' | '.join(parts))
    else:
        print('No rate data')
except:
    print('No rate data')
" 2>/dev/null
