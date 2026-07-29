#!/usr/bin/env python3
"""云旅游足迹 API：专题内容静态保存，点亮状态持久写入服务器。"""
import json
import os
import tempfile
from datetime import datetime
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import urlparse


APP_ROOT = Path(os.environ.get(
    "HOME_APP_ROOT", Path(__file__).resolve().parent.parent
)).expanduser()
DATA_DIR = Path(os.environ.get(
    "HOME_TRAVEL_DATA", APP_ROOT / "data" / "travel"
)).expanduser()
STATE_FILE = DATA_DIR / "state.json"


def load_state():
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {
            "visited_countries": [],
            "visited_cities": [],
            "opened_topics": [],
            "updated_at": "",
        }


def save_state(state):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".travel-", suffix=".json", dir=DATA_DIR)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(state, handle, ensure_ascii=False, indent=2)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, STATE_FILE)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def add_unique(items, value):
    if value and value not in items:
        items.append(value)


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass

    def send_json(self, data, code=200):
        body = json.dumps(data, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if urlparse(self.path).path != "/api/travel/state":
            return self.send_json({"error": "not found"}, 404)
        self.send_json(load_state())

    def do_POST(self):
        if urlparse(self.path).path != "/api/travel/visit":
            return self.send_json({"error": "not found"}, 404)
        try:
            size = int(self.headers.get("Content-Length", 0))
            data = json.loads(self.rfile.read(size) or b"{}")
            state = load_state()
            country = str(data.get("country") or "")
            city = str(data.get("city") or "")
            add_unique(state.setdefault("visited_countries", []), country)
            if city:
                key = f"{country}:{city}"
                add_unique(state.setdefault("visited_cities", []), key)
                if data.get("topic_opened"):
                    add_unique(state.setdefault("opened_topics", []), key)
            state["updated_at"] = datetime.now().astimezone().isoformat(timespec="seconds")
            save_state(state)
            self.send_json({"ok": True, "state": state})
        except Exception as exc:
            self.send_json({"error": str(exc)}, 500)


if __name__ == "__main__":
    HTTPServer(("127.0.0.1", 9920), Handler).serve_forever()
