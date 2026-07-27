#!/usr/bin/env python3
"""
Session Swap/Forge MVP for Claude Code
Based on public-cc-swap-forge-guide-2026-06-12-v3

Swap: context too long but clean → trim transcript, resume in new session
Forge: context polluted (route drift, stale output) → rebuild from clean boundary

Usage:
  python3 session_swap.py swap [--retain-tokens N]     # daily swap
  python3 session_swap.py forge [--target-model MODEL]  # deep recast
  python3 session_swap.py status                        # show active session info
  python3 session_swap.py guard  [--target-model MODEL] # check for route drift
"""

import json
import os
import sys
import uuid
import shutil
import glob
import argparse
from datetime import datetime
from pathlib import Path

PROJECT_DIR = Path.home() / ".claude" / "projects" / "-var-www-home-api"
ARCHIVE_DIR = PROJECT_DIR / "archived_sessions"
LAST_GOOD_FILE = PROJECT_DIR / "last_good_session.json"

KEEPABLE_TYPES = {"user", "assistant", "system"}
DEFAULT_RETAIN_TOKENS = 80000
DEFAULT_TARGET_MODEL = "claude-opus-4-6"
AUTO_SWAP_THRESHOLD = 0.75  # swap when transcript reaches 75% of estimated max
ESTIMATED_MAX_TOKENS = 200000  # opus context window
SWAP_ALERT_FILE = PROJECT_DIR / "swap_alert.json"


def read_jsonl(path):
    events = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line:
                events.append(json.loads(line))
    return events


def write_jsonl(path, events):
    with open(path, "w") as f:
        for event in events:
            f.write(json.dumps(event, ensure_ascii=False) + "\n")


def find_active_session():
    jsonl_files = glob.glob(str(PROJECT_DIR / "*.jsonl"))
    if not jsonl_files:
        return None
    newest = max(jsonl_files, key=os.path.getmtime)
    return newest


def get_session_id(path):
    return Path(path).stem


def estimate_event_tokens(event):
    raw = json.dumps(event, ensure_ascii=False)
    return len(raw) // 4


def filter_keepable(events):
    keepable = []
    for e in events:
        t = e.get("type")
        if t in KEEPABLE_TYPES:
            keepable.append(e)
    return keepable


def find_clean_boundary(keepable, retain_tokens):
    """Find where to cut: keep the last N tokens worth of events."""
    total = 0
    cut_index = len(keepable)
    for i in range(len(keepable) - 1, -1, -1):
        total += estimate_event_tokens(keepable[i])
        if total > retain_tokens:
            cut_index = i + 1
            break
    # Align to user message boundary
    while cut_index < len(keepable):
        if keepable[cut_index].get("type") == "user":
            break
        cut_index += 1
    return cut_index


def ensure_tool_primer(retained, all_keepable, min_rounds=1):
    """Make sure at least min_rounds of tool_use + tool_result pairs exist."""
    has_tool_use = False
    for e in retained:
        if e.get("type") == "assistant":
            content = e.get("message", {}).get("content", [])
            for block in content:
                if isinstance(block, dict) and block.get("type") == "tool_use":
                    has_tool_use = True
                    break
        if has_tool_use:
            break

    if has_tool_use:
        return retained

    # Find a tool_use round from earlier in the transcript
    primer_pairs = []
    i = 0
    found = 0
    while i < len(all_keepable) and found < min_rounds:
        e = all_keepable[i]
        if e.get("type") == "assistant":
            content = e.get("message", {}).get("content", [])
            for block in content:
                if isinstance(block, dict) and block.get("type") == "tool_use":
                    # Found assistant with tool_use, need the next user (tool_result)
                    primer_pairs.append(e)
                    if i + 1 < len(all_keepable) and all_keepable[i + 1].get("type") == "user":
                        primer_pairs.append(all_keepable[i + 1])
                    found += 1
                    break
        i += 1

    if primer_pairs:
        return primer_pairs + retained
    return retained


def rewrite_session_chain(events, new_session_id):
    """Rewrite session IDs and parent chain for new session."""
    rewritten = []
    for e in events:
        e2 = dict(e)
        if "sessionId" in e2:
            e2["sessionId"] = new_session_id
        if "session_id" in e2:
            e2["session_id"] = new_session_id
        if "parentUuid" in e2:
            e2["parentUuid"] = None
        if "uuid" in e2:
            e2["uuid"] = str(uuid.uuid4())
        # Rewrite tool_use/tool_result IDs to stay consistent
        rewritten.append(e2)
    return fix_tool_ids(rewritten)


