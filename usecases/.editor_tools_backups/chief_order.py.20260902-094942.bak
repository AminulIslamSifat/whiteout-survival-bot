#coming soon
import time

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



def activate_chief_order():
    recalibrate()
    tap_on_template("Home.ChiefOrder", wait=2)

    time.sleep(1)
    currency = req_text("Home.ChiefOrder.Currency")
    try:
        currency = currency[0][0].replace(",", "").replace(".", "")
        if currency.lower().endswith("m") and currency[:-1].isdigit():
            currency = int(currency[:-1])*1000000
    except Exception as e:
        print(f"Currency Reading Error - {e}")
        currency = 0

    order_list = {"UrgentMobilization": 50000, "ProductiveDay": 50000, "RushJob":150000}
    for key, value in order_list.items():
        if currency > value:
            status = tap_on_text(f"Home.ChiefOrder.{key}", wait=2)
            status1 =  None
            if status:
                status1 = tap_on_text("Home.ChiefOrder.Enact", wait=2)
                currency -= value
            if status1:
                tap_on_template("Home.ChiefOrder", wait=6)
            elif status and not status1:
                tap_on_template("Global.Back", wait=2)
    print("Finished publishing chief order, ending the task...")
    return True


