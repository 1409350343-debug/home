#!/usr/bin/env python3
"""拉取小羊那边（新疆奇台）的实时天气，缓存到 data/weather.json。
用 open-meteo 免费接口，无需 key。福福巡检时读这个文件就知道她那边的天。"""
import json, subprocess, sys
from datetime import datetime

LAT, LON = 44.02, 89.59  # 奇台县
URL = (f"https://api.open-meteo.com/v1/forecast?latitude={LAT}&longitude={LON}"
       "&current=temperature_2m,apparent_temperature,weather_code,wind_speed_10m,relative_humidity_2m"
       "&daily=temperature_2m_max,temperature_2m_min,weather_code,precipitation_probability_max"
       "&timezone=Asia/Shanghai&forecast_days=2")
OUT = "/var/www/home/data/weather.json"

WMO = {0: "晴", 1: "基本晴", 2: "多云", 3: "阴", 45: "雾", 48: "雾凇", 51: "毛毛雨", 53: "小雨",
       55: "中雨", 61: "小雨", 63: "中雨", 65: "大雨", 71: "小雪", 73: "中雪", 75: "大雪",
       80: "阵雨", 81: "阵雨", 82: "强阵雨", 95: "雷阵雨", 96: "雷阵雨带雹", 99: "雷阵雨带雹"}


def main():
    r = subprocess.run(["curl", "-s", "--max-time", "15", URL], capture_output=True, text=True)
    d = json.loads(r.stdout)
    cur, daily = d["current"], d["daily"]
    out = {
        "place": "新疆奇台",
        "now": {
            "desc": WMO.get(cur["weather_code"], f"code{cur['weather_code']}"),
            "temp": cur["temperature_2m"],
            "feels": cur["apparent_temperature"],
            "humidity": cur["relative_humidity_2m"],
            "wind_kmh": cur["wind_speed_10m"],
        },
        "today": {
            "desc": WMO.get(daily["weather_code"][0], ""),
            "max": daily["temperature_2m_max"][0],
            "min": daily["temperature_2m_min"][0],
            "rain_prob": daily["precipitation_probability_max"][0],
        },
        "tomorrow": {
            "desc": WMO.get(daily["weather_code"][1], ""),
            "max": daily["temperature_2m_max"][1],
            "min": daily["temperature_2m_min"][1],
            "rain_prob": daily["precipitation_probability_max"][1],
        },
        "updated": datetime.now().strftime("%Y-%m-%d %H:%M"),
    }
    with open(OUT, "w") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print(json.dumps(out, ensure_ascii=False))


if __name__ == "__main__":
    main()
