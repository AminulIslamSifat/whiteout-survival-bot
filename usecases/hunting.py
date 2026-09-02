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


def hunt_beast(count=None, use_stored_stamina=False, level=None):
    search_box = [[0, 78.86, 100, 80.49]]
    title = req_text("World.City")
    try:
        title = title[0][0].lower()
    except Exception as e:
        print(f"Reading Error - {e}")
    if title != "city":
        recalibrate()
        tap_on_text("Home.World", wait=2)
    
    tap_on_template("Global.Search", wait=2)
    tap_on_text("Beast",rois=[search_box], wait=2)
    if level:
        l = req_text("World.Search.ItemLevel")
        try:
            l = int(level[0][0])
            if level != level:
                tap_screen(84.26, 86.22)
                time.sleep(1)
                input_text(str(level))
        except Exception as e:
            print(f"Level reading Error, Continuing without reading the level...")

    tap_on_text("World.Search.Search", wait=2, sleep=1)
    tap_on_text("World.Search.Seach.Beast.Attack", wait=2)
    

def hunt_polar_terro(count=None, use_stored_stamina=False):
    return

def hunt_merchenary(stopping_level=None, use_stored_stamina=False):
    return