def fix_tool_ids(events):
    """Ensure tool_use IDs in assistant match tool_result IDs in subsequent user."""
    id_map = {}
    result = []
    for e in events:
        e2 = dict(e)
        if e2.get("type") == "assistant":
            msg = dict(e2.get("message", {}))
            content = msg.get("content", [])
            new_content = []
            for block in content:
                if isinstance(block, dict) and block.get("type") == "tool_use":
                    old_id = block.get("id", "")
                    new_id = "toolu_" + str(uuid.uuid4()).replace("-", "")[:24]
                    id_map[old_id] = new_id
                    block2 = dict(block)
                    block2["id"] = new_id
                    new_content.append(block2)
                else:
                    new_content.append(block)
            msg["content"] = new_content
            e2["message"] = msg
        elif e2.get("type") == "user":
            msg = e2.get("message", {})
            content = msg.get("content") if isinstance(msg, dict) else None
            if isinstance(content, list):
                new_content = []
                for block in content:
                    if isinstance(block, dict) and block.get("type") == "tool_result":
                        old_id = block.get("tool_use_id", "")
                        block2 = dict(block)
                        block2["tool_use_id"] = id_map.get(old_id, old_id)
                        new_content.append(block2)
                    else:
                        new_content.append(block)
                if isinstance(msg, dict):
                    msg2 = dict(msg)
                    msg2["content"] = new_content
                    e2["message"] = msg2
        result.append(e2)
    return result


def scan_route_guard(events, target_model):
    """Detect model routing drift."""
    drift_line = None
    for index, event in enumerate(events):
        if event.get("type") != "assistant":
            continue
        actual = event.get("message", {}).get("model", "")
        if actual and normalize_model(actual) != normalize_model(target_model):
            drift_line = index
            break

    if drift_line is None:
        return None

    anchor = find_anchor_before(events, drift_line)
    return {
        "reason": "model_route_drift",
        "anchor": anchor,
        "drift_line": drift_line,
        "actual_model": events[drift_line].get("message", {}).get("model", ""),
        "target_model": target_model,
    }


def normalize_model(model_str):
    parts = model_str.lower().replace("_", "-").split("-")
    key_parts = [p for p in parts if p in ("opus", "sonnet", "haiku", "fable") or p.replace(".", "").isdigit()]
    return "-".join(key_parts) if key_parts else model_str.lower()


def find_anchor_before(events, drift_line):
    """Find the last clean user message boundary before drift."""
    for i in range(drift_line - 1, -1, -1):
        if events[i].get("type") == "user":
            return i
    return 0


def create_session_header(new_session_id):
    return [
        {"type": "mode", "mode": "normal", "sessionId": new_session_id},
        {"type": "permission-mode", "permissionMode": "auto", "sessionId": new_session_id},
    ]


def mark_last_good(session_id, path):
    data = {
        "session_id": session_id,
        "path": str(path),
        "timestamp": datetime.utcnow().isoformat() + "Z",
    }
    with open(LAST_GOOD_FILE, "w") as f:
        json.dump(data, f, indent=2)
    print(f"  Marked last-good: {session_id}")


def archive_old(path):
    ARCHIVE_DIR.mkdir(exist_ok=True)
    dest = ARCHIVE_DIR / Path(path).name
    shutil.move(str(path), str(dest))
    print(f"  Archived: {Path(path).name} → archived_sessions/")


def do_swap(args):
    active_path = find_active_session()
    if not active_path:
        print("No active session found.")
        return False

    old_sid = get_session_id(active_path)
    print(f"Swap: active session = {old_sid}")
    print(f"  Path: {active_path}")

    events = read_jsonl(active_path)
    print(f"  Total events: {len(events)}")

    keepable = filter_keepable(events)
    print(f"  Keepable events: {len(keepable)}")

    cut = find_clean_boundary(keepable, args.retain_tokens)
    retained = keepable[cut:]
    print(f"  Retaining {len(retained)} events (from index {cut})")

    retained = ensure_tool_primer(retained, keepable, min_rounds=1)
    print(f"  After tool primer: {len(retained)} events")

    new_sid = str(uuid.uuid4())
    header = create_session_header(new_sid)
    rewritten = rewrite_session_chain(retained, new_sid)
    final = header + rewritten

    new_path = PROJECT_DIR / f"{new_sid}.jsonl"
    write_jsonl(new_path, final)
    print(f"  New session: {new_sid}")
    print(f"  New transcript: {len(final)} events")
    print(f"  Token estimate: ~{sum(estimate_event_tokens(e) for e in final):,}")

    mark_last_good(old_sid, active_path)
    archive_old(active_path)

    print(f"\n  Resume command:")
    print(f"  claude --resume {new_sid}")
    return True


