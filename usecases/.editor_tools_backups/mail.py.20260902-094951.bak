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




def collect_mail_rewards():
    recalibrate()
    tap_on_template("Home.Mail", wait=2)

    tap_on_text("Home.Mail.Wars", wait=2, sleep=0.5)
    tap_on_text("Home.Mail.ReadAndClaim", wait=2)
    tap_on_text("Home.Mail.TapAnywhereToExit", wait=2)
    tap_on_text("Home.Mail.Alliance", wait=2, sleep=0.5)
    tap_on_text("Home.Mail.ReadAndClaim", wait=2)
    tap_on_text("Home.Mail.TapAnywhereToExit", wait=2)
    tap_on_text("Home.Mail.System", wait=2, sleep=0.5)
    tap_on_text("Home.Mail.ReadAndClaim", wait=2)
    tap_on_text("Home.Mail.TapAnywhereToExit", wait=2)
    tap_on_text("Home.Mail.Reports", wait=2, sleep=0.5)
    tap_on_text("Home.Mail.ReadAndClaim", wait=2)
    tap_on_text("Home.Mail.TapAnywhereToExit", wait=2)
    
    return True

