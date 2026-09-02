import time
import requests
from core.core import req_ocr, tap_on_template, tap_on_text, tap_on_templates_batch, req_text
from cmd_program.screen_action import tap_screen
from core.coord_utils import percent_to_pixel
from core.logging_config import get_logger

logger = get_logger(__name__)


def recalibrate(timeout=30):
    is_home = False
    retry = 0
    start = time.time()
    
    # Percentage-based coordinates
    center_x_pct, center_y_pct = 50, 50  # Center of screen
    top_left_x_pct, top_left_y_pct = 6.48, 6.9  # Top-left area
    
    while(not is_home) and ((time.time()) - start) < timeout:
        found = False
        time.sleep(1)
        text = req_text("Home.World")

        try:
            text = text[0][0].lower()
        except Exception as e:
            logger.info("Finding The Homepage...")

        if text == "world":
            is_home = True
        elif text == "city":
            tap_on_text("World.City", sleep=2)
            is_home = True
            
        if is_home:
            logger.info("On homepage")
            time.sleep(1)
            break
        found = tap_on_templates_batch(
            [
                "Global.Back",
                "Global.Close", 
                "FirstPurchase.Close",
                "Home.Store.Back"
                
            ],
            wait=1,
            parallel = True
        )
        # found = tap_on_template("Global.Back", sleep=1)
        # if not found:
        #     found = tap_on_template("Global.Close", sleep=1)
        # if not found:
        #     found = tap_on_template("FirstPurchase.Close", sleep=1)

        targets = [
            "tap anywhere to continue",
            "tap to exit",
            "click to continue",
            "click anywhere to exit",
            "Reconnect"
        ]
        res = req_ocr()
        for item in res:
            box = item["box"]
            if item["text"].lower() == "world":
                found = True
                is_home = True
            if item["text"] in targets:
                box = item["box"]
                logger.debug("OCR box: %s", box)
                # OCR returns coordinates in pixels
                coord = ((box[0]+box[2])//2, (box[1]+box[3])//2)
                tap_screen(coord, coord=True)
                found = True

        if not found:
            time.sleep(1)
            text = req_text("Home.World")
            try:
                text = text[0][0]
            except Exception as e:
                logger.error("Error... %s", e)
            if text:
                found = True
                if text.lower() != "city" and text.lower() != "world":
                    tap_screen(center_x_pct, center_y_pct)
            else:
                found = False

        if found:
            start = time.time()
        else:
            tap_screen(top_left_x_pct, top_left_y_pct)
            time.sleep(1)

    
    time.sleep(1)
    if not is_home:
        raise RuntimeError("Homepage Not found, Runtime Error. Stopping the Bot...")

