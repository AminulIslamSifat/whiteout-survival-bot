"""
Dynamic resolution detection with scrcpy quirk handling.
Handles the fact that scrcpy returns 6 pixels less in the larger value.
"""

import subprocess
import re
from typing import Tuple

_cached_device_resolution = None
_cached_stream_resolution = None


def get_device_resolution(device_id: str) -> Tuple[int, int]:
    """
    Get actual device resolution from ADB via 'wm size'.
    This is the REAL physical resolution of the device.
    
    Returns:
        (width, height) tuple in pixels
    """
    global _cached_device_resolution
    
    if _cached_device_resolution is not None:
        return _cached_device_resolution
    
    result = subprocess.run(
        ["adb", "-s", str(device_id), "shell", "wm", "size"],
        capture_output=True,
        text=True,
        check=True,
    )
    match = re.search(r"Physical size:\s*(\d+)x(\d+)", result.stdout)
    if not match:
        raise RuntimeError(f"Unable to read screen size: {result.stdout.strip()}")
    
    _cached_device_resolution = (int(match.group(1)), int(match.group(2)))
    return _cached_device_resolution


def get_stream_resolution(device_id: str, apply_scrcpy_quirk: bool = True) -> Tuple[int, int]:
    """
    Get the resolution for streaming/OCR pipeline.
    
    Scrcpy quirk: When mirroring to v4l2loopback, scrcpy returns 6 pixels less
    in the larger dimension. This function accounts for that.
    
    Args:
        device_id: ADB device ID
        apply_scrcpy_quirk: If True, reduce larger dimension by 6 pixels (default: True)
                           Set to False if you want raw device resolution
    
    Returns:
        (width, height) tuple in pixels
    """
    global _cached_stream_resolution
    
    if _cached_stream_resolution is not None:
        return _cached_stream_resolution
    
    width, height = get_device_resolution(device_id)
    
    if apply_scrcpy_quirk:
        # Scrcpy reduces 6 pixels from the larger value
        if width > height:
            width = max(1, width - 6)
        else:
            height = max(1, height - 6)
    
    _cached_stream_resolution = (width, height)
    return _cached_stream_resolution


def reset_resolution_cache():
    """
    Reset cached resolutions. Call this if device is switched or reconnected.
    """
    global _cached_device_resolution, _cached_stream_resolution
    _cached_device_resolution = None
    _cached_stream_resolution = None
