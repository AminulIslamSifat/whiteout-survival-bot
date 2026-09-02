TASK_METADATA = [
    {"key": "mail", "title": "Mail Rewards", "description": "Collect mailbox rewards.", "func": "collect_mail_rewards"},
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

