"""Tests for cmd_program/screen_action.py::_convert_if_percentage.

The int-vs-float ambiguity here (a plain int is always passed through, a
float in [0, 100] is treated as a percentage, a float above 100 is just
cast to int) is deliberate, pre-existing behavior. These tests lock down
that behavior as-is -- they do not attempt to "fix" the ambiguity.
"""
from cmd_program.screen_action import _convert_if_percentage, BASE_HEIGHT, BASE_WIDTH


def test_int_passes_through_unchanged():
    assert _convert_if_percentage(1230, BASE_HEIGHT) == 1230


def test_float_in_percentage_range_is_treated_as_percentage():
    assert _convert_if_percentage(50.0, BASE_HEIGHT) == 1230


def test_float_above_100_is_cast_not_scaled():
    assert _convert_if_percentage(1500.0, BASE_HEIGHT) == 1500


def test_lower_boundary_zero():
    assert _convert_if_percentage(0.0, BASE_HEIGHT) == 0


def test_upper_boundary_100():
    assert _convert_if_percentage(100.0, BASE_HEIGHT) == BASE_HEIGHT


def test_int_zero_passes_through():
    # An int 0 is not a float, so it goes straight through int(), same as
    # any other int -- it is not special-cased as a percentage boundary.
    assert _convert_if_percentage(0, BASE_WIDTH) == 0
