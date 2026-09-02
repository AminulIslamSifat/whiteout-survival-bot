"""
WOS-Bot — Headless Runner
Receives task keys via stdin JSON or --tasks CLI arg.
No interactive CLI. Controlled entirely by the dashboard API.
"""

import os
import sys
import json
import time
import argparse
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from rich.console import Console
from rich.panel import Panel

from core.core import req_text
from core.recalibrate import recalibrate
from cmd_program.screen_action import tap_screen
from core.change_player import change_account, change_character

console = Console()
COMPLETION_LOG_PATH = "db/completion_log.txt"
SKIP_WINDOW_SECONDS = 3 * 60 * 60


class Player:
    def __init__(self, name, id, state, email):
        self.name = name
        self.id = id
        self.state = state
        self.email = email


# --- Task Registry (dynamic from usecases) ---
def _discover_tasks():
    """Scan usecases/ for TASK_METADATA and build key->callable map."""
    import importlib
    usecases_dir = Path(PROJECT_ROOT) / "usecases"
    task_map = {}
    task_list = []

    for pyfile in sorted(usecases_dir.glob("*.py")):
        if pyfile.name.startswith("_"):
            continue
        module_name = f"usecases.{pyfile.stem}"
        try:
            mod = importlib.import_module(module_name)
        except Exception as e:
            print(f"⚠️ Could not import {module_name}: {e}")
            continue

        metadata = getattr(mod, "TASK_METADATA", None)
        if not metadata:
            continue

        for entry in metadata:
            key = entry["key"]
            func_name = entry["func"]
            func = getattr(mod, func_name, None)
            if func is None:
                print(f"⚠️ {module_name}.{func_name} not found, skipping {key}")
                continue
            task_map[key] = func
            task_list.append({
                "key": key,
                "title": entry["title"],
                "description": entry.get("description", ""),
            })

    return task_map, task_list


TASK_MAP, TASK_LIST = _discover_tasks()


# --- Completion Log ---
def load_completion_log():
    records = {}
    if not os.path.exists(COMPLETION_LOG_PATH):
        return records
    with open(COMPLETION_LOG_PATH, "r") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            parts = line.split("|")
            if len(parts) < 2:
                continue
            try:
                records[parts[0].strip().lower()] = float(parts[1].strip())
            except ValueError:
                continue
    return records


def save_completion_log(records):
    lines = []
    for player_id, ts in sorted(records.items()):
        iso_time = datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")
        lines.append(f"{player_id}|{ts}|{iso_time}")
    with open(COMPLETION_LOG_PATH, "w") as f:
        f.write("\n".join(lines))
        if lines:
            f.write("\n")


def should_skip_player(player_id, records):
    ts = records.get(player_id.lower())
    if ts is None:
        return False
    return (time.time() - ts) < SKIP_WINDOW_SECONDS


def mark_player_completed(player_id, records):
    records[player_id.lower()] = time.time()
    save_completion_log(records)


# --- Account Loading ---
def init_database(
    account_filter: list[str] | None = None,
    character_filter: dict[str, list[str]] | None = None,
):
    """Load accounts, optionally filtering to specific emails and/or characters.

    Args:
        account_filter: List of emails to include. None = all accounts.
        character_filter: Dict of email -> [player_ids] to include. None = all characters.
    """
    global player_data, email_list, player_list
    path = "db/account.json"
    with open(path) as f:
        raw_data = json.load(f)

    # Apply account filter if provided
    if account_filter:
        filtered = {k: v for k, v in raw_data.items() if k in account_filter}
        if not filtered:
            print(f"⚠️ No matching accounts found for filter: {account_filter}")
            print(f"   Available: {', '.join(raw_data.keys())}")
        raw_data = filtered

    # Apply character filter if provided
    if character_filter:
        for email, allowed_ids in character_filter.items():
            if email not in raw_data:
                continue
            allowed_lower = {pid.lower() for pid in allowed_ids}
            original_players = raw_data[email].get("player", [])
            filtered_players = [
                p for p in original_players
                if str(p.get("id", "")).lower() in allowed_lower
            ]
            raw_data[email]["player"] = filtered_players
            removed = len(original_players) - len(filtered_players)
            if removed > 0:
                print(f"🎮 Filtered {removed} character(s) from {email}")
        # Remove accounts with no remaining players
        empty_emails = [e for e, d in raw_data.items() if not d.get("player")]
        for e in empty_emails:
            print(f"⚠️ Removing {e} — no characters left after filter")
            del raw_data[e]

    sorted_player_data = sorted(
        raw_data.items(),
        key=lambda item: item[1].get("priority", float("inf"))
    )

    player_list = []
    email_list = []

    for email, data in sorted_player_data:
        email_list.append(email)
        for player in data["player"]:
            player_list.append(player["id"])

    player_data = sorted_player_data


