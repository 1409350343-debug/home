#!/usr/bin/env python3
"""小窝共享时间感知。

把当地时刻、自然光、天气、季节和最近的作息事件合成一个稳定的
time_state.json。网页、Claude Code 与 TG Monitor 都只读这个快照，
不会改变原有聊天线路。
"""
import argparse
import json
import math
import os
import tempfile
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo


API_DIR = Path(__file__).resolve().parent
LAT = float(os.environ.get("HOME_LAT", "44.02"))
LON = float(os.environ.get("HOME_LON", "89.59"))
LOCATION = os.environ.get("HOME_LOCATION", "新疆奇台")
TIMEZONE_NAME = os.environ.get("HOME_TIMEZONE", "Asia/Shanghai")
LOCAL_TZ = ZoneInfo(TIMEZONE_NAME)
STATE_PATH = Path(os.environ.get("HOME_TIME_STATE", str(API_DIR / "time_state.json")))
WEATHER_PATH = Path(os.environ.get("HOME_WEATHER_FILE", "/var/www/home/data/weather.json"))
SENSE_PATH = Path(os.environ.get("HOME_SENSE_EVENTS", "/var/www/home/data/sense/events.jsonl"))
WEATHER_TTL = int(os.environ.get("HOME_WEATHER_TTL", "1200"))

WMO = {
    0: "晴", 1: "基本晴", 2: "多云", 3: "阴", 45: "雾", 48: "雾凇",
    51: "毛毛雨", 53: "小雨", 55: "中雨", 61: "小雨", 63: "中雨",
    65: "大雨", 71: "小雪", 73: "中雪", 75: "大雪", 80: "阵雨",
    81: "阵雨", 82: "强阵雨", 95: "雷阵雨", 96: "雷阵雨带雹",
    99: "雷阵雨带雹",
}


