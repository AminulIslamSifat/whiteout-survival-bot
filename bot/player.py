"""
Player session: initializes and validates the current player context.

Replaces player_initialization() + Player class from Main/main.py.
Takes Interaction instance — no globals.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Optional

from rapidfuzz import fuzz

from core.logging_config import get_logger
from navigation.recalibrate import recalibrate

logger = get_logger(__name__)


@dataclass
class PlayerSession:
    """Current player context after initialization."""

    name: str
    id: str
    state: str
    email: str
    furnace_level: int = 0


def initialize_player(ix: Any) -> Optional[PlayerSession]:
    """
    Detect and validate the currently logged-in player.

    Args:
        ix: vision.interaction.Interaction instance

    Returns:
        PlayerSession if successful, None on failure
    """
    recalibrate(ix)
    ix.device.tap(4.63, 6.1)
    time.sleep(2)

    try:
        time.sleep(1)
        res = ix.req_text(["ChiefProfile.Name", "ChiefProfile.ID", "ChiefProfile.State", "ChiefProfile.FurnaceLevel"])
        if not res or len(res) < 3:
            logger.error("Could not read player profile")
            return None

        name_raw = res[0][0]
        id_raw = res[1][0]
        state_raw = res[2][0] if len(res) > 2 else "Unknown"
        furnace_raw = res[3][0] if len(res) > 3 else "0"

        # Parse name (may have prefix like "[Lv.30] Name")
        name = name_raw
        if "]" in name:
            name = name.split("]")[1].strip()

        # Parse ID
        player_id = ""
        for item in res:
            text = item[0]
            if text.replace(":", "").strip().isdigit():
                player_id = text.replace(":", "").strip()
                break
        if not player_id:
            player_id = id_raw.replace(":", "").strip()

        # Parse furnace level
        furnace = 0
        try:
            furnace_text = furnace_raw.replace(":", "").strip()
            if furnace_text.isdigit():
                furnace = int(furnace_text)
        except Exception:
            pass

        # Parse state
        state = state_raw.replace(":", "").strip()

        session = PlayerSession(
            name=name,
            id=player_id,
            state=state,
            email="",  # Set by caller
            furnace_level=furnace,
        )

        logger.info(
            "🎮 Player: %s | ID: %s | State: %s | Furnace: %d",
            session.name, session.id, session.state, session.furnace_level,
        )
        return session

    except Exception as e:
        logger.error("Player initialization failed: %s", e)
        return None