# --- Player Initialization ---
current_player = None


def player_initialization():
    recalibrate()
    tap_screen(4.63, 6.1)
    time.sleep(2)
    global current_player

    try:
        time.sleep(1)
        from rapidfuzz import fuzz
        import re

        def clean_text(s):
            if not s:
                return ""
            s = s.strip()
            s = ''.join(ch for ch in s if ch.isprintable())
            s = ' '.join(s.split())
            return s

        def is_garbage(s):
            if not s:
                return True
            s = s.strip()
            if len(s) < 2:
                return True
            non_alnum = sum(1 for ch in s if not ch.isalnum() and not ch.isspace())
            if non_alnum / max(1, len(s)) > 0.6:
                return True
            return False

        def pick_best_text(ocr_results, expected=None, min_len=2):
            candidates = []
            for entry in (ocr_results or []):
                txt = entry[0] if isinstance(entry, (list, tuple)) and entry else entry
                t = clean_text(txt)
                if len(t) < min_len or is_garbage(t):
                    continue
                candidates.append(t)
            if not candidates:
                return None
            if expected:
                return max(candidates, key=lambda x: fuzz.ratio(x.lower(), expected.lower()))
            return candidates[0]

        page_title_res = req_text("ChiefProfile.Title")
        page_title = pick_best_text(page_title_res, expected="Chief Profile") or ""
        if fuzz.ratio(page_title.lower(), "chief profile".lower()) < 60:
            print("Failed to load chief profile")
            return None
    except Exception as e:
        print(f"Reading error - {e}, Ending the task")
        return None

    time.sleep(1)
    data = req_text([
        "ChiefProfile.PlayerName",
        "ChiefProfile.PlayerID",
        "ChiefProfile.FurnaceLevel",
        "ChiefProfile.State"
    ])

    def extract_after_delim(s, delim, default=None):
        if not s:
            return default
        if delim in s:
            parts = s.split(delim)
            return parts[-1].strip()
        return s.strip()

    def extract_first_number(s):
        if not s:
            return None
        m = re.search(r"\d+", s)
        return m.group(0) if m else None

    def extract_id(s):
        if not s:
            return None
        s = s.strip()
        m = re.search(r"\d{4,}", s)
        if m:
            return m.group(0)
        m = re.search(r"[A-Za-z0-9\-]{4,}", s)
        return m.group(0) if m else s

    name_raw = pick_best_text([data[0]]) if data and len(data) > 0 else None
    id_raw = pick_best_text([data[1]]) if data and len(data) > 1 else None
    furnace_raw = pick_best_text([data[2]]) if data and len(data) > 2 else None
    state_raw = pick_best_text([data[3]]) if data and len(data) > 3 else None

    name = extract_after_delim(name_raw, ']') if name_raw else None
    id_val = extract_id(id_raw) if id_raw else None
    furnace = extract_first_number(furnace_raw) if furnace_raw else None
    state = extract_after_delim(state_raw, '#') if state_raw else (state_raw or None)

    current_player_id = None
    current_email = None

    for email, info in player_data:
        for player in info["player"]:
            if player.get("id") == id_val.lower():
                current_player_id = player.get("id")
                current_email = email

    if current_player_id is None or current_email is None:
        print("No player data found for this ID, Exiting this character...")
        raise RuntimeError("Player Initialization Failed, Stopping the Bot...")

    current_player = Player(name, id_val, state, current_email)
    console.print(Panel.fit(
        f"Email: {current_email}\nName:{name}\nID: {id_val}\nFurnace Level: {furnace}\nState: {state}",
        title="[bold magenta]🎮 Player Summary[/bold magenta]",
        border_style="bright_blue"
    ))


def get_next_email(current_email):
    if not email_list:
        return None
    try:
        idx = email_list.index(current_email)
        return email_list[(idx + 1) % len(email_list)]
    except ValueError:
        return email_list[0]


