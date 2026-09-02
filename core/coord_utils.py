"""
Coordinate conversion utilities for percentage-based screen coordinates.
Base resolution: Dynamically detected, with fallback to 1080x2456
"""

# Base resolution used for percentage calculations
# These can be updated at runtime via set_base_resolution()
BASE_WIDTH = 1080
BASE_HEIGHT = 2456

_base_resolution_set = False


def set_base_resolution(width: int, height: int) -> None:
    """
    Set the base resolution for percentage calculations.
    This should be called with the actual device resolution.
    
    Args:
        width: Screen width in pixels
        height: Screen height in pixels
    """
    global BASE_WIDTH, BASE_HEIGHT, _base_resolution_set
    BASE_WIDTH = int(width)
    BASE_HEIGHT = int(height)
    _base_resolution_set = True


def get_base_resolution() -> tuple[int, int]:
    """Get the current base resolution used for calculations."""
    return BASE_WIDTH, BASE_HEIGHT


def pixel_to_percent(x: float, y: float) -> tuple[float, float]:
    """Convert pixel coordinates to percentage coordinates."""
    x_percent = (x / BASE_WIDTH) * 100
    y_percent = (y / BASE_HEIGHT) * 100
    return x_percent, y_percent


def percent_to_pixel(x_percent: float, y_percent: float, 
                     screen_width: int = BASE_WIDTH, 
                     screen_height: int = BASE_HEIGHT) -> tuple[int, int]:
    """Convert percentage coordinates to pixel coordinates."""
    x_pixel = int((x_percent / 100) * screen_width)
    y_pixel = int((y_percent / 100) * screen_height)
    return x_pixel, y_pixel


def box_pixel_to_percent(box: list[int]) -> list[float]:
    """Convert box [x1, y1, x2, y2] from pixels to percentages."""
    x1, y1, x2, y2 = box
    x1_p, y1_p = pixel_to_percent(x1, y1)
    x2_p, y2_p = pixel_to_percent(x2, y2)
    return [x1_p, y1_p, x2_p, y2_p]


def box_percent_to_pixel(box: list[float], 
                         screen_width: int = BASE_WIDTH,
                         screen_height: int = BASE_HEIGHT) -> list[int]:
    """Convert box [x1%, y1%, x2%, y2%] from percentages to pixels."""
    x1_p, y1_p, x2_p, y2_p = box
    x1, y1 = percent_to_pixel(x1_p, y1_p, screen_width, screen_height)
    x2, y2 = percent_to_pixel(x2_p, y2_p, screen_width, screen_height)
    return [x1, y1, x2, y2]


def round_percentages(box: list[float], decimals: int = 2) -> list[float]:
    """Round percentage values to specified decimal places."""
    return [round(v, decimals) for v in box]


def pct_to_px(x_percent: float, y_percent: float,
              screen_width: int = BASE_WIDTH,
              screen_height: int = BASE_HEIGHT) -> tuple[int, int]:
    """Convenience function: convert percentage coordinates to pixel coordinates as a tuple."""
    x_pixel = int((x_percent / 100) * screen_width)
    y_pixel = int((y_percent / 100) * screen_height)
    return (x_pixel, y_pixel)
