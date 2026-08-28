import os
import cv2
import time
import subprocess
import numpy as np

from core.coord_utils import BASE_WIDTH, BASE_HEIGHT


def _convert_if_percentage(value, max_value):
    """Convert value from percentage to pixel if it's a percentage (0-100)."""
    if isinstance(value, float) and 0 <= value <= 100:
        return int((value / 100) * max_value)
    return int(value)




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




_device_id = None


def resolve_device(force=False):
    """Resolve the adb serial lazily. Re-probes when the cache is empty or forced."""
    global _device_id
    if force:
        _device_id = None
    if _device_id is not None:
        return _device_id
    preferred = os.getenv("WOS_ADB_SERIAL")
    devices = get_adb_devices()
    if preferred and preferred in devices:
        _device_id = preferred
    elif devices:
        _device_id = devices[0]
    else:
        print("❌ No ADB devices found. Please connect your phone, babe. 💋")
        _device_id = None
    return _device_id


def invalidate_device():
    """Drop the cached serial so the next call re-probes."""
    global _device_id
    _device_id = None



def run_adb_command(cmd, device_id=None):
    #running the adb command and chekcing if the adb is available or not
    if device_id is None:
        try:
            device_id = resolve_device()
        except OSError as e:
            # get_adb_devices() (called by resolve_device()) does its own
            # subprocess.run and can raise the same OSError family (adb
            # missing, not executable, etc.) as the command dispatch below.
            raise RuntimeError(f"adb command failed - could not probe for adb devices: {e}")
    if device_id is None:
        raise RuntimeError(
            f"adb command failed - no adb device available "
            f"(WOS_ADB_SERIAL={os.getenv('WOS_ADB_SERIAL')!r})"
        )
    try:
        subprocess.run(
            ["adb", "-s", str(device_id)] + cmd,
            check=True,
            stderr=subprocess.PIPE,
            text=True,
        )
    except subprocess.CalledProcessError as e:
        invalidate_device()
        stderr = e.stderr.strip() if e.stderr else ""
        raise RuntimeError(
            f"adb command failed - device={device_id} cmd={cmd} exit_code={e.returncode}"
            + (f" stderr={stderr}" if stderr else "")
        )
    except FileNotFoundError as e:
        raise RuntimeError(f"adb command failed - adb binary not found: {e}")



def tap_screen(*args):
    # Handling both tuple and normal x,y coordination and converting them to string
    # Used default device_id so that it won't cause problem when multiple device is connected
    if len(args) == 1:
        if args[0] == None:
            raise RuntimeError("Coordination not found")
        x, y = args[0]
    elif len(args)==2:
        x, y = args
    else:
        raise ValueError

    # Convert percentage to pixels if needed
    x = _convert_if_percentage(x, BASE_WIDTH)
    y = _convert_if_percentage(y, BASE_HEIGHT)

    adb_command = ["shell", "input", "tap", str(x), str(y)]
    run_adb_command(adb_command)



def swipe_screen(*args, duration=300):
    if len(args) == 2:
        (x1, y1), (x2, y2) = args
    elif len(args) == 4:
        x1, y1, x2, y2 = args
    else:
        raise ValueError

    # Convert percentage to pixels if needed
    x1 = _convert_if_percentage(x1, BASE_WIDTH)
    y1 = _convert_if_percentage(y1, BASE_HEIGHT)
    x2 = _convert_if_percentage(x2, BASE_WIDTH)
    y2 = _convert_if_percentage(y2, BASE_HEIGHT)

    duration = str(duration)

    adb_command = ["shell", "input", "swipe", str(x1), str(y1), str(x2), str(y2), str(duration)]
    run_adb_command(adb_command)



def long_press(*args, duration=300):
    # in case of long press, its similar to swipe while the starting and ending location is the same
    if len(args) == 1:
        x, y = args[0]
    elif len(args)==2:
        x, y = args
    else:
        raise ValueError

    # Convert percentage to pixels if needed
    x = _convert_if_percentage(x, BASE_WIDTH)
    y = _convert_if_percentage(y, BASE_HEIGHT)

    duration = str(duration)

    adb_command = ["shell", "input", "swipe", str(x), str(y), str(x), str(y), str(duration)]
    run_adb_command(adb_command)





def take_screenshot(save=False):
    try:
        device_id = resolve_device()
    except OSError as e:
        raise RuntimeError(f"take_screenshot failed - could not probe for adb devices: {e}")
    if device_id is None:
        raise RuntimeError(
            f"take_screenshot failed - no adb device available "
            f"(WOS_ADB_SERIAL={os.getenv('WOS_ADB_SERIAL')!r})"
        )

    adb_command = ["adb", "-s", str(device_id), "exec-out", "screencap", "-p"]
    try:
        raw = subprocess.check_output(adb_command, stderr=subprocess.PIPE)
    except subprocess.CalledProcessError as e:
        invalidate_device()
        stderr = e.stderr.decode(errors="replace").strip() if e.stderr else ""
        raise RuntimeError(
            f"take_screenshot failed - device={device_id} exit_code={e.returncode}"
            + (f" stderr={stderr}" if stderr else "")
        )
    except FileNotFoundError as e:
        raise RuntimeError(f"take_screenshot failed - adb binary not found: {e}")

    img_array = np.frombuffer(raw, np.uint8)
    img = cv2.imdecode(img_array, cv2.IMREAD_COLOR)

    if img is None:
        raise RuntimeError(
            f"Failed to decode the image - device={device_id}, bytes_received={len(raw)}"
        )
    elif save:
        os.makedirs("cache", exist_ok=True)
        cv2.imwrite(f"cache/wos-{int(time.time())}.png", img)

    return img




def clear_input(count=6):
    run_adb_command(["shell", "input", "keyevent", "123"])

    for i in range(count):
        run_adb_command(["shell", "input", "keyevent", "67"])



def input_text(text, backspace=6):
    text = text.replace(" ", "%s")

    adb_command = ["shell", "input", "text", text]
    clear_input(count=backspace)
    run_adb_command(adb_command)
    run_adb_command(["shell", "input", "keyevent", "66"])
    print(f"Text Input: {text}")