def get_players_by_email(target_email):
    for email, info in player_data:
        if email == target_email:
            return info.get("player", [])
    return []


def run_selected_tasks(current_player_id, selected_task_keys):
    for key in selected_task_keys:
        func = TASK_MAP.get(key)
        if func is None:
            print(f"⚠️ Unknown task key: {key}")
            continue
        print(f"▶ Running task: {key}")
        try:
            # Some tasks accept player_id, some don't
            import inspect
            sig = inspect.signature(func)
            if len(sig.parameters) > 0:
                func(current_player_id)
            else:
                func()
        except Exception as e:
            print(f"❌ Task {key} failed: {e}")


def run_bot(selected_task_keys):
    completion_records = load_completion_log()

    while True:
        player_initialization()

        current_email = current_player.email
        next_email = get_next_email(current_email)

        current_email_players = get_players_by_email(current_email)
        if not current_email_players:
            raise RuntimeError(f"No players configured for email: {current_email}")

        processed_ids = set()

        while len(processed_ids) < len(current_email_players):
            active_id = current_player.id.lower()
            if active_id not in processed_ids:
                if should_skip_player(current_player.id, completion_records):
                    last_ts = completion_records.get(active_id)
                    last_time = datetime.fromtimestamp(last_ts).strftime("%Y-%m-%d %H:%M:%S")
                    print(f"Skipping {current_player.name} ({current_player.id}) - completed recently at {last_time}")
                else:
                    print(f"Running tasks for: {current_player.name} ({current_player.id})")
                    run_selected_tasks(current_player.id, selected_task_keys)
                    mark_player_completed(current_player.id, completion_records)
                    print(f"Marked completed: {current_player.id} at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
                processed_ids.add(active_id)

            next_player = next(
                (p for p in current_email_players if p["id"].lower() not in processed_ids),
                None,
            )

            if not next_player:
                break

            print(f"Switching to sibling character: {next_player['name']}")
            change_character(next_player["name"])
            player_initialization()

            if current_player.email != current_email:
                raise RuntimeError(
                    f"Unexpected email after character switch. Expected {current_email}, got {current_player.email}"
                )

        print(f"Progressing to the next email: {next_email}")
        status = change_account(next_email)
        if not status:
            raise RuntimeError("Account changing error")


def main():
    parser = argparse.ArgumentParser(description="WOS-Bot Headless Runner")
    parser.add_argument("--tasks", type=str, help="Comma-separated task keys")
    args = parser.parse_args()

    # Determine task keys + optional filters: CLI arg > stdin JSON > fail
    task_keys = None
    account_filter = None
    character_filter = None

    if args.tasks:
        task_keys = [k.strip() for k in args.tasks.split(",") if k.strip()]
    elif not sys.stdin.isatty():
        # Read JSON from stdin (dashboard sends this)
        try:
            raw = sys.stdin.read().strip()
            if raw:
                data = json.loads(raw)
                if isinstance(data, dict) and "tasks" in data:
                    task_keys = data["tasks"]
                    account_filter = data.get("accounts")  # optional email filter
                    character_filter = data.get("characters")  # optional char filter
                elif isinstance(data, list):
                    task_keys = data
        except (json.JSONDecodeError, Exception) as e:
            print(f"❌ Failed to parse stdin: {e}")
            sys.exit(1)

    if not task_keys:
        print("❌ No tasks specified. Use --tasks=key1,key2 or pipe JSON via stdin.")
        print(f"Available tasks: {', '.join(t['key'] for t in TASK_LIST)}")
        sys.exit(1)

    # Validate
    valid_keys = set(TASK_MAP.keys())
    invalid = [k for k in task_keys if k not in valid_keys]
    if invalid:
        print(f"❌ Invalid task keys: {invalid}")
        print(f"Available: {', '.join(sorted(valid_keys))}")
        sys.exit(1)

    print(f"✅ Starting bot with tasks: {', '.join(task_keys)}")
    if account_filter:
        print(f"👤 Account filter: {', '.join(account_filter)}")
    if character_filter:
        for email, ids in character_filter.items():
            print(f"🎮 Character filter for {email}: {', '.join(ids)}")
    print(f"📋 Discovered {len(TASK_MAP)} tasks from usecases/")

    init_database(account_filter=account_filter, character_filter=character_filter)
    run_bot(task_keys)


if __name__ == "__main__":
    main()
