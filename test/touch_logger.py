#!/usr/bin/env python3
"""
touch_logger.py

Monitors touchscreen coordinates on an Android device over ADB and logs
them to a CSV file, in real time.

Requirements:
  - ADB installed and in PATH
  - Phone connected with USB debugging enabled (adb devices should show it)
  - Python 3

Usage:
  1. Find your touchscreen device node:
       adb shell getevent -pl
     Look for the block containing ABS_MT_POSITION_X / ABS_MT_POSITION_Y
     and note its path, e.g. /dev/input/event4

  2. Run this script:
       python3 touch_logger.py /dev/input/event4

  3. Tap on the phone screen. Coordinates get printed and appended to
     touch_log.csv in the current directory. Ctrl+C to stop.

Notes:
  - Raw touch coordinates from getevent are in the touchscreen's native
    resolution, which may differ from your screen's pixel resolution.
    The script also queries `wm size` so you can compute a scale factor
    if needed.
"""

import subprocess
import sys
import csv
import time
import re
import shutil


def parse_coord_line(line):
    """Extract coordinate updates from getevent output."""
    if "ABS_MT_POSITION_X" in line or "ABS_X" in line:
        return "x", int(line.split()[-1], 16)
    if "ABS_MT_POSITION_Y" in line or "ABS_Y" in line:
        return "y", int(line.split()[-1], 16)
    return None, None

def check_adb():
    if shutil.which("adb") is None:
        print("Error: 'adb' not found in PATH. Install Android platform-tools.")
        sys.exit(1)
    result = subprocess.run(["adb", "devices"], capture_output=True, text=True)
    lines = [l for l in result.stdout.splitlines()[1:] if l.strip()]
    if not lines:
        print("Error: no device detected. Check `adb devices` and USB debugging.")
        sys.exit(1)
    print("Connected device(s):")
    for l in lines:
        print(" ", l)

def get_screen_size():
    try:
        result = subprocess.run(["adb", "shell", "wm", "size"], capture_output=True, text=True)
        m = re.search(r"(\d+)x(\d+)", result.stdout)
        if m:
            return int(m.group(1)), int(m.group(2))
    except Exception:
        pass
    return None, None


def get_touch_axis_ranges(device_path):
    """Read the touchscreen's raw axis ranges from `getevent -pl`."""
    result = subprocess.run(
        ["adb", "shell", "getevent", "-pl", device_path],
        capture_output=True,
        text=True,
    )

    x_max = None
    y_max = None

    x_match = re.search(r"ABS_MT_POSITION_X\s*:.*max\s+(\d+)", result.stdout)
    y_match = re.search(r"ABS_MT_POSITION_Y\s*:.*max\s+(\d+)", result.stdout)

    if x_match:
        x_max = int(x_match.group(1))
    if y_match:
        y_max = int(y_match.group(1))

    return x_max, y_max


def raw_to_pixel(raw_x, raw_y, raw_max_x, raw_max_y, screen_w, screen_h):
    """Map raw touch coordinates into screen pixel coordinates."""
    if not raw_max_x or not raw_max_y or not screen_w or not screen_h:
        return None, None

    x_px = round(raw_x * (screen_w - 1) / raw_max_x)
    y_px = round(raw_y * (screen_h - 1) / raw_max_y)
    return int(x_px), int(y_px)

def main():
    if len(sys.argv) < 2:
        print("Usage: python3 touch_logger.py /dev/input/eventX")
        print("Run `adb shell getevent -pl` first to find the right device.")
        sys.exit(1)

    device_path = sys.argv[1]
    check_adb()

    w, h = get_screen_size()
    raw_max_x, raw_max_y = get_touch_axis_ranges(device_path)
    if w and raw_max_x and raw_max_y:
        print(f"Reported screen size: {w}x{h}")
        print(f"Touch axis range: X 0..{raw_max_x}, Y 0..{raw_max_y}")

    out_file = "touch_log.csv"
    print(f"Logging touches from {device_path} to {out_file}")
    print("Tap your screen now. Press Ctrl+C to stop.\n")

    proc = subprocess.Popen(
        ["adb", "shell", "getevent", "-lt", device_path],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )

    cur_x, cur_y = None, None

    with open(out_file, "a", newline="") as f:
        writer = csv.writer(f)
        if f.tell() == 0:
            writer.writerow(["timestamp", "x_px", "y_px", "raw_x", "raw_y"])

        try:
            for line in proc.stdout:
                line = line.strip()
                if not line:
                    continue

                axis, value = parse_coord_line(line)
                if axis == "x":
                    cur_x = value
                elif axis == "y":
                    cur_y = value
                elif "SYN_REPORT" in line and cur_x is not None and cur_y is not None:
                    ts = time.time()
                    x_px, y_px = raw_to_pixel(cur_x, cur_y, raw_max_x, raw_max_y, w, h)
                    if x_px is None or y_px is None:
                        print(f"raw=({cur_x}, {cur_y})")
                        writer.writerow([ts, None, None, cur_x, cur_y])
                    else:
                        print(f"px=({x_px}, {y_px}) raw=({cur_x}, {cur_y})")
                        writer.writerow([ts, x_px, y_px, cur_x, cur_y])
                    f.flush()
                    cur_x, cur_y = None, None
        except KeyboardInterrupt:
            print("\nStopped. Coordinates saved to", out_file)
        finally:
            proc.terminate()

if __name__ == "__main__":
    main()