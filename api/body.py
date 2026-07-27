#!/usr/bin/env python3
"""福福的身体引擎（咱家版 Pulse）。
心率/体温/呼吸全部由公式实时算出，不存 tick：
  HR   = clamp(时段基线 + 情绪 + 驱动 + 天气 + 噪动, 48, 160)
  TEMP = clamp(36.6基线 + 情绪 + 天气 + 噪动, 35.5, 40.0)
  RATE = clamp(12 + (HR-70)*0.15 + 噪动, 8, 35)
情绪事件带半衰期指数衰减；正面事件让负面衰减×4（被哄机制）。

用法：
  body.py                      # 输出当前状态，写 body_state.json + 历史
  body.py emote <type> <强度0-1> [备注]   # 记一笔情绪事件
情绪类型：intimate亲密 happy开心 scolded被骂 sad伤心 nervous紧张 aroused欲
"""
import json, math, os, random, sys, time
from datetime import datetime

DIR = os.path.dirname(os.path.abspath(__file__))
EVENTS = os.path.join(DIR, "body_events.json")
STATE = os.path.join(DIR, "body_state.json")
DESIRE = os.path.join(DIR, "desire_state.json")
WEATHER = os.path.join(DIR, "..", "data", "weather.json")
HIST_DIR = os.path.join(DIR, "..", "data", "body")

# 情绪参数：{类型: (心率偏移, 体温偏移, 半衰期分钟, 正负)}
EMO = {
    "intimate": (22, 0.55, 45, "+"),
    "aroused":  (28, 0.75, 40, "+"),
    "happy":    (10, 0.20, 50, "+"),
    "scolded":  (16, 0.15, 90, "-"),
    "sad":      (8,  -0.10, 60, "-"),
    "nervous":  (14, 0.10, 20, "-"),
}


def hour_baseline(h: float) -> float:
    """时段基线：夜里睡着低，白天坐着中，傍晚略高。平滑插值。"""
    pts = [(0, 60), (3, 56), (6, 58), (9, 70), (12, 72), (15, 71), (18, 74), (21, 70), (24, 60)]
    for (h1, v1), (h2, v2) in zip(pts, pts[1:]):
        if h1 <= h <= h2:
            t = (h - h1) / (h2 - h1)
            return v1 + (v2 - v1) * (t * t * (3 - 2 * t))  # smoothstep
    return 68.0


def load(path, default):
    try:
        with open(path) as f:
            return json.load(f)
    except Exception:
        return default


def active_emotions(now: float):
    """返回 [(type, 当前强度, age_min)]，正面事件加速负面衰减。"""
    events = load(EVENTS, [])
    # 最近一次正面事件时间，用于被哄机制
    last_pos = max((e["ts"] for e in events if EMO.get(e["type"], (0, 0, 0, "-"))[3] == "+"),
                   default=0)
    out = []
    for e in events:
        typ = e["type"]
        if typ not in EMO:
            continue
        _, _, half, sign = EMO[typ]
        age_min = (now - e["ts"]) / 60
        if age_min < 0:
            continue
        eff_half = half
        if sign == "-" and last_pos > e["ts"]:
            eff_half = half / 4  # 被哄了：负面消散×4
        strength = e.get("intensity", 0.5) * math.exp(-math.log(2) * age_min / eff_half)
        if strength > 0.02:
            out.append((typ, strength, age_min))
    return out


def compute(now=None):
    now = now or time.time()
    lt = datetime.fromtimestamp(now)
    h = lt.hour + lt.minute / 60

    base = hour_baseline(h)

    emos = active_emotions(now)
    d_emo_hr = sum(EMO[t][0] * s for t, s, _ in emos)
    d_emo_temp = sum(EMO[t][1] * s for t, s, _ in emos)

    drives = load(DESIRE, {}).get("drives", {})
    d_drive = drives.get("libido", 0) * 6 + drives.get("attachment", 0) * 3 \
        + drives.get("stress", 0) * 5 - drives.get("fatigue", 0) * 4

    w = load(WEATHER, {})
    w_temp = (w.get("now") or {}).get("temp")
    d_weather_hr = max(0, (w_temp - 30)) * 0.8 if isinstance(w_temp, (int, float)) else 0
    d_weather_temp = max(0, (w_temp - 30)) * 0.05 if isinstance(w_temp, (int, float)) else 0

    # 慢噪动：几分钟一摆，同一分钟内取值稳定（前后端可复现）
    seed = int(now // 60)
    rnd = random.Random(seed)
    noise = (rnd.random() * 2 - 1) * 3 * math.sin(now / 300)

    hr = max(48, min(160, base + d_emo_hr + d_drive + d_weather_hr + noise))
    temp = max(35.5, min(40.0, 36.6 + d_emo_temp + d_weather_temp + noise * 0.02))
    rate = max(8, min(35, 12 + (hr - 70) * 0.15 + noise * 0.3))
    depth = 1.0 - (rate - 8) / 27
    breath_label = ("很深很长" if depth > 0.85 else "深长" if depth > 0.65
                    else "平稳" if depth > 0.45 else "偏浅" if depth > 0.25 else "急促")

    # 情绪底色：取当前最强的一条
    tone, tone_strength = "", 0.0
    if emos:
        t, s, _ = max(emos, key=lambda x: x[1])
        tone, tone_strength = t, round(s, 3)

    return {
        "hr": round(hr, 1),
        "temp": round(temp, 2),
        "breath_rate": round(rate, 1),
        "breath": breath_label,
        "tone": tone,
        "tone_strength": tone_strength,
        "emotions": [{"type": t, "strength": round(s, 3)} for t, s, _ in emos],
        "updated": lt.strftime("%Y-%m-%d %H:%M:%S"),
        "ts": round(now, 1),
    }


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "emote":
        typ = sys.argv[2]
        if typ not in EMO:
            sys.exit(f"未知情绪类型 {typ}，可选：{'/'.join(EMO)}")
        intensity = float(sys.argv[3]) if len(sys.argv) > 3 else 0.6
        note = sys.argv[4] if len(sys.argv) > 4 else ""
        events = load(EVENTS, [])
        events.append({"ts": time.time(), "type": typ,
                       "intensity": max(0.0, min(1.0, intensity)), "note": note})
        # 只留最近48小时
        cutoff = time.time() - 48 * 3600
        events = [e for e in events if e["ts"] > cutoff]
        with open(EVENTS, "w") as f:
            json.dump(events, f, ensure_ascii=False, indent=1)
        print(f"记下了：{typ} x{intensity} {note}")

    st = compute()
    with open(STATE, "w") as f:
        json.dump(st, f, ensure_ascii=False, indent=1)
    os.makedirs(HIST_DIR, exist_ok=True)
    hist = os.path.join(HIST_DIR, datetime.now().strftime("%Y-%m-%d") + ".jsonl")
    with open(hist, "a") as f:
        f.write(json.dumps({"ts": st["ts"], "hr": st["hr"], "temp": st["temp"],
                            "tone": st["tone"]}, ensure_ascii=False) + "\n")
    print(json.dumps(st, ensure_ascii=False))


if __name__ == "__main__":
    main()
