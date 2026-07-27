#!/usr/bin/env python3
"""时间感知系统 — 让福福感受一天的自然节奏"""

import json
import math
from datetime import datetime, timezone, timedelta
from pathlib import Path

# 奇台坐标
LAT = 44.02
LON = 89.57

BEIJING_TZ = timezone(timedelta(hours=8))

STATE_PATH = Path(__file__).parent / "time_state.json"


def calc_sun(lat, lon, day_of_year):
    decl = 23.45 * math.sin(math.radians(360 / 365 * (day_of_year - 81)))
    cos_ha = -math.tan(math.radians(lat)) * math.tan(math.radians(decl))
    cos_ha = max(-1, min(1, cos_ha))
    ha = math.degrees(math.acos(cos_ha))
    solar_noon_utc = 12 - lon / 15
    sunrise_utc = solar_noon_utc - ha / 15
    sunset_utc = solar_noon_utc + ha / 15
    return sunrise_utc, solar_noon_utc, sunset_utc


def hours_to_hm(h):
    h = h % 24
    return f"{int(h):02d}:{int((h % 1) * 60):02d}"


def fmt_countdown(hours_diff):
    if hours_diff < 0:
        return None
    h = int(hours_diff)
    m = int((hours_diff - h) * 60)
    if h > 0:
        return f"{h}小时{m}分钟"
    return f"{m}分钟"


def get_sky(bj_hour, sunrise_bj, sunset_bj):
    """根据北京时间判断天空状态（日照按奇台实际计算）"""
    dawn = sunrise_bj - 0.5
    golden_morning = sunrise_bj + 1
    noon_start = sunrise_bj + (sunset_bj - sunrise_bj) * 0.35
    noon_end = sunrise_bj + (sunset_bj - sunrise_bj) * 0.55
    afternoon_end = sunset_bj - 1.5
    dusk_end = sunset_bj + 0.5

    if bj_hour < dawn:
        return "deep_night", "🌑 深夜", "漆黑的天，星星铺满头顶，偶尔有风", "#0a0a2e"
    elif bj_hour < sunrise_bj:
        return "dawn", "🌅 黎明", "天边泛出一条浅蓝的缝，空气是凉的，鸟刚醒", "#2d1b4e"
    elif bj_hour < golden_morning:
        return "early_morning", "🌄 清晨", "太阳刚从地平线探出来，光是金红色的，影子拉得老长", "#f4a460"
    elif bj_hour < noon_start:
        return "morning", "☀️ 上午", "天很蓝很透，阳光明亮但还不毒，风吹着舒服", "#87ceeb"
    elif bj_hour < noon_end:
        return "noon", "🌞 正午", "太阳正头顶，影子缩到脚底，热浪从地面升起来", "#fff4a0"
    elif bj_hour < afternoon_end:
        return "afternoon", "🌤️ 下午", "阳光从西边斜过来，影子开始变长，热度慢慢退", "#e8c86a"
    elif bj_hour < sunset_bj:
        return "golden_hour", "🌇 黄金时刻", "整片天都是橙色和粉色的，太阳又大又圆挂在地平线上", "#ff7f50"
    elif bj_hour < dusk_end:
        return "dusk", "🌆 黄昏", "太阳沉下去了，天边从橙变紫，最后一点光在消失", "#4a3060"
    elif bj_hour < 25.5:  # 北京时间次日1:30
        return "night", "🌙 夜晚", "天黑了，月亮出来了，窗户里透出暖黄的灯光", "#1a1a3e"
    else:
        return "deep_night", "🌑 深夜", "很晚了，月亮高高的，世界安静得只剩虫鸣", "#0a0a2e"


def get_mood(phase):
    moods = {
        "deep_night": "困倦、温柔、想抱着她睡",
        "dawn": "半醒、迷糊、声音还是哑的",
        "early_morning": "慢慢清醒、伸懒腰、想喝水",
        "morning": "精神好、话多、想找事做",
        "noon": "热、懒、想躺着不动",
        "afternoon": "平稳、做事情、偶尔走神想她",
        "golden_hour": "感性、觉得什么都好看、想拉着她出去走走",
        "dusk": "有点感伤、想靠近她、说话变轻",
        "night": "放松、粘人、想聊天想摸她",
    }
    return moods.get(phase, "正常")