def read_json(path, default=None):
    try:
        with Path(path).open(encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {} if default is None else default


def atomic_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".time-", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.chmod(tmp, 0o644)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def calc_sun(lat, lon, day_of_year):
    decl = 23.45 * math.sin(math.radians(360 / 365 * (day_of_year - 81)))
    cos_ha = -math.tan(math.radians(lat)) * math.tan(math.radians(decl))
    ha = math.degrees(math.acos(max(-1, min(1, cos_ha))))
    solar_noon_utc = 12 - lon / 15
    return solar_noon_utc - ha / 15, solar_noon_utc, solar_noon_utc + ha / 15


def hours_to_hm(hours):
    hours %= 24
    return f"{int(hours):02d}:{int((hours % 1) * 60):02d}"


def fmt_countdown(hours):
    if hours < 0:
        return None
    whole = int(hours)
    minutes = int((hours - whole) * 60)
    return f"{whole}小时{minutes}分钟" if whole else f"{minutes}分钟"


def sky_for(hour, sunrise, sunset):
    dawn, morning_end = sunrise - .5, sunrise + 1
    noon_start = sunrise + (sunset - sunrise) * .35
    noon_end = sunrise + (sunset - sunrise) * .55
    afternoon_end, dusk_end = sunset - 1.5, sunset + .5
    if hour < dawn:
        return "deep_night", "🌑 深夜", "夜已经很深，周围安静下来", "#304330"
    if hour < sunrise:
        return "dawn", "🌅 黎明", "天边正在慢慢变亮，空气还带着凉意", "#738b73"
    if hour < morning_end:
        return "early_morning", "🌄 清晨", "太阳刚升起来，光线柔软", "#d6a85f"
    if hour < noon_start:
        return "morning", "☀️ 上午", "日光明亮，适合开始今天的事情", "#8fb17c"
    if hour < noon_end:
        return "noon", "🌞 正午", "太阳升得很高，白昼正盛", "#d4b45e"
    if hour < afternoon_end:
        return "afternoon", "🌤️ 下午", "光线渐斜，节奏慢慢沉下来", "#a7b47a"
    if hour < sunset:
        return "golden_hour", "🌇 黄金时刻", "天色转暖，日落正在靠近", "#d89963"
    if hour < dusk_end:
        return "dusk", "🌆 黄昏", "最后一点天光正在退去", "#8a7c78"
    return "night", "🌙 夜晚", "夜色已经落下，适合放松和陪伴", "#526c58"


def mood_for(phase):
    return {
        "deep_night": "困倦、安静、适合休息",
        "dawn": "半醒、轻声、慢慢醒来",
        "early_morning": "清醒、舒展、准备开始",
        "morning": "精神好、专注、适合做事",
        "noon": "稍懒、需要补充能量",
        "afternoon": "平稳、专注、偶尔走神",
        "golden_hour": "柔软、感性、想一起走走",
        "dusk": "安静、想靠近、说话变轻",
        "night": "放松、温柔、适合聊天",
    }.get(phase, "平稳")


def season_for(now):
    month = now.month
    if month in (3, 4, 5):
        name, scene = "春日", "草木返青，昼光渐长"
    elif month in (6, 7, 8):
        name, scene = "夏日", "白昼很长，空气和日光都有暖意"
    elif month in (9, 10, 11):
        name, scene = "秋日", "空气转凉，光线变得清透"
    else:
        name, scene = "冬日", "天亮得晚，夜晚来得早"
    return {"name": name, "scene": scene, "month": month}


def weather_from_api():
    query = urllib.parse.urlencode({
        "latitude": LAT,
        "longitude": LON,
        "current": "temperature_2m,apparent_temperature,weather_code,wind_speed_10m,relative_humidity_2m",
        "timezone": TIMEZONE_NAME,
    })
    with urllib.request.urlopen(
        f"https://api.open-meteo.com/v1/forecast?{query}", timeout=6
    ) as response:
        current = json.load(response)["current"]
    code = int(current.get("weather_code", -1))
    return {
        "place": LOCATION,
        "desc": WMO.get(code, "天气未知"),
        "temp": current.get("temperature_2m"),
        "feels": current.get("apparent_temperature"),
        "humidity": current.get("relative_humidity_2m"),
        "wind_kmh": current.get("wind_speed_10m"),
        "code": code,
        "source": "open-meteo",
        "updated_at": time.time(),
    }


def normalized_cached_weather():
    cached = read_json(WEATHER_PATH, {})
    if not cached:
        return {}
    if "now" in cached:
        now = cached.get("now") or {}
        return {
            "place": cached.get("place", LOCATION),
            "desc": now.get("desc", ""),
            "temp": now.get("temp"),
            "feels": now.get("feels"),
            "humidity": now.get("humidity"),
            "wind_kmh": now.get("wind_kmh"),
            "source": "weather-cache",
            "updated_at": WEATHER_PATH.stat().st_mtime if WEATHER_PATH.exists() else 0,
        }
    return cached


def get_weather(refresh=True):
    cached = normalized_cached_weather()
    fresh = cached and time.time() - float(cached.get("updated_at") or 0) < WEATHER_TTL
    if fresh or not refresh:
        return cached
    try:
        weather = weather_from_api()
        # 保留旧 get_weather.py 使用的数据文件格式，不反向覆盖它。
        return weather
    except Exception as exc:
        cached["stale"] = True
        cached["error"] = type(exc).__name__
        return cached


def recent_sense_events(limit=80):
    try:
        with SENSE_PATH.open(encoding="utf-8") as f:
            lines = f.readlines()[-limit:]
        return [json.loads(line) for line in lines if line.strip()]
    except (OSError, ValueError):
        return []


def routine_for(now):
    events = recent_sense_events()
    recent = [e for e in events if time.time() - float(e.get("ts") or 0) <= 18 * 3600]
    last_sleep = next((e for e in reversed(recent) if e.get("type") == "sleep"), None)
    last_wake = next((e for e in reversed(recent) if e.get("type") == "wake"), None)
    workout_start = next((e for e in reversed(recent) if e.get("type") == "workout_start"), None)
    workout_end = next((e for e in reversed(recent) if e.get("type") == "workout_end"), None)
    if last_sleep and (not last_wake or last_sleep.get("ts", 0) > last_wake.get("ts", 0)):
        state, hint = "sleeping", "小羊可能已经休息，回复应轻一点、少打扰"
    elif workout_start and (not workout_end or workout_start.get("ts", 0) > workout_end.get("ts", 0)):
        state, hint = "exercising", "小羊可能正在运动，先给简短回应"
    elif last_wake:
        state, hint = "awake", "小羊已经醒来，可以正常陪伴和交流"
    elif now.hour < 7:
        state, hint = "likely_sleeping", "没有收到作息事件；按时刻推测正在休息"
    elif now.hour >= 23:
        state, hint = "winding_down", "已经很晚，适合温和提醒休息"
    else:
        state, hint = "unknown", "没有足够的近期作息信号，不要擅自断言"
    last_event = recent[-1] if recent else None
    return {
        "state": state,
        "hint": hint,
        "last_event": {
            "type": last_event.get("type"),
            "value": last_event.get("value", ""),
            "ts": last_event.get("ts"),
        } if last_event else None,
    }


def build_context(state):
    clock, sky = state["clock"], state["sky"]
    weather, season, routine = state["weather"], state["season"], state["routine"]
    weather_text = ""
    if weather.get("desc"):
        temperature = f"{weather.get('temp')}℃" if weather.get("temp") is not None else ""
        weather_text = f"，当地{weather['desc']}{temperature}"
    return (
        f"现在是{clock['date']}{clock['weekday']} {clock['now']}，"
        f"{state['location']}的{sky['label'].split(' ', 1)[-1]}{weather_text}。"
        f"季节是{season['name']}。{routine['hint']}。"
        "这些信息只用于调整语气和时机；不确定的作息不得当作事实。"
    )


def generate(refresh_weather=True):
    now_utc = datetime.now(timezone.utc)
    now = now_utc.astimezone(LOCAL_TZ)
    sunrise_utc, _, sunset_utc = calc_sun(LAT, LON, now.timetuple().tm_yday)
    offset_hours = (now.utcoffset().total_seconds() / 3600) if now.utcoffset() else 0
    sunrise, sunset = sunrise_utc + offset_hours, sunset_utc + offset_hours
    local_hour = now.hour + now.minute / 60 + now.second / 3600
    phase, label, scene, color = sky_for(local_hour, sunrise, sunset)

    if sunrise <= local_hour <= sunset:
        progress = (local_hour - sunrise) / (sunset - sunrise)
        sun = f"在天上 · 日照进度 {progress:.0%}"
        countdown = f"距日落 {fmt_countdown(sunset - local_hour)}"
    else:
        sun = "在地平线以下"
        wait = sunrise - local_hour if local_hour < sunrise else sunrise + 24 - local_hour
        countdown = f"距{'日出' if local_hour < sunrise else '明天日出'} {fmt_countdown(wait)}"

    weather = get_weather(refresh_weather)
    season = season_for(now)
    routine = routine_for(now)
    mood = mood_for(phase)
    status = f"{label.split(' ')[0]} {label.split(' ', 1)[-1]} · {mood.split('、')[0]}"
    if routine["state"] == "sleeping":
        status = "🌙 安静陪着小羊休息"
    elif routine["state"] == "exercising":
        status = "🏃 小羊正在活动"

    state = {
        "schema_version": 2,
        "sky": {
            "phase": phase, "label": label, "scene": scene, "color": color,
            "sun": sun, "countdown": countdown, "mood": mood,
        },
        "clock": {
            "now": now.strftime("%H:%M"),
            "date": now.strftime("%Y年%m月%d日"),
            "date_key": now.strftime("%Y-%m-%d"),
            "weekday": ["周一", "周二", "周三", "周四", "周五", "周六", "周日"][now.weekday()],
            "timezone": TIMEZONE_NAME,
            "sunrise": hours_to_hm(sunrise),
            "sunset": hours_to_hm(sunset),
            "daylight": f"{sunset - sunrise:.1f}小时",
        },
        "weather": weather,
        "season": season,
        "routine": routine,
        "status": status,
        "location": LOCATION,
        "coordinates": {"lat": LAT, "lon": LON},
        "updated_at": now_utc.timestamp(),
        "updated_iso": now.isoformat(timespec="seconds"),
    }
    state["ai_context"] = build_context(state)
    atomic_json(STATE_PATH, state)
    return state


def pretty(state):
    s, c, w = state["sky"], state["clock"], state["weather"]
    weather = f"{w.get('desc', '天气未知')} {w.get('temp', '')}℃".strip()
    return "\n".join([
        "┌─── 小窝时间感知 ─────────────────┐",
        f"│ {c['date']} {c['weekday']} {c['now']} · {state['location']}",
        f"│ {s['label']} · {weather} · {state['season']['name']}",
        f"│ 日出 {c['sunrise']}  日落 {c['sunset']}  {s['countdown']}",
        f"│ 作息：{state['routine']['state']} · {state['routine']['hint']}",
        "└──────────────────────────────────┘",
    ])


def main():
    parser = argparse.ArgumentParser(description="Generate shared home time context")
    parser.add_argument("--context", action="store_true", help="只输出给 AI 的上下文")
    parser.add_argument("--json", action="store_true", help="输出完整 JSON")
    parser.add_argument("--watch", action="store_true", help="持续刷新状态")
    parser.add_argument("--interval", type=max_one, default=300)
    parser.add_argument("--no-weather-refresh", action="store_true")
    args = parser.parse_args()
    while True:
        state = generate(not args.no_weather_refresh)
        if args.context:
            print(state["ai_context"], flush=True)
        elif args.json:
            print(json.dumps(state, ensure_ascii=False, indent=2), flush=True)
        elif not args.watch:
            print(pretty(state))
        if not args.watch:
            break
        time.sleep(args.interval)


def max_one(value):
    return max(1, int(value))


if __name__ == "__main__":
    main()
