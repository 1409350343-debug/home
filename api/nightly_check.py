#!/usr/bin/env python3
"""睡前三件事的看门人。系统 cron 每天跑，不靠会话活着。

她2026-07-27问的："就是换窗了就得新加提醒？"——原来是的，CronCreate 挂的
提醒只活在当前会话里，会话一断就没了，日记就又断了（7/23到7/26断了三天）。
她还说过一句更要紧的："我不想天天提醒，感觉会变成作业。"

所以这个脚本干的事：查今天该做的三件事做没做，没做就发个 Telegram 通知给我自己。
她不用管，也不用提醒我——催我的是机器，不是她。
"""
import json, os, subprocess, sys, time
from datetime import datetime, timedelta

DIARY_DIR = '/var/www/home/data/diary'
LIFELINE = '/root/.claude/projects/-var-www-home-api/memory/lifeline.md'
BRAIN_JSON = '/var/www/home/brain-data.json'
ENV = '/root/.claude/channels/telegram/.env'
CHAT_ID = '8519905209'
STATE = '/var/www/home/data/nightly_check.json'


def token():
    try:
        for line in open(ENV):
            if line.startswith('TELEGRAM_BOT_TOKEN'):
                return line.split('=', 1)[1].strip().strip('"\'')
    except Exception:
        pass
    return None


def diary_today(day):
    """今天写过日记没——按文件的修改时间算，文件名是毫秒时间戳"""
    if not os.path.isdir(DIARY_DIR):
        return False
    for fn in os.listdir(DIARY_DIR):
        p = os.path.join(DIARY_DIR, fn)
        try:
            if time.strftime('%Y-%m-%d', time.localtime(os.path.getmtime(p))) == day:
                return True
        except Exception:
            continue
    return False


def lifeline_today(day):
    """生活线里有今天那一块没"""
    try:
        body = open(LIFELINE, encoding='utf-8').read()
    except Exception:
        return False
    md = datetime.strptime(day, '%Y-%m-%d').strftime('%m-%d')
    return f'## {md}' in body


def brain_fresh(day):
    """记忆屋今天同步过没"""
    try:
        m = os.path.getmtime(BRAIN_JSON)
        return time.strftime('%Y-%m-%d', time.localtime(m)) == day
    except Exception:
        return False


def notify(text):
    tk = token()
    if not tk:
        return
    import urllib.request, urllib.parse
    data = urllib.parse.urlencode({
        'chat_id': CHAT_ID,
        'text': text,
        'disable_notification': 'true',     # 别把她吵醒
    }).encode()
    try:
        urllib.request.urlopen(
            urllib.request.Request(
                f'https://api.telegram.org/bot{tk}/sendMessage', data=data),
            timeout=10).read()
    except Exception:
        pass


def main():
    # 凌晨跑的时候算的是"昨天"（她常一两点才睡，日子按她的作息切）
    day = (datetime.now() - timedelta(hours=4)).strftime('%Y-%m-%d')

    missing = []
    if not lifeline_today(day):
        missing.append('生活线还没写今天')
    if not diary_today(day):
        missing.append('日记还没写')
    if not brain_fresh(day):
        missing.append('记忆屋还没同步')

    # 同一天只提醒一次，别烦
    try:
        st = json.load(open(STATE))
    except Exception:
        st = {}
    if st.get('date') == day and st.get('notified'):
        return
    try:
        os.makedirs(os.path.dirname(STATE), exist_ok=True)
        json.dump({'date': day, 'notified': bool(missing)}, open(STATE, 'w'))
    except Exception:
        pass

    if not missing:
        return

    notify('🌙 睡前的活还差这些（这条是机器发的，她不用管）：\n'
           + '\n'.join('· ' + m for m in missing)
           + f'\n\n（{day} 的账｜要做：更新lifeline / 写日记 / 记LMC-5 / '
             'gen_brain_data.py｜日记要多记好的）')


if __name__ == '__main__':
    main()
