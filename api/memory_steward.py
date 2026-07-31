#!/usr/bin/env python3
"""Gemini 记忆管家。

只在出现新对话或到达每日整理时间时调用 Gemini。Gemini 负责给出结构化
候选动作，本地代码负责校验并通过 lmc5_tool.py 落库；不会把数据库写权限
交给模型，也不会物理删除记忆。
"""
import argparse
import hashlib
import json
import os
import re
import sqlite3
import subprocess
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path

from memory_config import APP_ROOT, LMC5_DB, LMC5_TOOL
from memory_schema import ensure_memory_schema, memory_snapshot, record_history


PRIVATE_DIR = Path(
    os.environ.get("HOME_MEMORY_STEWARD_DIR", APP_ROOT.parent / ".home-private")
).expanduser()
CONFIG_FILE = PRIVATE_DIR / "memory-steward.json"
STATE_FILE = PRIVATE_DIR / "memory-steward-state.json"
READING_DIR = Path(
    os.environ.get("HOME_READING_DATA_DIR", APP_ROOT / "data" / "reading")
).expanduser()
CHAT_FILE = READING_DIR / "chat.json"
CHAT_ARCHIVE_FILE = READING_DIR / "chat-archive.jsonl"
PROVIDERS = {
    "deepseek": {"model": "deepseek-v4-flash", "name": "DeepSeek"},
    "gemini": {"model": "gemini-2.5-flash", "name": "Gemini"},
}
ALLOWED_CATEGORIES = {
    "person", "relationship", "preference", "project", "fact",
    "promise", "event", "growth", "health", "study", "travel", "note",
}
SECRET_RE = re.compile(
    r"(?i)(api[_ -]?key|token|password|passwd|secret)\s*[:=]\s*\S+"
)


def _atomic_json(path, value, mode=0o600):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    os.chmod(tmp, mode)
    os.replace(tmp, path)


def _read_json(path, fallback):
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else fallback.copy()
    except (OSError, json.JSONDecodeError):
        return fallback.copy()


def default_config():
    return {
        "enabled": False,
        "provider": "deepseek",
        "api_key": "",
        "model": PROVIDERS["deepseek"]["model"],
        "auto_capture": True,
        "daily_review": True,
        "batch_min_messages": 6,
        "max_wait_minutes": 120,
        "review_hour": 3,
    }


def load_config():
    cfg = default_config()
    cfg.update(_read_json(CONFIG_FILE, {}))
    provider = cfg.get("provider", "deepseek")
    if provider not in PROVIDERS:
        provider = "deepseek"
    cfg["provider"] = provider
    cfg["model"] = PROVIDERS[provider]["model"]
    return cfg


def public_config():
    cfg = load_config()
    key = cfg.pop("api_key", "")
    cfg["configured"] = bool(key)
    cfg["key_masked"] = (
        f"{key[:4]}…{key[-4:]}" if len(key) >= 10 else ("已保存" if key else "")
    )
    return cfg


def save_config(patch):
    old = load_config()
    for key in (
        "enabled", "provider", "auto_capture", "daily_review",
        "batch_min_messages", "max_wait_minutes", "review_hour",
    ):
        if key in patch:
            old[key] = patch[key]
    new_key = "".join(str(patch.get("api_key") or "").split())
    if new_key:
        if len(new_key) < 20 or not re.fullmatch(r"[\x21-\x7e]+", new_key):
            raise ValueError("API key 格式不完整，请复制完整密钥且不要带空格或换行")
        old["api_key"] = new_key
    if patch.get("clear_api_key"):
        old["api_key"] = ""
        old["enabled"] = False
    if old.get("provider") not in PROVIDERS:
        raise ValueError("不支持的记忆助手")
    old["model"] = PROVIDERS[old["provider"]]["model"]
    old["batch_min_messages"] = max(2, min(50, int(old["batch_min_messages"])))
    old["max_wait_minutes"] = max(15, min(1440, int(old["max_wait_minutes"])))
    old["review_hour"] = max(0, min(23, int(old["review_hour"])))
    if old["enabled"] and not old["api_key"]:
        raise ValueError(f"请先填写 {PROVIDERS[old['provider']]['name']} API key")
    _atomic_json(CONFIG_FILE, old)
    return public_config()


