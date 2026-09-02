#coming soon
import time
from core.logging_config import get_logger
from core.core import (
    tap_on_template,
    tap_on_text,
    req_text,
    tap_on_templates_batch
)
from cmd_program.screen_action import(
    tap_screen,
    swipe_screen
)
from core.recalibrate import recalibrate
from rapidfuzz import fuzz
# use dynamic percentage taps; do not convert to pixels here

logger = get_logger(__name__)










def change_account(next_email):
    recalibrate()
    tap_screen(9.26, 6.9)
    tap_on_text("ChiefProfile.Settings", wait=2)
    tap_on_text("ChiefProfile.Settings.Account", wait = 2, sleep=2)
    tap_on_text("ChiefProfile.Settings.Account.ChangeAccount", wait=5, sleep=0.5)
    tap_on_text("ChiefProfile.Settings.Account.ChangeAccount.SignInWithGoogle", wait=5)
    status = tap_on_text(next_email, wait=5)
    if not status:
        swipe_screen(50.93, 73.17, 50.93, 16.26)
        status = tap_on_text(next_email, wait=10, threshold=1.0)
        if not status:
            logger.error("Email not found, Exiting...")
            return None
    tap_on_text("ChiefProfile.Settings.Account.ChangeAccount.SignInWithGoogle.Continue", wait=20, sleep=2)
    recalibrate(timeout=80)
    return True




def change_character(next_name):
    recalibrate()
    tap_screen(9.26, 6.9)
    tap_on_text("ChiefProfile.Title", wait=2, tap=False)
    time.sleep(1)
    text = req_text("ChiefProfile.Title")[0][0]
    if text.lower() != "chief profile":
        logger.error("Chief Profile not found, Exiting...")
        return None
    tap_on_text("ChiefProfile.Settings", wait=1)
    tap_on_text("ChiefProfile.Settings.Characters", wait=2)
    time.sleep(1)
    players = req_text()
    names = []
    for player in players:
        try:
            name = player[0].split(']')[1].lower()
        except Exception:
            name = player[0].lower()
        names.append(name)

    # normalize names: if `next_name` appears inside a detected name, strip everything bfore it
    target = next_name.lower().strip()
    players_match_value = {}
    for idx, name in enumerate(names):
        proc_name = name
        pos = name.find(target)
        if pos != -1:
            proc_name = name[pos:]
        # compute fuzzy ratio against the processed name
        r = fuzz.ratio(target, proc_name)
        players_match_value[idx] = r

    threshold = 70  # corresponds to 0.7 similarity
    candidates = [(idx, score) for idx, score in players_match_value.items() if score >= threshold]
    if not candidates:
        logger.error("No matching player found with sufficient similarity, Exiting...")
        return None

    best_idx, best_score = max(candidates, key=lambda x: x[1])
    box = players[best_idx][1]
    coord = ((box[0] + box[2]) // 2, (box[1] + box[3]) // 2)
    tap_screen(coord, coord=True)
    
    tap_on_text("ChiefProfile.Settings.Characters.Login.Confirm", wait=2, sleep=2)
    recalibrate(timeout=80)
    return True



