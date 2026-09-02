TASK_METADATA = [
    {"key": "chief_order", "title": "Chief Order", "description": "Activate chief order tasks.", "func": "activate_chief_order"},
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
        logger.warning("Currency Reading Error - %s", e)
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
    logger.info("Finished publishing chief order, ending the task...")
    return True