def default_state():
    return {
        "processed_ids": [],
        "last_capture_at": "",
        "last_review_date": "",
        "last_run_at": "",
        "last_error": "",
        "last_result": "",
        "captured_total": 0,
        "archived_total": 0,
    }


def load_state():
    state = default_state()
    state.update(_read_json(STATE_FILE, {}))
    return state


def save_state(state):
    state["processed_ids"] = list(state.get("processed_ids", []))[-3000:]
    _atomic_json(STATE_FILE, state)


def public_status():
    state = load_state()
    state["pending_messages"] = len(pending_messages(state))
    state["configured"] = public_config()["configured"]
    state["enabled"] = public_config()["enabled"]
    return state


def _message_id(item):
    raw = str(item.get("id") or item.get("client_id") or "")
    if raw:
        return raw
    text = json.dumps(item, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(text.encode()).hexdigest()[:20]


def _clean_message(item):
    sender = str(item.get("sender") or item.get("role") or "").strip().lower()
    if sender in {"system", "tool"}:
        return None
    text = str(item.get("text") or item.get("content") or "").strip()
    if not text:
        return None
    text = SECRET_RE.sub(r"\1=[已隐藏]", text)[:4000]
    return {
        "id": _message_id(item),
        "sender": sender or "unknown",
        "text": text,
        "time": str(item.get("ts") or item.get("time") or ""),
        "source": str(item.get("route") or "home-chat"),
    }


def load_chat_messages(limit=500):
    items = []
    try:
        current = json.loads(CHAT_FILE.read_text(encoding="utf-8"))
        if isinstance(current, dict):
            current = current.get("messages", [])
        if isinstance(current, list):
            items.extend(current)
    except (OSError, json.JSONDecodeError):
        pass
    if CHAT_ARCHIVE_FILE.exists():
        try:
            lines = CHAT_ARCHIVE_FILE.read_text(encoding="utf-8").splitlines()[-limit:]
            for line in lines:
                value = json.loads(line)
                if isinstance(value, list):
                    items.extend(value)
                elif isinstance(value, dict):
                    items.append(value)
        except (OSError, json.JSONDecodeError):
            pass
    cleaned = [message for item in items if (message := _clean_message(item))]
    deduped = {}
    for item in cleaned:
        deduped[item["id"]] = item
    return list(deduped.values())[-limit:]


def pending_messages(state=None):
    state = state or load_state()
    done = set(state.get("processed_ids", []))
    return [item for item in load_chat_messages() if item["id"] not in done]


CAPTURE_SCHEMA = {
    "type": "object",
    "properties": {
        "candidates": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "action": {"type": "string", "enum": ["ignore", "add_memory", "set_fact"]},
                    "title": {"type": "string"},
                    "content": {"type": "string"},
                    "category": {"type": "string"},
                    "thread": {"type": "string"},
                    "tags": {"type": "array", "items": {"type": "string"}},
                    "why": {"type": "string"},
                    "valence": {"type": "number"},
                    "fact_key": {"type": "string"},
                    "fact_value": {"type": "string"},
                    "confidence": {"type": "number"},
                    "explicit_user_fact": {"type": "boolean"},
                    "source_message_ids": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["action", "title", "content", "category", "thread",
                             "tags", "why", "confidence", "explicit_user_fact",
                             "source_message_ids"],
            },
        }
    },
    "required": ["candidates"],
}

REVIEW_SCHEMA = {
    "type": "object",
    "properties": {
        "decisions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "integer"},
                    "action": {"type": "string", "enum": ["keep", "archive"]},
                    "reason": {"type": "string"},
                    "confidence": {"type": "number"},
                },
                "required": ["id", "action", "reason", "confidence"],
            },
        }
    },
    "required": ["decisions"],
}


