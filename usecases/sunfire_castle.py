import os
import sys
import time

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

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




def attack():
    return

def heal():
    while True:
        tap_screen(747, 2118, coord=True)
        time.sleep(1)
        tap_screen(330, 330, coord=True)
        time.sleep(0.3)
        tap_screen(351, 570, coord=True)
        time.sleep(1)
        tap_screen(550, 1180, coord=True)
        time.sleep(1)
        tap_on_text("attack",wait=3, sleep=1)
        tap_on_text("World.Deploy.Deploy", sleep=1)
        time.sleep(1)
        tap_screen(835, 2118, coord=True)
        time.sleep(1)
        tap_screen(90, 850, coord=True)
        time.sleep(60)
        tap_screen(90, 850, coord=True)


heal()