TASK_METADATA = [
    {"key": "heal", "title": "Heal", "description": "Run healing workflow.", "func": "heal"},
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




def heal():
    time.sleep(0.5)
    title = req_text("World.City")
    try:
        title = title[0][0].lower()
    except Exception as e:
        logger.warning("Reading Error - %s", e)
    if title != "city":
        recalibrate()
        tap_on_text("Home.World", wait=2)

    time.sleep(1)
    status = tap_on_template("World.Heal", wait=3)
    if status:
        tap_on_text("World.Heal.QuickSelect")
        tap_on_text("World.Heal.Heal", wait=2)
        tap_on_text("World.Heal.Help", wait=2)
        tap_on_text("World.City", wait=3)
    else:
        logger.info("No troops to heal, Continuing to the next task...")
    return True
