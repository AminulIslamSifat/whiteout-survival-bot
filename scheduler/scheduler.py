"""
Task scheduler with TTL, priority, and cooldown support.

Replaces the flat sequential loop from Main/main.py.
Tasks are ordered by priority, filtered by TTL/cooldown, and executed sequentially.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Optional

from core.logging_config import get_logger
from scheduler.completion import CompletionLog
from scheduler.task_registry import TaskEntry

logger = get_logger(__name__)


@dataclass
class ScheduledTask:
    """A task with scheduling metadata."""

    entry: TaskEntry
    priority: int = 0  # Lower = higher priority
    ttl_seconds: float = 3600.0  # Skip if completed within this window
    enabled: bool = True


class TaskScheduler:
    """
    Manages task execution order with priority and TTL.

    Usage:
        scheduler = TaskScheduler(completion_log, skip_window=10800)
        scheduler.add_tasks(discovered_tasks)
        for task in scheduler.get_runnable_tasks(player_id):
            task.entry.func(player_id)
            completion_log.mark_completed(player_id)
    """

    def __init__(
        self,
        completion_log: CompletionLog,
        *,
        default_skip_window: float = 10800.0,
        max_retries: int = 2,
    ) -> None:
        self._completion = completion_log
        self._default_skip_window = default_skip_window
        self._max_retries = max_retries
        self._tasks: list[ScheduledTask] = []

    def add_tasks(self, entries: list[TaskEntry], *, priority: int = 0) -> None:
        """Add discovered tasks with default priority."""
        for entry in entries:
            self._tasks.append(ScheduledTask(
                entry=entry,
                priority=priority,
                ttl_seconds=self._default_skip_window,
            ))
        # Sort by priority (lower first)
        self._tasks.sort(key=lambda t: t.priority)

    def set_task_priority(self, key: str, priority: int) -> None:
        """Override priority for a specific task."""
        for task in self._tasks:
            if task.entry.key == key:
                task.priority = priority
                break
        self._tasks.sort(key=lambda t: t.priority)

    def set_task_ttl(self, key: str, ttl_seconds: float) -> None:
        """Override TTL for a specific task."""
        for task in self._tasks:
            if task.entry.key == key:
                task.ttl_seconds = ttl_seconds
                break

    def disable_task(self, key: str) -> None:
        """Disable a task without removing it."""
        for task in self._tasks:
            if task.entry.key == key:
                task.enabled = False
                break

    def enable_task(self, key: str) -> None:
        """Re-enable a disabled task."""
        for task in self._tasks:
            if task.entry.key == key:
                task.enabled = True
                break

    def get_runnable_tasks(self, player_id: str) -> list[ScheduledTask]:
        """
        Return tasks that should run for this player.
        Filters by enabled status and TTL.
        Ordered by priority.
        """
        runnable: list[ScheduledTask] = []
        for task in self._tasks:
            if not task.enabled:
                continue
            if self._completion.should_skip(f"{player_id}:{task.entry.key}", task.ttl_seconds):
                last = self._completion.get_last_completed(f"{player_id}:{task.entry.key}")
                if last:
                    logger.info(
                        "Skipping %s for %s (completed %.0fs ago, TTL=%.0fs)",
                        task.entry.key, player_id,
                        time.time() - last, task.ttl_seconds,
                    )
                continue
            runnable.append(task)
        return runnable

    def mark_task_completed(self, player_id: str, task_key: str) -> None:
        """Mark a specific task as completed for a player."""
        self._completion.mark_completed(f"{player_id}:{task_key}")

    @property
    def all_tasks(self) -> list[ScheduledTask]:
        return list(self._tasks)

    @property
    def task_keys(self) -> list[str]:
        return [t.entry.key for t in self._tasks]
