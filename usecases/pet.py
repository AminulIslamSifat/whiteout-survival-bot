TASK_METADATA = [
    {"key": "pet_treasure", "title": "Ally Treasure", "description": "Collect ally treasure.", "func": "collect_ally_treasure"},
    {"key": "pet_exploration", "title": "Pet Exploration", "description": "Start pet exploration.", "func": "start_pet_exploration"},
]

import time
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

from core.logging_config import get_logger

logger = get_logger(__name__)

# use percentage taps so screen_action handles conversion

def collect_ally_treasure():
    recalibrate()
    status = tap_on_template("Home.Pet", wait=2)
    if not status:
        return None
    tap_on_text("Home.Pet.Skill.BeastCage", sleep=1, wait=2)
    tap_on_text("Home.Pet.BeastCage.Adventure", wait=2)
    tap_on_text("Home.Pet.BeastCage.Adventure.AllyTreasure", wait=2, align=[0, -2.03])
    tap_on_text("Home.Pet.BeastCage.Adventure.AllyTreasure.AllianceShares", wait=2, sleep=0.5)
    tap_on_text("Home.Pet.BeastCage.Adventure.AllyTreasure.AllianceShares.ClaimAll", wait=2)
    tap_on_text("Tap anywhere to exit", sleep=1)
    tap_on_text("Home.Pet.BeastCage.Adventure.AllyTreasure.MyShares", wait=2)
    tap_on_text("Home.Pet.BeastCage.Adventure.AllyTreasure.MyShares.Share", wait=2, sleep=1)
    return True

def start_pet_exploration():
    exploration_roi = [0, 16.26, 100, 89.43]

    def center(box):
        x1, y1, x2, y2 = box
        return ((x1 + x2) // 2, (y1 + y2) // 2)
    
    def distance(c1, c2):
        return ((c1[0]-c2[0])**2 + (c1[1]-c2[1])**2)**0.5

    recalibrate()

    status = tap_on_template("Home.Pet", wait=2)
    if not status:
        return None
    
    tap_on_text("Home.Pet.Skill.BeastCage", sleep=1, wait=2)
    tap_on_text("Home.Pet.BeastCage.Adventure", wait=2, sleep=2)
    text = req_text(["Home.Pet.BeastCage.Adventure.RemainingAttempt", "Home.Pet.BeastCage.Adventrue.AdventureGround"])
    
    adventuring = 0
    remaining_attempts = 4
    
    try:
        remaining_attempts = int(text[0][0])
        for t in text:
            if len(t[0].split(":")) == 3:
                adventuring += 1
    except Exception as e:
        logger.error("Reading Error - %s, Exiting the task...", e)
        return None

    status = True
    while(status):
        status = tap_on_template("Home.Pet.BeastCage.Adventure.CompletedAdventure", wait=2)
        if not status:
            logger.info("No adventure Completed")
            break
        if tap_on_text("Home.Pet.BeastCage.Adventure.Completed", wait=2, tap=False):
            tap_screen(51.85, 62.60)
            tap_on_text("Tap anywhere to exit", wait=4, sleep=0.5)
            tap_on_template("Global.Close", wait=2)

    while(adventuring<3 and remaining_attempts>0):
        text = req_text(["Home.Pet.BeastCage.Adventure.RemainingAttempt", "Home.Pet.BeastCage.Adventrue.AdventureGround"])
        try:
            remaining_attempts = int(text[0][0])
            for t in text:
                if len(t[0].split(":")) == 3:
                    adventuring += 1
        except Exception as e:
            logger.error("Reading Error - %s, Exiting the task...", e)
            adventuring += 1
            remaining_attempts -= 1
        logger.info("Remaining Attempt: %s, Adventuring: %s", remaining_attempts, adventuring)

        treasure_boxs = [
            "Home.Pet.BeastCage.Adventure.RedTreasure",
            "Home.Pet.BeastCage.Adventure.PurpleTreasure",
            "Home.Pet.BeastCage.Adventure.BlueTreasure"
        ]

        boxes = []
        for treasure_box in treasure_boxs:
            r = req_temp_match(treasure_box)
            if r:
                for item in r:
                    boxes.append(item)
        
        text = req_text("Home.Pet.BeastCage.Adventrue.AdventureGround")
        treasures = []
        for box in boxes:
            valid = True
            for t in text:
                d = distance(center(box["box"]), center(t[1]))
                if d < 8.13:
                    valid = False
            if valid:
                treasures.append(box)

        for treasure in treasures:
            treasure = center(treasure["box"])
            # treasure center is in pixels (from template matching)
            tap_screen(treasure, coord=True)
            time.sleep(0.5)

            status = tap_on_text("Home.Pet.BeastCage.Adventure.Treasure.InAdventure", wait=2, tap=False)
            if status:
                tap_on_template("Global.Close", wait=2)
                continue
            status = tap_on_text("Home.Pet.BeastCage.Adventure.SelectPet", wait=2, sleep=1)
            if status:
                status = tap_on_text("Home.Pet.BeastCage.Adventure.SelectPet.Start", wait=2)
                if not status:
                    status = tap_on_text("Home.Pet.BeastCage.Adventure.SelectPet.InsuffiecientAdventureAttempts", wait=2, tap=False)
                    if status:
                        logger.warning("Insufficient Adventure Attempts")
                        tap_on_template("Global.Close", wait=2, sleep=0.5)
                        tap_on_template("Global.Close", wait=2)
                        continue
                    continue
                adventuring += 1
                remaining_attempts -= 1
                tap_on_template("Global.Close", wait=2)
                continue
            status = tap_on_text("Home.Pet.BeastCage.Adventure.Completed", wait=2, tap=False)
            if status:
                tap_screen(51.85, 62.60)
                tap_on_text("Tap anywhere to exit", wait=2, sleep=0.5)
                tap_on_template("Global.Close", wait=2)
                continue
            else:
                logger.error("Something went wrong")

    logger.info("Task - Pet Exploration Completed, Returning to homepage...")

def activate_reward_pet_skill():
    return

def activate_war_pet_skill():
    return
