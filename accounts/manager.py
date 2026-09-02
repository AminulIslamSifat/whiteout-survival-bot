"""
Account and character loading with filtering.

Replaces init_database() + player_data globals from Main/main.py.
Pure data layer — no device interaction.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from core.logging_config import get_logger

logger = get_logger(__name__)


@dataclass
class PlayerInfo:
    """A single game character."""

    name: str
    id: str
    email: str
    priority: int  # Account-level priority


class AccountManager:
    """
    Loads and filters accounts/characters from db/account.json.

    Usage:
        mgr = AccountManager(db_dir / "account.json")
        players = mgr.get_all_players()
        filtered = mgr.get_players(account_filter=["a@gmail.com"])
    """

    def __init__(self, account_file: Path | str) -> None:
        self._path = Path(account_file)
        self._raw: dict = {}
        self._load()

    def _load(self) -> None:
        if not self._path.exists():
            logger.warning("Account file not found: %s", self._path)
            return
        try:
            with open(self._path) as f:
                self._raw = json.load(f)
            logger.info("Loaded %d accounts from %s", len(self._raw), self._path)
        except Exception as e:
            logger.error("Failed to load accounts: %s", e)

    def get_all_players(
        self,
        *,
        account_filter: Optional[list[str]] = None,
        character_filter: Optional[dict[str, list[str]]] = None,
    ) -> list[PlayerInfo]:
        """
        Return sorted list of players.

        Args:
            account_filter: Only include these emails. None = all.
            character_filter: email -> [player_ids] to include. None = all.
        """
        data = dict(self._raw)

        # Apply account filter
        if account_filter:
            filtered = {k: v for k, v in data.items() if k in account_filter}
            if not filtered:
                logger.warning("No matching accounts for filter: %s", account_filter)
                logger.warning("   Available: %s", ", ".join(data.keys()))
            data = filtered

        # Apply character filter
        if character_filter:
            for email, allowed_ids in character_filter.items():
                if email not in data:
                    continue
                allowed_lower = {pid.lower() for pid in allowed_ids}
                original = data[email].get("player", [])
                data[email]["player"] = [
                    p for p in original
                    if str(p.get("id", "")).lower() in allowed_lower
                ]
                removed = len(original) - len(data[email]["player"])
                if removed > 0:
                    logger.info("🎮 Filtered %d character(s) from %s", removed, email)
            # Remove empty accounts
            empty = [e for e, d in data.items() if not d.get("player")]
            for e in empty:
                logger.warning("Removing %s — no characters left after filter", e)
                del data[e]

        # Build sorted player list
        sorted_accounts = sorted(
            data.items(),
            key=lambda item: item[1].get("priority", float("inf")),
        )

        players: list[PlayerInfo] = []
        for email, info in sorted_accounts:
            priority = info.get("priority", 999)
            for p in info.get("player", []):
                players.append(PlayerInfo(
                    name=p["name"],
                    id=str(p["id"]),
                    email=email,
                    priority=priority,
                ))

        return players

    def get_emails(self) -> list[str]:
        """Return sorted list of all configured emails."""
        sorted_accounts = sorted(
            self._raw.items(),
            key=lambda item: item[1].get("priority", float("inf")),
        )
        return [email for email, _ in sorted_accounts]

    def get_players_for_email(self, email: str) -> list[PlayerInfo]:
        """Return all players for a specific email."""
        info = self._raw.get(email, {})
        priority = info.get("priority", 999)
        return [
            PlayerInfo(name=p["name"], id=str(p["id"]), email=email, priority=priority)
            for p in info.get("player", [])
        ]

    @property
    def total_accounts(self) -> int:
        return len(self._raw)

    @property
    def total_characters(self) -> int:
        return sum(len(v.get("player", [])) for v in self._raw.values())