def ai_json(prompt, schema, config=None):
    cfg = config or load_config()
    if not cfg.get("api_key"):
        raise RuntimeError("记忆助手 API key 未配置")
    if cfg.get("provider") == "deepseek":
        return deepseek_json(prompt, schema, cfg)
    return gemini_json(prompt, schema, cfg)


def deepseek_json(prompt, schema, cfg):
    url = "https://api.deepseek.com/chat/completions"
    schema_hint = json.dumps(schema, ensure_ascii=False)
    payload = {
        "model": cfg["model"],
        "messages": [
            {
                "role": "system",
                "content": "你是记忆整理助手。只输出合法 JSON，不要输出 Markdown 或解释。",
            },
            {
                "role": "user",
                "content": f"{prompt}\n\n请严格按这个 JSON Schema 输出 JSON：\n{schema_hint}",
            },
        ],
        "response_format": {"type": "json_object"},
        "temperature": 0.15,
        "max_tokens": 4096,
    }
    request = urllib.request.Request(
        url,
        data=json.dumps(payload, ensure_ascii=False).encode(),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {cfg['api_key']}",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            result = json.loads(response.read().decode())
        text = result["choices"][0]["message"]["content"]
        if not text:
            raise RuntimeError("DeepSeek 返回了空内容，请稍后重试")
        return json.loads(text)
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode(errors="replace")[:500]
        raise RuntimeError(f"DeepSeek HTTP {exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"无法连接 DeepSeek：{exc.reason}") from exc
    except (TimeoutError, OSError) as exc:
        raise RuntimeError(f"连接 DeepSeek 失败：{exc}") from exc
    except (KeyError, IndexError, json.JSONDecodeError) as exc:
        raise RuntimeError("DeepSeek 没有返回可用的结构化结果") from exc


def gemini_json(prompt, schema, cfg):
    url = (
        "https://generativelanguage.googleapis.com/v1beta/models/"
        f"{cfg['model']}:generateContent"
    )
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": 0.15,
            "responseMimeType": "application/json",
            "responseJsonSchema": schema,
        },
    }
    request = urllib.request.Request(
        url,
        data=json.dumps(payload, ensure_ascii=False).encode(),
        headers={
            "Content-Type": "application/json",
            "x-goog-api-key": cfg["api_key"],
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=45) as response:
            result = json.loads(response.read().decode())
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode(errors="replace")[:500]
        raise RuntimeError(f"Gemini HTTP {exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"无法连接 Gemini：{exc.reason}") from exc
    except (TimeoutError, OSError) as exc:
        raise RuntimeError(f"连接 Gemini 失败：{exc}") from exc
    try:
        text = result["candidates"][0]["content"]["parts"][0]["text"]
        return json.loads(text)
    except (KeyError, IndexError, json.JSONDecodeError) as exc:
        raise RuntimeError("Gemini 没有返回可用的结构化结果") from exc


def _run_tool(arguments):
    proc = subprocess.run(
        ["python3", str(LMC5_TOOL), *arguments],
        cwd=str(LMC5_TOOL.parent),
        text=True,
        capture_output=True,
        timeout=60,
    )
    if proc.returncode:
        raise RuntimeError((proc.stderr or proc.stdout).strip()[:800])
    return proc.stdout.strip()


def apply_candidate(item):
    action = item.get("action")
    if action == "ignore":
        return False
    confidence = float(item.get("confidence") or 0)
    why = str(item.get("why") or "").strip()
    title = str(item.get("title") or "").strip()[:120]
    content = str(item.get("content") or "").strip()[:8000]
    if confidence < 0.72 or not why or not title or not content:
        return False
    category = str(item.get("category") or "note").strip().lower()
    if category not in ALLOWED_CATEGORIES:
        category = "note"
    thread = re.sub(r"[^\w\u4e00-\u9fff.-]", "-", str(item.get("thread") or category))[:60]
    tags = [
        str(tag).strip()[:30] for tag in item.get("tags", [])
        if str(tag).strip()
    ][:10]
    source_ids = ",".join(str(v) for v in item.get("source_message_ids", []))[:500]
    if action == "set_fact":
        key = str(item.get("fact_key") or "").strip().lower()
        value = str(item.get("fact_value") or "").strip()
        if not re.fullmatch(r"[a-z0-9][a-z0-9_.-]{2,127}", key) or not value:
            return False
        explicit = bool(item.get("explicit_user_fact"))
        status = "confirmed" if explicit and confidence >= 0.92 else "pending"
        _run_tool([
            "fact-set", key, value, "--title", title, "--content", content,
            "--thread", thread, "--category", "fact",
            "--tags", ",".join(tags), "--source", "gemini-memory-steward",
            "--source-message-id", source_ids,
            "--confidence", str(confidence), "--review-status", status,
            "--change-reason", "从对话中识别出的事实版本", "--why", why,
        ])
    else:
        args = [
            "add", "--title", title, "--content", content,
            "--thread", thread, "--category", category,
            "--tags", ",".join(tags), "--source", "gemini-memory-steward",
            "--why", why,
        ]
        if item.get("valence") is not None:
            args += ["--valence", str(max(-1, min(1, float(item["valence"]))))]
        _run_tool(args)
    return True


def capture(messages=None, force=False):
    cfg, state = load_config(), load_state()
    if not cfg["enabled"] or not cfg["auto_capture"]:
        return {"ok": False, "message": "自动记录未启用"}
    messages = messages if messages is not None else pending_messages(state)
    if not messages:
        return {"ok": True, "message": "没有新对话", "written": 0}
    last = state.get("last_capture_at")
    waited = 10**9
    if last:
        try:
            waited = (datetime.now() - datetime.fromisoformat(last)).total_seconds() / 60
        except ValueError:
            pass
    if not force and len(messages) < cfg["batch_min_messages"] and waited < cfg["max_wait_minutes"]:
        return {"ok": True, "message": f"等待凑批（当前 {len(messages)} 条）", "written": 0}
    batch = messages[:40]
    prompt = """你是“小窝”的记忆筛选助手。只从给定对话提取未来仍有帮助的长期记忆。
忽略寒暄、一次性流水、模型自己的猜测、密钥与隐私凭据。每条记忆必须写清楚 why：
为什么以后值得想起。用户明确说出的稳定偏好、身份、约定或项目现状可用 set_fact；
不确定的事实也可输出，但 explicit_user_fact=false。不要凭空补充内容，不要把助理建议
当成用户事实。中文简洁输出。\n\n对话：\n""" + json.dumps(batch, ensure_ascii=False)
    result = ai_json(prompt, CAPTURE_SCHEMA, cfg)
    written = 0
    for item in result.get("candidates", [])[:20]:
        try:
            written += int(apply_candidate(item))
        except (ValueError, RuntimeError):
            continue
    state["processed_ids"] = state.get("processed_ids", []) + [item["id"] for item in batch]
    state["last_capture_at"] = datetime.now().isoformat(timespec="seconds")
    state["last_run_at"] = state["last_capture_at"]
    state["last_error"] = ""
    state["last_result"] = f"分析 {len(batch)} 条对话，写入 {written} 条记忆"
    state["captured_total"] = int(state.get("captured_total", 0)) + written
    save_state(state)
    return {"ok": True, "message": state["last_result"], "written": written}


def _review_candidates():
    if not LMC5_DB.exists():
        return []
    conn = sqlite3.connect(LMC5_DB)
    conn.row_factory = sqlite3.Row
    ensure_memory_schema(conn)
    cutoff = (datetime.now() - timedelta(days=7)).date().isoformat()
    rows = conn.execute(
        """SELECT id, title, content, category, thread, tags_json,
                  why_remembered, created_at, event_date, hit_count
           FROM memories
           WHERE status='current'
             AND COALESCE(substr(event_date,1,10), substr(created_at,1,10)) <= ?
             AND fact_key=''
             AND steward_reviewed_at IS NULL
           ORDER BY id LIMIT 80""",
        (cutoff,),
    ).fetchall()
    conn.close()
    return [dict(row) for row in rows]


def review(force=False):
    cfg, state = load_config(), load_state()
    today = datetime.now().date().isoformat()
    if not cfg["enabled"] or not cfg["daily_review"]:
        return {"ok": False, "message": "7 日整理未启用"}
    if not force and state.get("last_review_date") == today:
        return {"ok": True, "message": "今天已经整理过"}
    rows = _review_candidates()
    if not rows:
        state["last_review_date"] = today
        save_state(state)
        return {"ok": True, "message": "没有到期记忆"}
    prompt = """你是记忆库的 7 日整理助手。判断这些超过 7 天的记忆是否仍值得保留。
长期偏好、人物关系、承诺、事实、项目决定、重要成长必须 keep；仅当内容确实是短期流水、
重复噪声或已失去用途时才 archive。archive 是可恢复归档，不是删除。保守判断，不确定就
keep。逐项返回，理由使用中文。\n\n记忆：\n""" + json.dumps(rows, ensure_ascii=False)
    result = ai_json(prompt, REVIEW_SCHEMA, cfg)
    allowed = {row["id"] for row in rows}
    archived = 0
    conn = sqlite3.connect(LMC5_DB)
    conn.row_factory = sqlite3.Row
    ensure_memory_schema(conn)
    for decision in result.get("decisions", []):
        mid = int(decision.get("id") or 0)
        confidence = float(decision.get("confidence") or 0)
        if mid not in allowed:
            continue
        if decision.get("action") != "archive" or confidence < 0.88:
            conn.execute(
                "UPDATE memories SET steward_reviewed_at=CURRENT_TIMESTAMP WHERE id=?",
                (mid,),
            )
            continue
        before = memory_snapshot(conn, mid)
        cur = conn.execute(
            """UPDATE memories SET status='archived', archived_at=CURRENT_TIMESTAMP,
                   updated_at=CURRENT_TIMESTAMP,
                   steward_reviewed_at=CURRENT_TIMESTAMP
               WHERE id=? AND status='current'""",
            (mid,),
        )
        if cur.rowcount:
            record_history(
                conn, mid, "archived_by_gemini_review",
                str(decision.get("reason") or "7 日整理"), snapshot=before,
            )
            archived += 1
    conn.commit()
    conn.close()
    state["last_review_date"] = today
    state["last_run_at"] = datetime.now().isoformat(timespec="seconds")
    state["last_error"] = ""
    state["last_result"] = f"复核 {len(rows)} 条，归档 {archived} 条"
    state["archived_total"] = int(state.get("archived_total", 0)) + archived
    save_state(state)
    return {"ok": True, "message": state["last_result"], "archived": archived}


def run_once(force=False):
    cfg, state = load_config(), load_state()
    if not cfg["enabled"]:
        return {"ok": False, "message": "记忆管家未启用"}
    results = []
    try:
        if cfg["auto_capture"]:
            results.append(capture(force=force))
        due = datetime.now().hour >= cfg["review_hour"]
        if cfg["daily_review"] and (force or due):
            results.append(review(force=force))
        return {"ok": True, "results": results}
    except Exception as exc:
        state["last_run_at"] = datetime.now().isoformat(timespec="seconds")
        state["last_error"] = str(exc)[:800]
        state["last_result"] = "运行失败"
        save_state(state)
        raise


def watch(interval=300):
    while True:
        try:
            run_once()
        except Exception:
            pass
        time.sleep(max(60, interval))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("run-once", "watch", "status"))
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--interval", type=int, default=300)
    args = parser.parse_args()
    if args.command == "status":
        print(json.dumps(public_status(), ensure_ascii=False, indent=2))
    elif args.command == "watch":
        watch(args.interval)
    else:
        print(json.dumps(run_once(args.force), ensure_ascii=False, indent=2))
