import os
import sys
import cv2
import time
import json
import requests
import subprocess
import numpy as np
from datetime import datetime
from rich.panel import Panel
from rich.console import Console
from rapidfuzz import fuzz
import re

from cmd_program.screen_action import (
    tap_screen,
    swipe_screen,
    long_press,
    take_screenshot
)

from core.core import (
    req_ocr,
    req_temp_match,
    tap_on_template,
    req_text
)

from usecases.exploration import(
    claim_exploration_idle_income,
    continue_exploring
)
from usecases.alliance import(
    tech_contribution,
    auto_join,
    collect_chests,
    collect_triumph,
    help
)
from usecases.vip import (
    collect_vip_rewards,
    buy_vip_time
)
from usecases.heal import (
    heal
)
from usecases.arena import (
    arena
)
from usecases.mail import (
    collect_mail_rewards
)
from usecases.training_troops import(
    train,
    train_lancer,
    train_infantry,
    train_marksman
)
from usecases.intel import (
    intel
)
from usecases.collect import (
    collect_missions_reward,
    collect_life_essence,
    collect_from_events
)
from usecases.chief_order import(
    activate_chief_order
)
from usecases.pet import (
    collect_ally_treasure,
    start_pet_exploration
)
from usecases.labyrinth import labyrinth

from core.recalibrate import recalibrate
from core.change_player import change_account, change_character

from Main.task_menu import prompt_task_selection, run_selected_tasks
from core.player_profile import load_profile, save_profile





class Player:
    def __init__(self, name, id, state, email):
        self.name = name
        self.id = id
        self.state = state
        self.email = email 


COMPLETION_LOG_PATH = "db/completion_log.txt"
SKIP_WINDOW_SECONDS = 3 * 60 * 60
console = Console()



def start_game(game_name="com.gof.global/com.unity3d.player.MyMainPlayerActivity"):
    # Pin the device when WOS_ADB_SERIAL is set (run.sh always sets it) —
    # bare adb fails with "more than one device" when MuMu also registers
    # its emulator-5554 alias.
    serial = os.getenv("WOS_ADB_SERIAL")
    wos_adb_command = (
        ["adb"] + (["-s", serial] if serial else []) + [
        "shell",
        "am",
        "start",
        "-n",
        game_name
    ])
    # adb inherits and drains stdin; DEVNULL keeps it away from the task
    # selector's input(), which is the only stdin reader in this program.
    subprocess.run(wos_adb_command, stdin=subprocess.DEVNULL)



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

            player_id = parts[0].strip().lower()
            try:
                ts = float(parts[1].strip())
            except ValueError:
                continue

            records[player_id] = ts

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




def init_database():
    global player_data, email_list, player_list
    path = "db/account.json"
    with open(path) as f:
        player_data = json.load(f)
    
    sorted_player_data = sorted(
        player_data.items(),
        key = lambda item: item[1].get("priority", float("inf"))
    )

    player_list = []
    email_list = []

    for email, data in sorted_player_data:
        email_list.append(email)
        for player in data["player"]:
            player_list.append(player["id"])

    player_data = sorted_player_data



def player_initialization():
    recalibrate()
    tap_screen(4.63, 6.1)
    time.sleep(2)
    global current_player
    try:
        time.sleep(1)
        # read and sanitize page title using OCR filtering helpers
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
            # ocr_results is list of [text, box]
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

    data = req_text(
        [
            "ChiefProfile.PlayerName",
            "ChiefProfile.PlayerID", 
            "ChiefProfile.FurnaceLevel", 
            "ChiefProfile.State"
        ],
        read_kind="value"
    )

    # safer extraction/helpers
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
        # prefer sequences of digits or alnum of length >=4
        m = re.search(r"\d{4,}", s)
        if m:
            return m.group(0)
        m = re.search(r"[A-Za-z0-9\-]{4,}", s)
        return m.group(0) if m else s

    # pick best text per field
    name_raw = pick_best_text([data[0]]) if data and len(data) > 0 else None
    id_raw = pick_best_text([data[1]]) if data and len(data) > 1 else None
    furnace_raw = pick_best_text([data[2]]) if data and len(data) > 2 else None
    state_raw = pick_best_text([data[3]]) if data and len(data) > 3 else None

    # cleanup and extract values
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

    # Seed/refresh the on-disk profile (db/players/<id>.json, example.json
    # schema) with what this session observed; tasks read evolving fields
    # (e.g. gather node level) from it.
    profile = load_profile(id_val)
    profile["name"] = name
    if state:
        profile["state"] = state
    if furnace:
        profile["furnace_level"] = int(furnace)
    save_profile(profile)

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



def run_task(current_player_id, selected_tasks):
    run_selected_tasks(current_player_id, selected_tasks)




def run_bot(selected_tasks):
    completion_records = load_completion_log()

    while True:
        player_initialization()

        #----Config----
        current_email = current_player.email
        next_email = get_next_email(current_email)

        #----- Run all characters under current email -----
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
                    run_task(current_player.id, selected_tasks)
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

        if len(email_list) == 1:
            print(f"Single account configured ({current_email}) - pass complete, exiting.")
            return

        print(f"Progressing to the next email: {next_email}")
        status = change_account(next_email)
        if not status:
            raise RuntimeError("Account changing error")



if __name__=="__main__":
    # Side effects live here, not at module scope, so tests can import Main.main.
    # Runtime order for `python -m Main.main` is unchanged.
    start_game()
    init_database()
    selected_tasks = prompt_task_selection()
    run_bot(selected_tasks)
