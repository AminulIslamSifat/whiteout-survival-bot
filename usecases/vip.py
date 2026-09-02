TASK_METADATA = [
    {"key": "vip", "title": "VIP Rewards", "description": "Collect VIP rewards before anything else.", "func": "collect_vip_rewards"},
]

import time

from core.logging_config import get_logger

logger = get_logger(__name__)

from usecases._compat import (
    req_ocr,
    req_text,
    tap_on_text,
    req_temp_match,
    tap_on_template,
    tap_on_templates_batch,
    tap_screen,
    swipe_screen,
    input_text,
    recalibrate,
)




def collect_vip_rewards():
    recalibrate()
    tap_on_text("Home.VIPLevel", wait=2)

    status = tap_on_template("Home.VIP.CollectChest", wait=2, sleep=1)
    if status:
        tap_on_text("click to continue", wait=2, align=[0, -16.26])
    status = tap_on_text("Home.VIP.Claim", wait=3)
    if status:
        tap_on_text("Home.VIP.Claim.TapAnywhereToExit", wait=2)
    recalibrate()
    return True

    

def buy_vip_time(day=30):
    time.sleep(0.5)
    title = req_text("Home.VIP.Title")
    try:
        title = title[0][0]
    except Exception as e:
        logger.warning("Error while reading page title - %s, Continuing...", e)
    
    if title.lower != "vip":
        recalibrate()
        tap_on_text("Home.VIPLevel", wait=2)

    
