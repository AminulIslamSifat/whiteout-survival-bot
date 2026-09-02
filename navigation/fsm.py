"""
Game state machine for screen navigation.

Covers ALL screens referenced by the 17 usecase modules:
- main_city, world, alliance (+ sub-screens), chief_profile, settings
- missions (daily/growth), arena, exploration, pet, labyrinth
- intel, vip, mail, troop_training, heal, gather

Instance-scoped — no singleton. Each bot runner gets its own FSM.
"""

from __future__ import annotations

import time
from typing import Any, Optional

from core.logging_config import get_logger

logger = get_logger(__name__)

# Type alias for transition definition
Transition = dict[str, str | list[float]]


class GameFSM:
    """
    Finite state machine for navigating between game screens.

    Uses BFS pathfinding on a directed graph of screen transitions.
    State detection via OCR text/template matching.
    """

    def __init__(self, interaction: Any) -> None:
        """
        Args:
            interaction: vision.interaction.Interaction instance
        """
        self.ix = interaction
        self.current_state: Optional[str] = None

        # ── Graph: state -> neighbor -> transition ───────────────────
        self.graph: dict[str, dict[str, Transition]] = {
            "main_city": {
                "world": {"action": "text", "target": "Home.World"},
                "alliance": {"action": "text", "target": "Home.Alliance"},
                "exploration": {"action": "text", "target": "Home.Exploration"},
                "heroes": {"action": "text", "target": "Home.Heroes"},
                "backpack": {"action": "text", "target": "Home.Backpack"},
                "shop": {"action": "text", "target": "Home.Store"},
                "vip": {"action": "text", "target": "Home.VIPLevel"},
                "mail": {"action": "template", "target": "Home.Mail"},
                "missions": {"action": "template", "target": "Home.Missions"},
                "labyrinth": {"action": "template", "target": "Home.Labyrinth"},
                "pet": {"action": "template", "target": "Home.Pet"},
                "chief_order": {"action": "template", "target": "Home.ChiefOrder"},
                "troop_training": {"action": "template", "target": "Global.SidePanel"},
                "chief_profile": {"action": "coord", "target": [4.63, 6.1]},
            },
            "world": {
                "main_city": {"action": "text", "target": "World.City"},
                "intel": {"action": "template", "target": "World.Intel"},
                "search": {"action": "template", "target": "World.Search"},
                "heal": {"action": "template", "target": "World.Heal"},
                "gather": {"action": "template", "target": "World.Search"},
            },
            "alliance": {
                "main_city": {"action": "template", "target": "Global.Back"},
                "alliance_tech": {"action": "text", "target": "Home.Alliance.Tech"},
                "alliance_war": {"action": "text", "target": "Home.Alliance.War"},
                "alliance_chests": {"action": "text", "target": "Home.Alliance.Chests"},
                "alliance_help": {"action": "text", "target": "Home.Alliance.Help"},
                "alliance_triumph": {"action": "text", "target": "Home.Alliance.Triumph"},
            },
            "alliance_tech": {
                "alliance": {"action": "template", "target": "Global.Back"},
            },
            "alliance_war": {
                "alliance": {"action": "template", "target": "Global.Back"},
            },
            "alliance_chests": {
                "alliance": {"action": "template", "target": "Global.Back"},
            },
            "alliance_help": {
                "alliance": {"action": "template", "target": "Global.Back"},
            },
            "alliance_triumph": {
                "alliance": {"action": "template", "target": "Global.Back"},
            },
            "exploration": {
                "main_city": {"action": "template", "target": "Global.Back"},
            },
            "vip": {
                "main_city": {"action": "template", "target": "Global.Back"},
            },
            "mail": {
                "main_city": {"action": "template", "target": "Global.Back"},
            },
            "missions": {
                "main_city": {"action": "template", "target": "Global.Back"},
            },
            "arena": {
                "missions": {"action": "template", "target": "Global.Back"},
                "main_city": {"action": "template", "target": "Global.Back"},
            },
            "labyrinth": {
                "main_city": {"action": "template", "target": "Global.Back"},
            },
            "pet": {
                "main_city": {"action": "template", "target": "Global.Back"},
            },
            "chief_order": {
                "main_city": {"action": "template", "target": "Global.Back"},
            },
            "intel": {
                "world": {"action": "template", "target": "Global.Back"},
            },
            "heal": {
                "world": {"action": "text", "target": "World.City"},
            },
            "search": {
                "world": {"action": "template", "target": "Global.Back"},
            },
            "gather": {
                "world": {"action": "template", "target": "Global.Back"},
            },
            "troop_training": {
                "main_city": {"action": "template", "target": "Global.Back"},
            },
            "chief_profile": {
                "main_city": {"action": "template", "target": "Global.Back"},
                "settings": {"action": "text", "target": "ChiefProfile.Settings"},
            },
            "settings": {
                "chief_profile": {"action": "template", "target": "Global.Back"},
                "account": {"action": "text", "target": "ChiefProfile.Settings.Account"},
                "characters": {"action": "text", "target": "ChiefProfile.Settings.Characters"},
            },
        }

        # ── Detection map: OCR key -> state name ─────────────────────
        self.detection_map: dict[str, str] = {
            "Home.Alliance.Title": "alliance",
            "Home.Alliance.Tech.Title": "alliance_tech",
            "Home.Alliance.War.Title": "alliance_war",
            "Home.Alliance.Chests.Title": "alliance_chests",
            "Home.Alliance.Help.Title": "alliance_help",
            "Home.Alliance.Triumph.Title": "alliance_triumph",
            "World.City": "world",
            "Home.World": "main_city",
            "ChiefProfile.Title": "chief_profile",
            "ChiefProfile.Settings.Title": "settings",
            "Home.Exploration.Title": "exploration",
            "Home.VIP.Title": "vip",
            "Home.Mail.Title": "mail",
            "Home.Missions.Title": "missions",
            "Home.Arena.Title": "arena",
            "Home.Labyrinth.Title": "labyrinth",
            "Home.Pet.Title": "pet",
            "Home.ChiefOrder.Title": "chief_order",
            "Home.TroopTraining.Title": "troop_training",
            "World.Intel.Title": "intel",
            "World.Heal.Title": "heal",
            "World.Search.Title": "search",
        }

    # ── State detection ──────────────────────────────────────────────

    def detect_state(self) -> Optional[str]:
        """Identify current screen by checking known titles/buttons."""
        logger.info("Detecting current state...")

        # Check World vs City first (most common)
        res = self.ix.req_text("World.City")
        if res and "City" in res[0][0]:
            self.current_state = "world"
            return "world"

        res = self.ix.req_text("Home.World")
        if res and "World" in res[0][0]:
            self.current_state = "main_city"
            return "main_city"

        # Check other titles
        for key, state in self.detection_map.items():
            if key in ("World.City", "Home.World"):
                continue
            res = self.ix.req_text(key)
            if res:
                self.current_state = state
                return state

        logger.warning("Could not detect state automatically.")
        return None

    # ── Pathfinding ──────────────────────────────────────────────────

    def find_path(self, start: str, end: str) -> Optional[list[str]]:
        """BFS shortest path between two states."""
        if start == end:
            return [start]

        queue: list[list[str]] = [[start]]
        visited: set[str] = set()

        while queue:
            path = queue.pop(0)
            node = path[-1]
            if node == end:
                return path
            if node not in visited:
                for neighbor in self.graph.get(node, {}):
                    new_path = list(path)
                    new_path.append(neighbor)
                    queue.append(new_path)
                visited.add(node)

        return None

    # ── Navigation ───────────────────────────────────────────────────

    def navigate_to(self, target_state: str) -> bool:
        """
        Navigate from current state to target state.
        Auto-detects current state if unknown.
        Falls back to recalibrate on failure.
        """
        if not self.current_state:
            self.detect_state()

        if not self.current_state:
            from navigation.recalibrate import recalibrate
            recalibrate(self.ix)
            self.current_state = "main_city"

        if self.current_state == target_state:
            logger.info("Already at %s", target_state)
            return True

        path = self.find_path(self.current_state, target_state)
        if not path:
            logger.warning(
                "Path not found from %s to %s. Resetting to main_city...",
                self.current_state, target_state,
            )
            from navigation.recalibrate import recalibrate
            recalibrate(self.ix)
            self.current_state = "main_city"
            path = self.find_path("main_city", target_state)
            if not path:
                return False

        logger.info("Navigating: %s", " -> ".join(path))

        for i in range(len(path) - 1):
            from_node = path[i]
            to_node = path[i + 1]
            transition = self.graph[from_node][to_node]

            success = False
            action = transition["action"]
            target = transition["target"]

            if action == "text":
                success = bool(self.ix.tap_on_text(str(target), wait=3))
            elif action == "template":
                success = bool(self.ix.tap_on_template(str(target), wait=3))
            elif action == "coord":
                assert isinstance(target, list)
                self.ix.device.tap(target[0], target[1])
                success = True

            if not success:
                logger.warning("Failed to move from %s to %s. Retrying...", from_node, to_node)
                self.detect_state()
                return self.navigate_to(target_state)

            self.current_state = to_node
            time.sleep(1)

        return True

    def go_home(self) -> bool:
        """Navigate back to main city screen."""
        return self.navigate_to("main_city")
