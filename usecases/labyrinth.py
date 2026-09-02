TASK_METADATA = [
    {"key": "labyrinth", "title": "Labyrinth", "description": "Run the labyrinth routine.", "func": "labyrinth"},
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
    tap_on_closest_text,
)

from core.logging_config import get_logger

logger = get_logger(__name__)

# percentages passed directly; runtime conversion will occur

missions_title_area = [0, 79.67, 100, 85.37]
missions_area = [0, 18.7, 100, 79.27]

def go_to_labyrinth():
    tap_on_template("Home.Missions", wait=2)
    status = tap_on_text("Daily Missions", rois=[missions_title_area], wait=2)
    
    if not status:
        return False
    
    base = "complete 1 challenges in the labrynth"
    target = "go"
    for _ in range(10):
        status = tap_on_text(base, wait=2, threshold=0.7, tap=False)
        if not status:
            swipe_screen(50.93, 56.91, 50.93, 38.21, duration=1500)
            time.sleep(0.5)
            continue
        status = tap_on_closest_text(base, target, rois=[missions_area], wait=2, maximum_distance=20.33)
        if status:
            return status
    return False

def labyrinth():
    recalibrate()
    labyrinth_list = [
        "Home.Labyrinth.CaveOfMonster",
        "Home.Labyrinth.CharmMine",
        "Home.Labyrinth.ResearchCenter",
        "Home.Labyrinth.GearForge",
        "Home.Labyrinth.GaiaHeart"
    ]
    status = tap_on_template("Home.Labyrinth", sleep=1)
    if not status:
        status = go_to_labyrinth()
        if not status:
            logger.info("Labyrinth task is already completed, Exiting the task")
            return None
    
    for lab in labyrinth_list:
        status = tap_on_text(lab, wait=2)
        if not status:
            continue
        status = tap_on_text("Home.Labyrinth.Raid", wait=2)
        if status:
            tap_on_text("Home.Labyrinth.Raid.Claim", wait=2)
        status = tap_on_text("Home.Labyrinth.Challenge", wait=2)
        if not status:
            continue
        status = tap_on_text("Home.Labyrinth.Challenge.Deploy", wait=2)
        if not status:
            tap_on_template("Global.Back")
            continue
        
        while True:
            tap_on_text("Home.Labyrinth.Challenge.Skip", wait=3, threshold=0.5)
            status = tap_on_text("Home.Labyrinth.Challenge.Victory.Title", wait=2, tap=False)
            if status:
                status = tap_on_text("Home.Labyrinth.Challenge.Victory.Next", wait=2)
                if not status:
                    tap_on_text("Home.Labyrinth.Challenge.Victory.NextChapter", wait=2, sleep=4)
                    tap_on_text("Home.Labyrinth.Challenge", wait=2)
                    tap_on_text("Home.Labyrinth.Challenge.Deploy", wait=2)
                continue
            status = tap_on_text("Home.Labyrinth.Challenge.Defeat.Title", wait=2, tap=False)
            if status:
                remaining_attempts = 0

                try:
                    remaining_attempts = req_text("Home.Labyrinth.Challenge.Defeat.RemainingAttempts")
                    remaining_attempts = int(remaining_attempts[0][0])
                    if remaining_attempts > 5 or remaining_attempts == 0:
                        remaining_attempts = 0
                except Exception as e:
                    remaining_attempts = 0
                
                if remaining_attempts == 0:
                    tap_screen(50.93, 81.3)
                    time.sleep(1)
                    tap_on_template("Global.Back")
                    break

                tap_on_text("Home.Labyrinth.Challenge.Defeat.Retry", wait=2)
        

    return True

