"""
Completion log: tracks when each player last completed their task run.

Replaces the flat-file completion_log.txt logic from Main/main.py.
Thread-safe via file locking.
"""

from __future__ import annotations

import time
from datetime import datetime
from pathlib import Path
from threading import Lock

from core.logging_config import get_logger

logger = get_logger(__name__)


class CompletionLog:
    """Tracks per-player completion timestamps."""

    def __init__(self, path: Path | str) -> None:
        self._path = Path(path)
        self._lock = Lock()
        self._records: dict[str, float] = {}
        self._load()

    def _load(self) -> None:
        if not self._path.exists():
            return
        try:
            with open(self._path) as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    parts = line.split("|")
                    if len(parts) < 2:
                        continue
                    try:
                        self._records[parts[0].strip().lower()] = float(parts[1].strip())
                    except ValueError:
                        continue
        except Exception as e:
            logger.error("Failed to load completion log: %s", e)

    def _save(self) -> None:
        try:
            lines = []
            for player_id, ts in sorted(self._records.items()):
                iso = datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")
                lines.append(f"{player_id}|{ts}|{iso}")
            self._path.parent.mkdir(parents=True, exist_ok=True)
            with open(self._path, "w") as f:
                f.write("\n".join(lines))
                if lines:
                    f.write("\n")
        except Exception as e:
            logger.error("Failed to save completion log: %s", e)

    def should_skip(self, player_id: str, skip_window_seconds: float) -> bool:
        """Check if player was completed recently enough to skip."""
        with self._lock:
            ts = self._records.get(player_id.lower())
            if ts is None:
                return False
            return (time.time() - ts) < skip_window_seconds

    def mark_completed(self, player_id: str) -> None:
        """Record that a player has completed their task run."""
        with self._lock:
            self._records[player_id.lower()] = time.time()
            self._save()

    def get_last_completed(self, player_id: str) -> float | None:
        """Return timestamp of last completion, or None."""
        with self._lock:
            return self._records.get(player_id.lower())

    def get_all_records(self) -> dict[str, float]:
        """Return copy of all records."""
        with self._lock:
            return dict(self._records)
