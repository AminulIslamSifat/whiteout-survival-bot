"""
ADB device abstraction.

Each DeviceContext encapsulates all state for a single Android device:
- device_id
- cached screen size
- ADB command execution
- tap / swipe / long_press / screenshot / text input

No module-level globals. Thread-safe per-instance.
"""

from __future__ import annotations

import re
import subprocess
import time
from typing import Optional

import cv2
import numpy as np

from core.logging_config import get_logger

logger = get_logger(__name__)


def list_adb_devices() -> list[str]:
    """Return list of connected ADB device IDs."""
    try:
        result = subprocess.run(
            ["adb", "devices"],
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired) as e:
        logger.error("ADB not available: %s", e)
        return []

    devices: list[str] = []
    for line in result.stdout.strip().split("\n")[1:]:
        if not line.strip():
            continue
        parts = line.split()
        if len(parts) >= 2 and parts[1] == "device":
            devices.append(parts[0])
    return devices


class DeviceContext:
    """Encapsulates all interaction with a single ADB device."""

    def __init__(self, device_id: str) -> None:
        self.device_id = device_id
        self._screen_size: Optional[tuple[int, int]] = None

    def __repr__(self) -> str:
        return f"DeviceContext({self.device_id!r})"

    # ── Screen geometry ──────────────────────────────────────────────

    @property
    def screen_width(self) -> int:
        return self.screen_size[0]

    @property
    def screen_height(self) -> int:
        return self.screen_size[1]

    @property
    def screen_size(self) -> tuple[int, int]:
        """Return (width, height) in pixels. Cached after first call."""
        if self._screen_size is not None:
            return self._screen_size

        result = self._run_adb(["shell", "wm", "size"])
        match = re.search(r"Physical size:\s*(\d+)x(\d+)", result)
        if not match:
            raise RuntimeError(f"Unable to read screen size from {self.device_id}: {result}")

        self._screen_size = (int(match.group(1)), int(match.group(2)))
        logger.info("📱 %s resolution: %dx%d", self.device_id, *self._screen_size)
        return self._screen_size

    def invalidate_screen_cache(self) -> None:
        """Force re-detection of screen size on next access."""
        self._screen_size = None

    # ── Coordinate conversion ────────────────────────────────────────

    def pct_to_px(self, x_pct: float, y_pct: float) -> tuple[int, int]:
        """Convert percentage coordinates to pixel coordinates."""
        w, h = self.screen_size
        return int((x_pct / 100) * w), int((y_pct / 100) * h)

    def px_to_pct(self, x: int, y: int) -> tuple[float, float]:
        """Convert pixel coordinates to percentage coordinates."""
        w, h = self.screen_size
        return (x / w) * 100, (y / h) * 100

    # ── Input actions ────────────────────────────────────────────────

    def tap(self, x: float, y: float, *, coord: bool = False) -> None:
        """Tap at coordinates. If coord=False, values are percentages."""
        if not coord:
            x, y = self.pct_to_px(x, y)
        self._run_adb(["shell", "input", "tap", str(int(x)), str(int(y))])

    def swipe(
        self,
        x1: float, y1: float,
        x2: float, y2: float,
        *,
        duration: int = 300,
        coord: bool = False,
    ) -> None:
        """Swipe between two points. If coord=False, values are percentages."""
        if not coord:
            x1, y1 = self.pct_to_px(x1, y1)
            x2, y2 = self.pct_to_px(x2, y2)
        self._run_adb([
            "shell", "input", "swipe",
            str(int(x1)), str(int(y1)),
            str(int(x2)), str(int(y2)),
            str(duration),
        ])

    def long_press(self, x: float, y: float, *, duration: int = 300, coord: bool = False) -> None:
        """Long press at coordinates (zero-distance swipe)."""
        if not coord:
            x, y = self.pct_to_px(x, y)
        self._run_adb([
            "shell", "input", "swipe",
            str(int(x)), str(int(y)),
            str(int(x)), str(int(y)),
            str(duration),
        ])

    def input_text(self, text: str, *, backspace_count: int = 6) -> None:
        """Clear existing input and type new text."""
        # Move cursor to end
        self._run_adb(["shell", "input", "keyevent", "123"])
        # Delete existing characters
        for _ in range(backspace_count):
            self._run_adb(["shell", "input", "keyevent", "67"])
        # Type new text (spaces must be %s for ADB)
        escaped = text.replace(" ", "%s")
        self._run_adb(["shell", "input", "text", escaped])
        # Press enter
        self._run_adb(["shell", "input", "keyevent", "66"])
        logger.debug("Text input on %s: %s", self.device_id, text)

    # ── Screenshot ───────────────────────────────────────────────────

    def screenshot(self, *, save_path: Optional[str] = None) -> np.ndarray:
        """Capture screen via ADB screencap. Returns BGR numpy array."""
        raw = subprocess.check_output(
            ["adb", "-s", self.device_id, "exec-out", "screencap", "-p"],
            timeout=10,
        )
        img_array = np.frombuffer(raw, np.uint8)
        img = cv2.imdecode(img_array, cv2.IMREAD_COLOR)
        if img is None:
            raise RuntimeError(f"Failed to decode screenshot from {self.device_id}")

        if save_path:
            cv2.imwrite(save_path, img)

        return img

    # ── Internal ─────────────────────────────────────────────────────

    def _run_adb(self, args: list[str], *, timeout: int = 10) -> str:
        """Run an ADB command targeting this device. Returns stdout."""
        cmd = ["adb", "-s", self.device_id] + args
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout,
                check=True,
            )
            return result.stdout
        except subprocess.CalledProcessError as e:
            raise RuntimeError(f"ADB command failed on {self.device_id}: {' '.join(args)}\n{e.stderr}") from e
        except subprocess.TimeoutExpired as e:
            raise RuntimeError(f"ADB command timed out on {self.device_id}: {' '.join(args)}") from e
