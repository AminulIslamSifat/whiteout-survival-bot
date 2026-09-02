import os
import re
import cv2
import time
import subprocess
import numpy as np

from core.coord_utils import percent_to_pixel
from cmd_program.resolution_utils import get_stream_resolution
from core.logging_config import get_logger

logger = get_logger(__name__)


def get_adb_devices():
    result = subprocess.run(
        ["adb", "devices"],
        capture_output=True,
        text=True
    )
    lines = result.stdout.strip().split("\n")[1:]
    devices = []
    for line in lines:
        if line.strip():
            parts = line.split()
            if len(parts) >=2 and parts[1] == "device":
                devices.append(parts[0])
    return devices




devices = get_adb_devices()
if not devices:
    logger.error("❌ No ADB devices found. Please connect your phone.")
    device_id = None
elif "13139385O0003802" in devices:
    device_id = "13139385O0003802"
else:
    device_id = devices[0]


_screen_size = None


def _resolve_device_id(selected_device_id=None):
    resolved = selected_device_id or device_id
    if not resolved:
        raise RuntimeError("No ADB device selected")
    return resolved


def _get_screen_size(selected_device_id=None):
    global _screen_size

    if _screen_size is not None:
        return _screen_size

    resolved_device_id = _resolve_device_id(selected_device_id)
    result = subprocess.run(
        ["adb", "-s", str(resolved_device_id), "shell", "wm", "size"],
        capture_output=True,
        text=True,
        check=True,
    )
    match = re.search(r"Physical size:\s*(\d+)x(\d+)", result.stdout)
    if not match:
        raise RuntimeError(f"Unable to read screen size: {result.stdout.strip()}")

    _screen_size = (int(match.group(1)), int(match.group(2)))
    return _screen_size


def _normalize_point_args(args):
    if len(args) == 1:
        if args[0] is None:
            raise RuntimeError("Coordination not found")
        x, y = args[0]
    elif len(args) == 2 and not any(isinstance(arg, (tuple, list)) for arg in args):
        x, y = args
    else:
        raise ValueError("Expected a point tuple or x/y values")

    return float(x), float(y)


def _normalize_swipe_args(args):
    if len(args) == 2 and all(isinstance(arg, (tuple, list)) for arg in args):
        (x1, y1), (x2, y2) = args
    elif len(args) == 4 and not any(isinstance(arg, (tuple, list)) for arg in args):
        x1, y1, x2, y2 = args
    else:
        raise ValueError("Expected two points or four coordinate values")

    return float(x1), float(y1), float(x2), float(y2)



def run_adb_command(cmd, device_id):
    #running the adb command and chekcing if the adb is available or not
    try:
        subprocess.run(["adb", "-s", str(device_id)] + cmd, check = True)
    except Exception as e:
        raise RuntimeError(f"adb command failed - {e}")



def tap_screen(*args, coord=False):
    """
    Tap screen at given coordinates.
    
    Args:
        *args: Either (x, y) or (point_tuple)
        coord: If False, coordinates are percentages and will be converted to pixels.
               If True, coordinates are already in pixels.
    """
    x, y = _normalize_point_args(args)
    
    if not coord:
        # Convert from percentage to pixel coordinates
        screen_width, screen_height = _get_screen_size()
        x, y = percent_to_pixel(x, y, screen_width, screen_height)
    
    # At this point, x and y are always pixels
    adb_command = ["shell", "input", "tap", str(int(x)), str(int(y))]
    run_adb_command(adb_command, _resolve_device_id())



def swipe_screen(*args, duration=300, coord=False):
    """
    Swipe screen from one location to another.
    
    Args:
        *args: Either ((x1, y1), (x2, y2)) or (x1, y1, x2, y2)
        duration: Duration of swipe in milliseconds
        coord: If False, coordinates are percentages and will be converted to pixels.
               If True, coordinates are already in pixels.
    """
    x1, y1, x2, y2 = _normalize_swipe_args(args)
    
    if not coord:
        # Convert from percentage to pixel coordinates
        screen_width, screen_height = _get_screen_size()
        x1, y1 = percent_to_pixel(x1, y1, screen_width, screen_height)
        x2, y2 = percent_to_pixel(x2, y2, screen_width, screen_height)
    
    # At this point, all coordinates are in pixels
    duration = str(duration)
    adb_command = ["shell", "input", "swipe", str(int(x1)), str(int(y1)), str(int(x2)), str(int(y2)), str(duration)]
    run_adb_command(adb_command, _resolve_device_id())



def long_press(*args, duration=300, coord=False):
    """
    Long press at given coordinates (implemented as a zero-distance swipe).
    
    Args:
        *args: Either (x, y) or (point_tuple)
        duration: Duration of press in milliseconds
        coord: If False, coordinates are percentages and will be converted to pixels.
               If True, coordinates are already in pixels.
    """
    x, y = _normalize_point_args(args)
    
    if not coord:
        # Convert from percentage to pixel coordinates
        screen_width, screen_height = _get_screen_size()
        x, y = percent_to_pixel(x, y, screen_width, screen_height)
    
    # At this point, x and y are always pixels
    duration = str(duration)
    adb_command = ["shell", "input", "swipe", str(int(x)), str(int(y)), str(int(x)), str(int(y)), str(duration)]
    run_adb_command(adb_command, _resolve_device_id())





def take_screenshot(save=False):
    adb_command = ["adb", "-s", str(device_id), "exec-out", "screencap", "-p"]
    raw = subprocess.check_output(adb_command)

    img_array = np.frombuffer(raw, np.uint8)
    img = cv2.imdecode(img_array, cv2.IMREAD_COLOR)

    if img is None:
        raise RuntimeError("Failed to decode the image")
    elif save:
        os.makedirs("cache", exist_ok=True)
        cv2.imwrite(f"cache/wos-{int(time.time())}.png", img)
    
    return img




def clear_input(count=6, device_id=None):
    resolved_device_id = _resolve_device_id(device_id)
    run_adb_command(["shell", "input", "keyevent", "123"], resolved_device_id)

    for i in range(count):
        run_adb_command(["shell", "input", "keyevent", "67"], resolved_device_id)



def input_text(text, device_id=None, backspace=6):
    text = text.replace(" ", "%s")

    adb_command = ["shell", "input", "text", text]
    resolved_device_id = _resolve_device_id(device_id)
    clear_input(count=backspace, device_id=resolved_device_id)
    run_adb_command(adb_command, resolved_device_id)
    run_adb_command(["shell", "input", "keyevent", "66"], device_id=resolved_device_id)
    logger.debug("Text Input: %s", text)