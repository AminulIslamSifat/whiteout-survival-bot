"""
Account and character switching via in-game UI.

Takes Interaction instance — no globals.
Replaces core/change_player.py.
"""

from __future__ import annotations

import time
from typing import Any, Optional

from rapidfuzz import fuzz

from core.logging_config import get_logger
from navigation.recalibrate import recalibrate

logger = get_logger(__name__)


class AccountSwitcher:
    """Handles in-game account and character switching."""

    def __init__(self, ix: Any) -> None:
        """
        Args:
            ix: vision.interaction.Interaction instance
        """
        self.ix = ix

    def change_account(self, next_email: str) -> bool:
        """Switch to a different Google account in-game."""
        recalibrate(self.ix)
        self.ix.device.tap(9.26, 6.9)
        self.ix.tap_on_text("ChiefProfile.Settings", wait=2)
        self.ix.tap_on_text("ChiefProfile.Settings.Account", wait=2, sleep=2)
        self.ix.tap_on_text("ChiefProfile.Settings.Account.ChangeAccount", wait=5, sleep=0.5)
        self.ix.tap_on_text("ChiefProfile.Settings.Account.ChangeAccount.SignInWithGoogle", wait=5)

        status = self.ix.tap_on_text(next_email, wait=5)
        if not status:
            self.ix.device.swipe(50.93, 73.17, 50.93, 16.26)
            status = self.ix.tap_on_text(next_email, wait=10, threshold=1.0)
            if not status:
                logger.error("Email not found: %s", next_email)
                return False

        self.ix.tap_on_text(
            "ChiefProfile.Settings.Account.ChangeAccount.SignInWithGoogle.Continue",
            wait=20, sleep=2,
        )
        recalibrate(self.ix, timeout=80)
        return True

    def change_character(self, next_name: str) -> bool:
        """Switch to a different character on the same account."""
        recalibrate(self.ix)
        self.ix.device.tap(9.26, 6.9)
        self.ix.tap_on_text("ChiefProfile.Title", wait=2, tap=False)
        time.sleep(1)

        text = self.ix.req_text("ChiefProfile.Title")
        try:
            detected = text[0][0].lower()
        except Exception:
            detected = ""

        if detected != "chief profile":
            logger.error("Chief Profile not found")
            return False

        self.ix.tap_on_text("ChiefProfile.Settings", wait=1)
        self.ix.tap_on_text("ChiefProfile.Settings.Characters", wait=2)
        time.sleep(1)

        logger.info("Scanning for player list (full_page OCR)...")
        players = self.ix.req_text()
        if not players:
            logger.error("No players found in OCR scan")
            return False

        logger.info("Player list OCR returned %d results", len(players))

        # Extract names and fuzzy-match against target
        target = next_name.lower().strip()
        best_idx = -1
        best_score = 0.0

        for idx, player in enumerate(players):
            try:
                name = player[0].split("]")[1].lower()
            except Exception:
                name = player[0].lower()

            # Normalize: if target appears inside detected name, strip prefix
            proc_name = name
            pos = name.find(target)
            if pos != -1:
                proc_name = name[pos:]

            score = fuzz.ratio(target, proc_name)
            if score > best_score:
                best_score = score
                best_idx = idx

        if best_score < 70 or best_idx < 0:
            logger.error("No matching player found (best score: %.1f)", best_score)
            return False

        box = players[best_idx][1]
        coord = ((box[0] + box[2]) // 2, (box[1] + box[3]) // 2)
        self.ix.device.tap(coord[0], coord[1], coord=True)

        self.ix.tap_on_text("ChiefProfile.Settings.Characters.Login.Confirm", wait=2, sleep=2)
        recalibrate(self.ix, timeout=80)
        return True
