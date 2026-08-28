"""Tests for core/coord_utils.py — the single source of truth for the
1080x2460 base resolution used across the vision (OCR) and action (adb tap)
legs of the pipeline.
"""
from core.coord_utils import (
    BASE_WIDTH,
    BASE_HEIGHT,
    pixel_to_percent,
    percent_to_pixel,
    box_pixel_to_percent,
    box_percent_to_pixel,
)


def test_base_resolution_is_1080x2460():
    # Sanity check the constants the rest of this file assumes.
    assert BASE_WIDTH == 1080
    assert BASE_HEIGHT == 2460


def test_pixel_percent_round_trip():
    # percent_to_pixel truncates via int(), so a round trip can land off by
    # at most one pixel per axis when the percentage isn't an exact multiple.
    points = [(0, 0), (1080, 2460), (540, 1230), (270, 615), (100, 200), (999, 2001)]
    for x, y in points:
        x_pct, y_pct = pixel_to_percent(x, y)
        x_back, y_back = percent_to_pixel(x_pct, y_pct)
        assert abs(x - x_back) <= 1, f"x round-trip drifted for ({x}, {y})"
        assert abs(y - y_back) <= 1, f"y round-trip drifted for ({x}, {y})"


def test_pixel_to_percent_zero_boundary():
    assert pixel_to_percent(0, 0) == (0.0, 0.0)


def test_pixel_to_percent_full_extent_boundary():
    # The full width/height must map to exactly 100%.
    assert pixel_to_percent(BASE_WIDTH, BASE_HEIGHT) == (100.0, 100.0)


def test_percent_to_pixel_zero_boundary():
    assert percent_to_pixel(0, 0) == (0, 0)


def test_percent_to_pixel_full_extent_boundary():
    assert percent_to_pixel(100, 100) == (BASE_WIDTH, BASE_HEIGHT)


def test_box_round_trip():
    box = [0, 400, 1080, 2200]
    box_pct = box_pixel_to_percent(box)
    box_back = box_percent_to_pixel(box_pct)
    for original, back in zip(box, box_back):
        assert abs(original - back) <= 1, f"box round-trip drifted: {box} -> {box_pct} -> {box_back}"


def test_box_percent_to_pixel_full_box():
    # A box spanning the full percentage range must map to the full pixel
    # extents — this is the case the coordinate-space bug would break.
    assert box_percent_to_pixel([0, 0, 100, 100]) == [0, 0, BASE_WIDTH, BASE_HEIGHT]
