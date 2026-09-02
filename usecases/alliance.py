TASK_METADATA = [
    {"key": "alliance_tech", "title": "Alliance Tech", "description": "Contribute to alliance tech.", "func": "tech_contribution"},
    {"key": "alliance_join", "title": "Alliance Auto Join", "description": "Auto-join alliance activity.", "func": "auto_join"},
    {"key": "alliance_chests", "title": "Alliance Chests", "description": "Collect alliance chests.", "func": "collect_chests"},
    {"key": "alliance_help", "title": "Alliance Help", "description": "Send alliance help.", "func": "help"},
    {"key": "alliance_triumph", "title": "Alliance Triumph", "description": "Collect triumph rewards.", "func": "collect_triumph"},
]

import time

from core.logging_config import get_logger
from core.recalibrate import recalibrate

logger = get_logger(__name__)

from core.core import (
    req_ocr,
    req_text,
    tap_on_text,
    req_temp_match,
    tap_on_template,
    tap_on_templates_batch
)
from cmd_program.screen_action import(
    tap_screen,
    swipe_screen
)
from core.coord_utils import pct_to_px







def tech_contribution():
    time.sleep(0.5)
    title = req_text("Home.Alliance.Title")
    try:
        title = title[0][0].lower()
    except Exception as e:
        logger.warning("Title Reading Error, Ignoring the read...")
    if title != "alliance":
        recalibrate()
        tap_on_text("Home.Alliance", wait=2)
    tap_on_text("Home.Alliance.Tech", wait=2)
    tap_on_template("Home.Alliance.Tech.Recommended", wait=2)
    tap_on_text("Home.Alliance.Tech.Contribute.FreeContribute", hold=7000, wait=2)
    tap_on_template("Global.Close", wait=2)
    tap_on_template("Global.Back", wait=2)
    return True

def auto_join():
    time.sleep(0.5)
    title = req_text("Home.Alliance.Title")
    try:
        title = title[0][0].lower()
    except Exception as e:
        logger.warning("Title Reading Error, Ignoring the read...")
    if title != "alliance":
        recalibrate()
        tap_on_text("Home.Alliance", wait=2)
    tap_on_text("Home.Alliance.War", wait=2)
    status = tap_on_text("Home.Alliance.War.AutoJoin", wait=2)
    if not status:
        tap_on_text("Home.Alliance.War.AutoJoining", wait=2)
    status = tap_on_text("Home.Alliance.War.AutoJoin.Enable", wait=2)
    if not status:
        tap_on_text("Home.Alliance.War.AutoJoin.Restart", wait=2)
    tap_on_template("Global.Close", wait=2)
    tap_on_template("Global.Back", wait=2)
    return True

def collect_chests():
    time.sleep(0.5)
    title = req_text("Home.Alliance.Title")
    try:
        title = title[0][0].lower()
    except Exception as e:
        logger.warning("Title Reading Error, Ignoring the read...")
    if title != "alliance":
        recalibrate()
        tap_on_text("Home.Alliance", wait=2)
    tap_on_text("Home.Alliance.Chests", wait=2)
    tap_on_text("Home.Alliance.Chests.LootChest",wait=2)
    status = tap_on_text("Home.Alliance.Chests.LootChest.ClaimAll", wait=2)
    if status:
        tap_on_text("Home.Alliance.Chests.LootChest.ClaimAll.TapAnywhereToExit", wait=2)
    tap_on_text("Home.Alliance.Chests.AllianceGift", wait=2, sleep=1)
    status = True
    while status:
        status = tap_on_text("claim", wait=2, sleep=1, threshold=1.0)
        if not status:
            swipe_screen(50.93, 48.78, 50.93, 32.52)
            status = tap_on_text("claim", wait=2, sleep=1, threshold=1.0)

    tap_on_template("Home.Alliance.Chests.HonorChest", wait=2)
    tap_on_text("Home.Alliance.Chests.HonorChest.TapAnywhereToExit", wait=2)
    tap_on_template("Global.Back", wait=2)
    return True


def help():
    time.sleep(0.5)
    title = req_text("Home.Alliance.Title")
    try:
        title = title[0][0].lower()
    except Exception as e:
        logger.warning("Title Reading Error, Ignoring the read...")
    if title != "alliance":
        recalibrate()
        tap_on_text("Home.Alliance", wait=2)
    tap_on_text("Home.Alliance.Help", wait=2)
    tap_on_text("Home.Alliance.Help.HelpAll", wait=2)
    tap_on_template("Global.Back", wait=2)
    return True

def shop():
    return



def collect_triumph():
    time.sleep(0.5)
    title = req_text("Home.Alliance.Title")
    try:
        title = title[0][0].lower()
    except Exception as e:
        logger.warning("Title Reading Error, Ignoring the read...")
    if title != "alliance":
        recalibrate()
        tap_on_text("Home.Alliance", wait=2)

    tap_on_text("Home.Alliance.Triumph", wait=2)
    for i in range(2):
        tap_on_template("Home.Alliance.Triumph.WeeklyAllianceTriumphChest", wait=2, sleep=0.5)
    
    text = req_text("Home.Alliance.Triumph.ActivityTriumphPoints")
    try:
        activity_points = text[0][0].split("/")
        activity_points  = [int(a.replace(",", "")) for a in activity_points]
        if activity_points[0] > activity_points[1]:
            tap_on_text(text[0][0], align=[0, -1.22])
    except Exception as e:
        logger.warning("Reading Error - %s", e)

