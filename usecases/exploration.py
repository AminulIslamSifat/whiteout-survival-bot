TASK_METADATA = [
    {"key": "exploration_idle", "title": "Exploration Idle Income", "description": "Claim passive exploration income.", "func": "claim_exploration_idle_income"},
    {"key": "exploration_continue", "title": "Continue Exploring", "description": "Resume exploration progress.", "func": "continue_exploring"},
]

import time

from core.logging_config import get_logger
from core.recalibrate import recalibrate

logger = get_logger(__name__)

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



def claim_exploration_idle_income():
    status = tap_on_text("Home.Exploration")
    if not status:
        recalibrate()
        tap_on_text("Home.Exploration", wait=2)

    tap_on_text("Home.Exploration.Claim", wait=2)
    status = tap_on_text("Home.Exploration.Claim.Claim", wait=2)
    if status:
        tap_on_text("Home.Exploration.Claim.Claim.TapAnywhereToExit", wait=2)

    recalibrate()


    



def continue_exploring(stopping_level=None):
    logger.info("Started Exploration...")

    def ensure_open_exploration():
        status = tap_on_text("Home.Exploration", wait=2)
        if not status:
            recalibrate()
            tap_on_text("Home.Exploration", wait=2)

    
    def setup_exploration():
        tap_on_text("Home.Exploration.Explore", wait=2)
        tap_on_text("Home.Exploration.Explore.QuickDeploy", wait=2)

    # --- start ---
    ensure_open_exploration()
    setup_exploration()


    is_auto = True

    while True:
        if stopping_level:
            try:
                time.sleep(0.5)
                level = int(req_text("Home.Exploration.CurrentLevel")[0][0])
            except Exception as e:
                logger.error("Level Reading Failed - %s, Ending the task...", e)
                return

            logger.info("Current level - %d, Will stop at %d", level, stopping_level)
            if level > stopping_level:
                logger.info("Exploration Completed...")
                break

        tap_on_text("Home.Exploration.Explore.Fight", wait=2)

        s = tap_on_text("Home.Exploration.Explore.Fight.ReturnToCity", wait=80, tap=False)
        if s:
            v = tap_on_text("Home.Exploration.Explore.Fight.Victory.Continue", wait=2)
            if v:
                logger.info("Challenging next stage...")
            else:
                v = tap_on_text("Home.Exploration.Explore.Fight.ReturnToCity", wait=2)
                logger.warning("Failed the stage, Returning to the Homepage")
                break