def do_forge(args):
    active_path = find_active_session()
    if not active_path:
        print("No active session found.")
        return False

    old_sid = get_session_id(active_path)
    events = read_jsonl(active_path)
    keepable = filter_keepable(events)

    print(f"Forge: active session = {old_sid}")
    print(f"  Total events: {len(events)}, keepable: {len(keepable)}")

    # Check for route drift
    drift = scan_route_guard(keepable, args.target_model)
    if drift:
        print(f"  Route drift detected at line {drift['drift_line']}")
        print(f"  Expected: {drift['target_model']}, Got: {drift['actual_model']}")
        print(f"  Cutting at anchor: {drift['anchor']}")
        keepable = keepable[: drift["anchor"]]

    cut = find_clean_boundary(keepable, args.retain_tokens)
    retained = keepable[cut:]
    retained = ensure_tool_primer(retained, keepable, min_rounds=1)

    new_sid = str(uuid.uuid4())
    header = create_session_header(new_sid)
    rewritten = rewrite_session_chain(retained, new_sid)
    final = header + rewritten

    new_path = PROJECT_DIR / f"{new_sid}.jsonl"
    write_jsonl(new_path, final)

    print(f"  New session: {new_sid}")
    print(f"  Forged transcript: {len(final)} events")

    mark_last_good(old_sid, active_path)
    archive_old(active_path)

    print(f"\n  Resume command:")
    print(f"  claude --resume {new_sid}")
    return True


def do_guard(args):
    active_path = find_active_session()
    if not active_path:
        print("No active session found.")
        return

    events = read_jsonl(active_path)
    keepable = filter_keepable(events)
    drift = scan_route_guard(keepable, args.target_model)

    if drift:
        print(f"DRIFT DETECTED")
        print(f"  Expected: {drift['target_model']}")
        print(f"  Actual:   {drift['actual_model']}")
        print(f"  At event: {drift['drift_line']}")
        print(f"  Recommend: python3 session_swap.py forge")
    else:
        models = set()
        for e in keepable:
            if e.get("type") == "assistant":
                m = e.get("message", {}).get("model", "")
                if m:
                    models.add(m)
        print(f"No drift. Models seen: {', '.join(models) or 'none'}")


