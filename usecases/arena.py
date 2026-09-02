import time
from core.recalibrate import recalibrate

from core.core import (
    req_ocr,
    req_text,
    tap_on_text,
    req_temp_match,
    tap_on_template,
    tap_on_templates_batch,
    tap_on_closest_text
)
from cmd_program.screen_action import(
    tap_screen,
    swipe_screen,
    input_text
)
from core.coord_utils import pct_to_px




missions_title_area = [0, 79.67, 100, 85.37]
missions_area = [0, 18.7, 100, 79.27]



def challenge_lowest_power():
    challenge_icons = [
        {'box': [81.76, 33.13, 91.3, 37.4]}, 
        {'box': [81.76, 40.93, 91.3, 45.2]}, 
        {'box': [81.76, 48.78, 91.3, 53.05]}, 
        {'box': [81.76, 56.59, 91.3, 60.86]}, 
        {'box': [81.76, 64.43, 91.3, 68.7]}
    ]
    powers = []
    time.sleep(0.5)
    res = req_ocr(rois=[[20.37, 33.13, 91.3, 68.7]])
    try:
        for item in res:
            text = item.get("text", "")
            text = text.replace(",", "").replace(".", "")
            if text.endswith("M") and text[:-1].isdigit():
                powers.append(int(text[:-1])*100000)
            elif text.isdigit() and int(text) > 50000:
                powers.append(int(text))
    except Exception as e:
        print(f"Power Reading Error - {e}")

    if powers:
        lowest_power = min(powers) if len(powers) > 0 else 0
        i = powers.index(lowest_power)
        tap_on_template("Home.Arena.Challenge.Challenge", rois=[challenge_icons[i]["box"]], wait=2)
    else:
        tap_on_template("Home.Arena.Challenge.Challenge", wait=2)




def find_arena():
    tap_on_template("Home.Missions", wait=2)
    status = tap_on_text("Daily Missions", rois=[missions_title_area], wait=2)
    
    if not status:
        return False
    
    base = "Fight in 1 Arena Challenge(s)"
    target = "go"
    for _ in range(10):
        status = tap_on_text(base, wait=2, threshold=0.7, tap=False)
        if not status:
            swipe_screen(50.93, 56.91, 50.93, 38.21, duration=1500)
            time.sleep(0.5)
            continue
        status = tap_on_closest_text(base, target, rois=[missions_area], wait=2, maximum_distance=24.39)
        if status:
            return status
    return False



def arena():
    attempt = 0
    recalibrate()
    print("Starting the fight in Arena of Glory...")

    availabe = find_arena()
    if not availabe:
        print("Arena challenge is not availabe, Ending the task")
        return None
    tap_on_text("Home.Arena.Challenge", wait=2, sleep=1)

    res = req_ocr(rois=[[27.78, 70.12, 61.57, 74.39]])

    try:
        attempt = int(res[0]['text'].split(":")[1])
    except Exception as e:
        print(f"Attempt Reading error -{e}")

    while(attempt > 0):
        res = req_ocr(rois=[[27.78, 70.12, 61.57, 74.39]])
        try:
            attempt = int(res[0]['text'].split(":")[1]) - 1
            print(f"Remaining Challenge {attempt}")
        except Exception as e:
            print(f"Attempt counting error -{e}")

        challenge_lowest_power()

        tap_on_text("Home.Arena.Challenge.Challenge.QuickDeploy", sleep=0.1)
        tap_on_text("Home.Arena.Challenge.Challenge.Fight", wait=2, sleep=3)
        tap_on_template("Home.Arena.Challenge.Challenge.Fight.Pause", wait=5)
        tap_on_template("Home.Arena.Challenge.Challenge.Fight.Pause.Retreat", wait=2)
        status = tap_on_text("Home.Arena.Challenge.Challenge.Fight.End.Title", tap=False, wait=3)
        if status:
            tap_on_text("Home.Arena.Challenge.Challenge.Fight.End.TapAnywhereToExit", wait=2)
            tap_on_text("Home.Arena.Challenge.FreeRefresh", wait=2, sleep=1)
        else:
            tap_on_text("Home.Arena.Challenge.Challenge.Fight.End.TapAnywhereToExit", wait=5)
        
    print("Finished the task - Arena Of Glory, Returning to homepage...")
    recalibrate()



