"""
Recalibration: recover to main city screen from any unknown state.

Takes Interaction instance — no globals, no module-level execution.
Replaces core/recalibrate.py which called recalibrate() at import time.
"""

from __future__ import annotations

import time
from typing import Any

from core.logging_config import get_logger

logger = get_logger(__name__)


def recalibrate(ix: Any, *, timeout: int = 30) -> None:
    """
    Attempt to return to the main city screen.

    Args:
        ix: vision.interaction.Interaction instance
        timeout: Maximum seconds to attempt recovery

    Raises:
        RuntimeError: If homepage cannot be found within timeout
    """
    is_home = False
    start = time.time()
    iteration = 0

    center_x_pct, center_y_pct = 50, 50
    top_left_x_pct, top_left_y_pct = 6.48, 6.9

    logger.info("recalibrate() started (timeout=%ds)", timeout)

    while not is_home and (time.time() - start) < timeout:
        iteration += 1
        elapsed = time.time() - start
        found = False
        time.sleep(1)
        logger.debug("recalibrate loop iter=%d elapsed=%.1fs", iteration, elapsed)

        # Check if we're already home
        text = ix.req_text("Home.World")
        try:
            detected = text[0][0].lower()
        except Exception:
            detected = ""
            logger.info("Finding homepage... (iter=%d)", iteration)

        if detected == "world":
            is_home = True
        elif detected == "city":
            ix.tap_on_text("World.City", sleep=2)
            is_home = True

        if is_home:
            logger.info("On homepage")
            time.sleep(1)
            break

        # Try closing overlays / going back
        found = bool(ix.tap_on_templates_batch(
            ["Global.Back", "Global.Close", "FirstPurchase.Close", "Home.Store.Back"],
            wait=1,
            parallel=True,
        ))

        # Full-page OCR scan for navigation cues
        targets = [
            "tap anywhere to continue",
            "tap to exit",
            "click to continue",
            "click anywhere to exit",
            "Reconnect",
        ]
        res = ix.req_ocr(name="recalibrate_scan")
        found_texts = [item["text"] for item in res] if res else []
        logger.info("Recalibrate scan found: %s", found_texts[:10])

        if res:
            for item in res:
                box = item["box"]
                if item["text"].lower() == "world":
                    found = True
                    is_home = True
                if item["text"] in targets:
                    coord = ((box[0] + box[2]) // 2, (box[1] + box[3]) // 2)
                    ix.device.tap(coord[0], coord[1], coord=True)
                    found = True

        if not found:
            time.sleep(1)
            text = ix.req_text("Home.World")
            try:
                detected = text[0][0]
            except Exception as e:
                logger.error("Error reading Home.World: %s", e)
                detected = ""

            if detected:
                found = True
                if detected.lower() not in ("city", "world"):
                    ix.device.tap(center_x_pct, center_y_pct)
            else:
                found = False

        if found:
            start = time.time()  # Reset timeout on progress
        else:
            ix.device.tap(top_left_x_pct, top_left_y_pct)
            time.sleep(1)

    time.sleep(1)
    if not is_home:
        raise RuntimeError("Homepage not found within timeout. Stopping bot.")