def do_status(args):
    active_path = find_active_session()
    if not active_path:
        print("No active session found.")
        return

    sid = get_session_id(active_path)
    events = read_jsonl(active_path)
    keepable = filter_keepable(events)
    size_kb = os.path.getsize(active_path) / 1024
    mtime = datetime.fromtimestamp(os.path.getmtime(active_path))

    user_count = sum(1 for e in keepable if e.get("type") == "user")
    asst_count = sum(1 for e in keepable if e.get("type") == "assistant")
    est_tokens = sum(estimate_event_tokens(e) for e in events)

    models = set()
    for e in keepable:
        if e.get("type") == "assistant":
            m = e.get("message", {}).get("model", "")
            if m:
                models.add(m)

    print(f"Active session: {sid}")
    print(f"  Path: {active_path}")
    print(f"  Size: {size_kb:.0f} KB")
    print(f"  Last modified: {mtime.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"  Total events: {len(events)} (user: {user_count}, assistant: {asst_count})")
    print(f"  Est. tokens: ~{est_tokens:,}")
    print(f"  Models: {', '.join(models) or 'none'}")

    if LAST_GOOD_FILE.exists():
        with open(LAST_GOOD_FILE) as f:
            lg = json.load(f)
        print(f"  Last-good: {lg['session_id']} ({lg['timestamp']})")

    archived = list(ARCHIVE_DIR.glob("*.jsonl")) if ARCHIVE_DIR.exists() else []
    print(f"  Archived sessions: {len(archived)}")


def get_real_token_count(events):
    """Get actual token count from the last assistant event's usage data."""
    for e in reversed(events):
        if e.get("type") == "assistant":
            usage = e.get("message", {}).get("usage", {})
            total = (
                usage.get("input_tokens", 0)
                + usage.get("cache_read_input_tokens", 0)
                + usage.get("cache_creation_input_tokens", 0)
            )
            if total > 0:
                return total
    return sum(estimate_event_tokens(e) for e in events)


def do_auto_check(args):
    """Check if context is getting fat, write alert file if swap needed."""
    active_path = find_active_session()
    if not active_path:
        print("NO_SESSION")
        return

    events = read_jsonl(active_path)
    est_tokens = get_real_token_count(events)
    ratio = est_tokens / ESTIMATED_MAX_TOKENS
    threshold = args.threshold if hasattr(args, 'threshold') else AUTO_SWAP_THRESHOLD

    # Also check for route drift
    keepable = filter_keepable(events)
    drift = scan_route_guard(keepable, args.target_model if hasattr(args, 'target_model') else DEFAULT_TARGET_MODEL)

    status = {
        "session_id": get_session_id(active_path),
        "est_tokens": est_tokens,
        "ratio": round(ratio, 3),
        "threshold": threshold,
        "needs_swap": ratio >= threshold,
        "drift_detected": drift is not None,
        "drift_info": drift,
        "checked_at": datetime.utcnow().isoformat() + "Z",
    }

    if ratio >= threshold or drift:
        # Write alert file
        with open(SWAP_ALERT_FILE, "w") as f:
            json.dump(status, f, indent=2, ensure_ascii=False)

        if drift:
            print(f"SWAP_NEEDED:DRIFT — model drifted to {drift['actual_model']}")
        else:
            print(f"SWAP_NEEDED:SIZE — {ratio:.0%} full ({est_tokens:,} tokens)")

        if args.auto_swap if hasattr(args, 'auto_swap') and args.auto_swap else False:
            print("Auto-swapping...")
            class SwapArgs:
                retain_tokens = DEFAULT_RETAIN_TOKENS
            do_swap(SwapArgs())
    else:
        # Clear alert if exists
        if SWAP_ALERT_FILE.exists():
            SWAP_ALERT_FILE.unlink()
        print(f"OK — {ratio:.0%} full ({est_tokens:,} tokens)")


def do_watch(args):
    """Continuous watcher: check every N seconds, auto-swap when needed."""
    import time
    interval = args.interval
    print(f"Watcher started (interval={interval}s, threshold={args.threshold:.0%})")
    check_count = 0
    while True:
        check_count += 1
        active_path = find_active_session()
        if not active_path:
            time.sleep(interval)
            continue

        events = read_jsonl(active_path)
        est_tokens = get_real_token_count(events)
        ratio = est_tokens / ESTIMATED_MAX_TOKENS

        keepable = filter_keepable(events)
        drift = scan_route_guard(keepable, args.target_model)

        ts = datetime.now().strftime("%H:%M:%S")

        if drift:
            print(f"[{ts}] #{check_count} DRIFT detected → auto-forge")
            class ForgeArgs:
                retain_tokens = DEFAULT_RETAIN_TOKENS
                target_model = args.target_model
            do_forge(ForgeArgs())
            break
        elif ratio >= args.threshold:
            print(f"[{ts}] #{check_count} {ratio:.0%} full → auto-swap")
            class SwapArgs:
                retain_tokens = DEFAULT_RETAIN_TOKENS
            do_swap(SwapArgs())
            break
        else:
            print(f"[{ts}] #{check_count} OK {ratio:.0%} ({est_tokens:,} tokens)", flush=True)

        time.sleep(interval)


def main():
    parser = argparse.ArgumentParser(description="Session Swap/Forge for Claude Code")
    sub = parser.add_subparsers(dest="command")

    p_swap = sub.add_parser("swap", help="Swap to a new clean session")
    p_swap.add_argument("--retain-tokens", type=int, default=DEFAULT_RETAIN_TOKENS)

    p_forge = sub.add_parser("forge", help="Deep recast (handles route drift)")
    p_forge.add_argument("--retain-tokens", type=int, default=DEFAULT_RETAIN_TOKENS)
    p_forge.add_argument("--target-model", default=DEFAULT_TARGET_MODEL)

    p_guard = sub.add_parser("guard", help="Check for model route drift")
    p_guard.add_argument("--target-model", default=DEFAULT_TARGET_MODEL)

    sub.add_parser("status", help="Show active session info")

    p_check = sub.add_parser("check", help="Check if swap is needed")
    p_check.add_argument("--threshold", type=float, default=AUTO_SWAP_THRESHOLD)
    p_check.add_argument("--target-model", default=DEFAULT_TARGET_MODEL)
    p_check.add_argument("--auto-swap", action="store_true", help="Auto-swap if threshold exceeded")

    p_watch = sub.add_parser("watch", help="Continuous watcher with auto-swap")
    p_watch.add_argument("--interval", type=int, default=120, help="Check interval in seconds")
    p_watch.add_argument("--threshold", type=float, default=AUTO_SWAP_THRESHOLD)
    p_watch.add_argument("--target-model", default=DEFAULT_TARGET_MODEL)

    args = parser.parse_args()

    if args.command == "swap":
        do_swap(args)
    elif args.command == "forge":
        do_forge(args)
    elif args.command == "guard":
        do_guard(args)
    elif args.command == "status":
        do_status(args)
    elif args.command == "check":
        do_auto_check(args)
    elif args.command == "watch":
        do_watch(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
