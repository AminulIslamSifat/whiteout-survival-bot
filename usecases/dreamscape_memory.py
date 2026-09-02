import os
import sys

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
import time
from rapidfuzz import fuzz

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



ch4 = {
    'saw': (327, 1462),
    'trophy': (730, 870),
    'meteor': (206, 495),
    'stool': (563, 1278),
    'tire tracks': (706, 1511),
    'bucket': (662, 1218),
    'clock': (596, 800),
    'spider web': (972, 569),
    'rope': (794, 372),
    'mouse': (566, 478),
    'lion wall art': (880, 817),
    'screwdriver': (593, 1590),
    'toolbox': (287, 311),
    'sledgehapper': (506, 1331)
}


SCAN_ROIS = [[50, 2090, 1035, 2190]]
FUZZY_THRESHOLD = 0.8


def box_center(box):
    x1, y1, x2, y2 = box
    return ((x1 + x2) // 2, (y1 + y2) // 2)


def find_best_match(ocr_items, candidates):
    best_match = None

    for text, box in ocr_items:
        normalized_text = text.strip().lower()

        for candidate in candidates:
            score = fuzz.ratio(normalized_text, candidate.lower()) / 100
            if score < FUZZY_THRESHOLD:
                continue

            if best_match is None or score > best_match["score"]:
                best_match = {
                    "ocr_text": text,
                    "candidate": candidate,
                    "score": score,
                    "box": box,
                }

    return best_match


while True:
    data = req_text(rois=SCAN_ROIS, save_result=True) or []
    match = find_best_match(data, ch4.keys())

    if match is None:
        continue

    logger.info("Matched %r -> %r (%.2f)", match['ocr_text'], match['candidate'], match['score'])
    tap_screen(box_center(match["box"]), coord=True)