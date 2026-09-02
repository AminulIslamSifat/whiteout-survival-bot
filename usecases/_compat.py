"""
Compatibility shim for usecase migration.

Provides the same function signatures as the old core/core.py,
cmd_program/screen_action.py, and core/recalibrate.py globals,
but delegates to a thread-local Interaction instance.

Usecases import from here instead of the old modules.
The BotRunner sets the active Interaction before calling any task.
"""

from __future__ import annotations

import threading
from typing import Any, Optional

from core.logging_config import get_logger

logger = get_logger(__name__)

# Thread-local storage for the active Interaction instance
_thread_local = threading.local()


def set_active_interaction(ix: Any) -> None:
    """Set the Interaction instance for the current thread."""
    _thread_local.ix = ix


def get_active_interaction() -> Any:
    """Get the Interaction instance for the current thread."""
    ix = getattr(_thread_local, "ix", None)
    if ix is None:
        raise RuntimeError(
            "No active Interaction set for this thread. "
            "BotRunner must call set_active_interaction() before running tasks."
        )
    return ix


# ── Proxies for core.core functions ──────────────────────────────────

def req_ocr(*args, **kwargs):
    return get_active_interaction().req_ocr(**kwargs)


def req_text(*args, **kwargs):
    # Handle positional arg (names) vs keyword
    if args:
        kwargs["names"] = args[0]
    return get_active_interaction().req_text(**kwargs)


def req_temp_match(*args, **kwargs):
    if args:
        kwargs["name"] = args[0]
    return get_active_interaction().req_temp_match(**kwargs)


def tap_on_text(*args, **kwargs):
    if args:
        kwargs["text"] = args[0]
    return get_active_interaction().tap_on_text(**kwargs)


def tap_on_template(*args, **kwargs):
    if args:
        kwargs["name"] = args[0]
    return get_active_interaction().tap_on_template(**kwargs)


def tap_on_templates_batch(*args, **kwargs):
    if args:
        kwargs["names"] = args[0]
    return get_active_interaction().tap_on_templates_batch(**kwargs)


def tap_on_closest_text(*args, **kwargs):
    if args:
        kwargs["base_text"] = args[0]
    if len(args) > 1:
        kwargs["target_text"] = args[1]
    return get_active_interaction().tap_on_closest_text(**kwargs)


# ── Proxies for cmd_program.screen_action functions ──────────────────

def tap_screen(*args, **kwargs):
    ix = get_active_interaction()
    if len(args) == 2:
        x, y = args
    elif len(args) == 1 and isinstance(args[0], (tuple, list)):
        x, y = args[0]
    else:
        raise ValueError(f"Invalid tap_screen args: {args}")
    ix.device.tap(x, y, coord=kwargs.get("coord", False))


def swipe_screen(*args, **kwargs):
    ix = get_active_interaction()
    if len(args) == 4:
        x1, y1, x2, y2 = args
    elif len(args) == 2 and all(isinstance(a, (tuple, list)) for a in args):
        (x1, y1), (x2, y2) = args
    else:
        raise ValueError(f"Invalid swipe_screen args: {args}")
    ix.device.swipe(x1, y1, x2, y2, duration=kwargs.get("duration", 300), coord=kwargs.get("coord", False))


def long_press(*args, **kwargs):
    ix = get_active_interaction()
    if len(args) == 2:
        x, y = args
    elif len(args) == 1 and isinstance(args[0], (tuple, list)):
        x, y = args[0]
    else:
        raise ValueError(f"Invalid long_press args: {args}")
    ix.device.long_press(x, y, duration=kwargs.get("duration", 300), coord=kwargs.get("coord", False))


def input_text(*args, **kwargs):
    ix = get_active_interaction()
    if args:
        ix.device.input_text(args[0], backspace_count=kwargs.get("backspace", 6))


def take_screenshot(*args, **kwargs):
    ix = get_active_interaction()
    return ix.device.screenshot(save_path=kwargs.get("save_path"))


def _get_screen_size():
    ix = get_active_interaction()
    return ix.device.screen_size


# ── Proxy for recalibrate ────────────────────────────────────────────

def recalibrate(*args, **kwargs):
    from navigation.recalibrate import recalibrate as _recalibrate
    ix = get_active_interaction()
    timeout = kwargs.get("timeout", 30)
    if args and isinstance(args[0], int):
        timeout = args[0]
    _recalibrate(ix, timeout=timeout)


# ── Proxy for coord_utils ────────────────────────────────────────────

def pct_to_px(x_pct, y_pct):
    ix = get_active_interaction()
    return ix.device.pct_to_px(x_pct, y_pct)
