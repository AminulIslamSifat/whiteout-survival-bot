"""
Dynamic task discovery from usecases/ directory.

Scans all Python files for TASK_METADATA lists.
No imports of usecase modules at discovery time (AST parsing).
Actual function loading happens lazily when tasks are executed.
"""

from __future__ import annotations

import ast
import importlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Optional

from core.logging_config import get_logger

logger = get_logger(__name__)


@dataclass
class TaskEntry:
    """A discovered task with metadata and lazy-loaded callable."""

    key: str
    title: str
    description: str
    module_name: str
    func_name: str
    _func: Optional[Callable] = None

    @property
    def func(self) -> Callable:
        """Lazily import and return the task function."""
        if self._func is None:
            mod = importlib.import_module(self.module_name)
            self._func = getattr(mod, self.func_name)
        return self._func

    def to_dict(self) -> dict[str, str]:
        return {
            "key": self.key,
            "title": self.title,
            "description": self.description,
        }


def discover_tasks(usecases_dir: Path | str) -> list[TaskEntry]:
    """
    Scan usecases/ for TASK_METADATA via AST parsing.
    No side effects — does not import any usecase modules.
    """
    usecases_dir = Path(usecases_dir)
    tasks: list[TaskEntry] = []
    seen_keys: set[str] = set()

    for pyfile in sorted(usecases_dir.glob("*.py")):
        if pyfile.name.startswith("_"):
            continue

        try:
            tree = ast.parse(pyfile.read_text())
        except SyntaxError as e:
            logger.warning("Syntax error in %s: %s", pyfile.name, e)
            continue

        for node in ast.walk(tree):
            if not isinstance(node, ast.Assign):
                continue
            for target in node.targets:
                if not (isinstance(target, ast.Name) and target.id == "TASK_METADATA"):
                    continue
                try:
                    entries = ast.literal_eval(node.value)
                except (ValueError, TypeError) as e:
                    logger.warning("Cannot parse TASK_METADATA in %s: %s", pyfile.name, e)
                    continue

                module_name = f"usecases.{pyfile.stem}"
                for entry in entries:
                    key = entry.get("key")
                    if not key or key in seen_keys:
                        continue
                    seen_keys.add(key)
                    tasks.append(TaskEntry(
                        key=key,
                        title=entry.get("title", key),
                        description=entry.get("description", ""),
                        module_name=module_name,
                        func_name=entry["func"],
                    ))

    logger.info("Discovered %d tasks from %s", len(tasks), usecases_dir)
    return tasks