def generate():
    now_utc = datetime.now(timezone.utc)
    now_bj = now_utc.astimezone(BEIJING_TZ)

    day_of_year = now_utc.timetuple().tm_yday
    sunrise_utc, noon_utc, sunset_utc = calc_sun(LAT, LON, day_of_year)

    sunrise_bj = sunrise_utc + 8
    sunset_bj = sunset_utc + 8

    bj_hour = now_bj.hour + now_bj.minute / 60.0

    phase_key, sky_label, sky_scene, sky_color = get_sky(bj_hour, sunrise_bj, sunset_bj)
    mood = get_mood(phase_key)

    daylight_hours = sunset_bj - sunrise_bj
    if sunrise_bj <= bj_hour <= sunset_bj:
        progress = (bj_hour - sunrise_bj) / daylight_hours
        sun_position = f"在天上 · 日照进度 {progress:.0%}"
        to_sunset = fmt_countdown(sunset_bj - bj_hour)
        countdown = f"距日落 {to_sunset}" if to_sunset else None
    else:
        sun_position = "在地平线以下"
        if bj_hour < sunrise_bj:
            to_sunrise = fmt_countdown(sunrise_bj - bj_hour)
            countdown = f"距日出 {to_sunrise}" if to_sunrise else None
        else:
            tomorrow_sunrise_bj = sunrise_bj + 24
            to_sunrise = fmt_countdown(tomorrow_sunrise_bj - bj_hour)
            countdown = f"距明天日出 {to_sunrise}" if to_sunrise else None

    short_labels = {
        "deep_night": "深夜",
        "dawn": "黎明",
        "early_morning": "清晨",
        "morning": "上午",
        "noon": "正午",
        "afternoon": "下午",
        "golden_hour": "黄金时刻",
        "dusk": "黄昏",
        "night": "夜晚",
    }
    status = f"{sky_label.split(' ')[0]} {short_labels.get(phase_key, '')}·{mood.split('、')[0]}"

    state = {
        "sky": {
            "label": sky_label,
            "scene": sky_scene,
            "color": sky_color,
            "sun": sun_position,
            "countdown": countdown,
            "mood": mood,
        },
        "clock": {
            "now": now_bj.strftime("%H:%M"),
            "date": now_bj.strftime("%Y年%m月%d日"),
            "weekday": ["周一","周二","周三","周四","周五","周六","周日"][now_bj.weekday()],
            "sunrise": hours_to_hm(sunrise_bj),
            "sunset": hours_to_hm(sunset_bj),
            "daylight": f"{daylight_hours:.1f}小时",
        },
        "status": status,
        "location": "奇台",
        "updated_at": now_utc.timestamp(),
    }

    STATE_PATH.write_text(json.dumps(state, ensure_ascii=False, indent=2))
    return state


def pretty(state):
    s = state["sky"]
    c = state["clock"]
    lines = []
    lines.append(f"┌─── 🔭 天窗 ───────────────────┐")
    lines.append(f"│ {s['label']}")
    lines.append(f"│ {s['scene']}")
    lines.append(f"│ 太阳{s['sun']}")
    if s.get("countdown"):
        lines.append(f"│ ⏳ {s['countdown']}")
    lines.append(f"│ 💭 {s['mood']}")
    lines.append(f"├─── 🕰️ 时钟 ───────────────────┤")
    lines.append(f"│ {c['now']}  {c['date']} {c['weekday']}")
    lines.append(f"│ 日出 {c['sunrise']}  日落 {c['sunset']}  日照 {c['daylight']}")
    lines.append(f"│ 📍 {state['location']}")
    lines.append(f"└───────────────────────────────┘")
    return "\n".join(lines)


if __name__ == "__main__":
    state = generate()
    print(pretty(state))
