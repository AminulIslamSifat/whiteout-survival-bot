"""
Per-device bot runner.

Replaces Main/main.py run_bot() loop.
Each instance manages one device, iterating through accounts/characters
and executing scheduled tasks with error recovery.
"""

from __future__ import annotations

import time
from typing import Optional

from config import BotConfig
from core.logging_config import get_logger
from device.adb import DeviceContext
from vision.ocr_client import OCRClient
from vision.calibration import load_calibration
from vision.interaction import Interaction
from navigation.fsm import GameFSM
from navigation.recalibrate import recalibrate
from scheduler.scheduler import TaskScheduler
from scheduler.completion import CompletionLog
from scheduler.task_registry import discover_tasks, TaskEntry
from accounts.manager import AccountManager, PlayerInfo
from accounts.switcher import AccountSwitcher
from bot.player import initialize_player, PlayerSession
from usecases._compat import set_active_interaction

logger = get_logger(__name__)


class BotRunner:
    """
    Manages the automation loop for a single device.

    Usage:
        runner = BotRunner(device_id, config, task_keys)
        runner.run()  # Blocks until interrupted
    """

    def __init__(
        self,
        device_id: str,
        config: BotConfig,
        task_keys: list[str],
        *,
        account_filter: Optional[list[str]] = None,
        character_filter: Optional[dict[str, list[str]]] = None,
    ) -> None:
        self.config = config
        self.task_keys = task_keys
        self.account_filter = account_filter
        self.character_filter = character_filter

        # Initialize device-scoped components
        self.device = DeviceContext(device_id)
        self.ocr = OCRClient(config)
        self.calibration = load_calibration(config, device_id=device_id)
        self.ix = Interaction(self.device, self.ocr, self.calibration, config)
        self.fsm = GameFSM(self.ix)
        self.switcher = AccountSwitcher(self.ix)
        self.accounts = AccountManager(config.db_dir / "account.json")
        self.completion = CompletionLog(config.db_dir / "completion_log.txt")
        self.scheduler = TaskScheduler(
            self.completion,
            default_skip_window=config.scheduler.skip_window_seconds,
            max_retries=config.scheduler.max_retries_per_task,
        )

        # Discover and register tasks
        all_tasks = discover_tasks(config.project_root / "usecases")
        selected = [t for t in all_tasks if t.key in task_keys]
        if not selected:
            raise ValueError(f"No matching tasks found for keys: {task_keys}")
        self.scheduler.add_tasks(selected)

        # Set thread-local Interaction so usecases can access it via _compat
        set_active_interaction(self.ix)

        logger.info(
            "🤖 BotRunner initialized for %s with %d tasks",
            device_id, len(selected),
        )

    def run(self) -> None:
        """Main loop: iterate through accounts/characters, run tasks."""
        players = self.accounts.get_all_players(
            account_filter=self.account_filter,
            character_filter=self.character_filter,
        )
        if not players:
            logger.error("No players to process")
            return

        logger.info("Starting bot loop with %d characters", len(players))

        while True:
            for player in players:
                try:
                    self._process_player(player)
                except RuntimeError as e:
                    if "Homepage not found" in str(e):
                        logger.error("Fatal: %s — skipping player %s", e, player.name)
                        continue
                    raise
                except Exception as e:
                    logger.error("Error processing %s (%s): %s", player.name, player.id, e)
                    # Try to recover before next player
                    try:
                        recalibrate(self.ix)
                    except Exception:
                        logger.error("Recovery failed, continuing to next player")

            logger.info("✅ Completed full cycle. Restarting...")
            time.sleep(5)

    def _process_player(self, player: PlayerInfo) -> None:
        """Switch to player and run their scheduled tasks."""
        logger.info("━━━ Processing: %s (%s) ━━━", player.name, player.id)

        # Switch account if needed
        current_session = initialize_player(self.ix)
        if current_session is None:
            logger.warning("Could not initialize player, attempting account switch")
            if not self.switcher.change_account(player.email):
                logger.error("Account switch failed for %s", player.email)
                return
            current_session = initialize_player(self.ix)
            if current_session is None:
                logger.error("Player init failed after account switch")
                return

        # Check if we need to switch character
        if current_session.id.lower() != player.id.lower():
            # Try character switch first (same account)
            if current_session.email == player.email:
                logger.info("Switching character to %s", player.name)
                if not self.switcher.change_character(player.name):
                    logger.error("Character switch failed")
                    return
            else:
                logger.info("Switching account to %s", player.email)
                if not self.switcher.change_account(player.email):
                    logger.error("Account switch failed")
                    return

            current_session = initialize_player(self.ix)
            if current_session is None:
                logger.error("Player init failed after switch")
                return

        current_session.email = player.email

        # Get runnable tasks for this player
        runnable = self.scheduler.get_runnable_tasks(player.id)
        if not runnable:
            logger.info("All tasks skipped for %s (recently completed)", player.name)
            return

        logger.info("Running %d tasks for %s", len(runnable), player.name)

        for scheduled in runnable:
            task = scheduled.entry
            logger.info("▶ Running task: %s", task.title)

            success = False
            for attempt in range(self.scheduler._max_retries + 1):
                try:
                    import inspect
                    sig = inspect.signature(task.func)
                    if len(sig.parameters) > 0:
                        task.func(current_session.id)
                    else:
                        task.func()
                    success = True
                    break
                except Exception as e:
                    logger.error(
                        "Task %s failed (attempt %d/%d): %s",
                        task.key, attempt + 1, self.scheduler._max_retries + 1, e,
                    )
                    if attempt < self.scheduler._max_retries:
                        try:
                            recalibrate(self.ix)
                        except Exception:
                            logger.error("Recovery failed during task retry")
                            break

            if success:
                self.scheduler.mark_task_completed(player.id, task.key)
                logger.info("✅ Task completed: %s", task.title)
            else:
                logger.error("❌ Task failed after retries: %s", task.title)
