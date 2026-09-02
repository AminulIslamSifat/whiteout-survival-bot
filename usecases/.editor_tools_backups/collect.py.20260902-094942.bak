import time
from core.recalibrate import recalibrate

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
    swipe_screen,
    input_text
)
# pass percentages to tap/swipe; conversion happens at action layer


side_panel = [0, 28.05, 62.04, 67.07]
missions_title_area = [0, 79.67, 100, 85.37]



def collect_missions_reward():
    recalibrate()
    tap_on_template("Home.Missions", wait=2)
    status = tap_on_text("growth missions", rois=[missions_title_area], wait=2, sleep=1)
    while status:
        status = tap_on_text("Home.Missions.GrowthMissions.Claim", wait=2)
    tap_on_text("daily missions", rois=[missions_title_area], wait=2)
    tap_on_text("Home.Missions.DailyMissions.ClaimAll", wait=2)
    tap_on_text("Home.Missions.TapAnywhereToExit", wait=2)



def collect_life_essence():
    recalibrate()
    status = tap_on_template("Global.SidePanel", wait=3, sleep=0.5, threshold=0.5)
    if not status:
        print("Side panel not found")
        tap_screen(0.37, 44.84)
        return None
    for _ in range(2):
        swipe_screen(32.41, 65.04, 32.41, 32.52)
        time.sleep(2)
    status = tap_on_text("Tree of Life", rois=[side_panel], sleep=6)
    if not status:
        print("Tree of life not found, Exiting..")
        status = tap_on_text("Global.SidePanel.City", tap=False)
        if status:
            status = tap_on_template("Global.SidePanel", wait=2, threshold=0.5)
            if not status:
                tap_screen(62.96, 44.88)
        return None
    tap_screen(50.93, 50.41)           # to remove instructor hand
    time.sleep(0.3)
    for i in range(3):
        swipe_screen(10.19, 38.62, 55.56, 50.81)
        time.sleep(2.5)
        status = tap_on_template("Global.Island.TimberMill.EssenceOfLife", wait=0.3)
        if status:
            break
    



def collect_from_events():
    box = [5.56, 14.43, 97.22, 16.26]
    recalibrate()
    tap_on_template("Home.Store", wait=2)
    
    status = True
    while(status):
        status = tap_on_text("claimable", rois=[[0, 0, 100, 43.9]], wait=2, align=[0, -2.03])
        if not status:
            status = tap_on_text("free", rois = [0, 0, 100, 43.9], wait=2)
            if status:
                tap_on_text("Tap anywhere to exit", wait=2, align=[0, 2.03])
        if status:
            tap_on_template("Global.Back", threshold=0.6, wait=2)
            tap_on_template("Home.Store", wait=2)
        else:
            tap_on_template("Global.Back", threshold=0.6, wait=2)
    
