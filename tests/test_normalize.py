"""Tests for core/ocr.py::_normalize_frame_resolution — the guard that makes
the historical 2456-vs-2460 coordinate drift impossible to reintroduce
silently (see the comment block above the function in core/ocr.py).

Importing core.ocr triggers module-scope PaddleOCR/paddle setup. That is
slow-ish (~3s) but non-interactive as long as OCR_CAPTURE_TOOL is set before
import, which tests/conftest.py guarantees.
"""
import numpy as np

from core.coord_utils import BASE_WIDTH, BASE_HEIGHT
from core.ocr import _normalize_frame_resolution


def test_frame_already_at_base_resolution_is_returned_unchanged():
    frame = np.zeros((BASE_HEIGHT, BASE_WIDTH, 3), dtype=np.uint8)
    result = _normalize_frame_resolution(frame)
    # Must be the identical object -- no resize, no copy -- when dims already match.
    assert result is frame


def test_off_height_frame_is_resized_to_base_resolution():
    frame = np.zeros((2400, BASE_WIDTH, 3), dtype=np.uint8)
    result = _normalize_frame_resolution(frame)
    assert result.shape[:2] == (BASE_HEIGHT, BASE_WIDTH)


def test_off_width_frame_is_resized_to_base_resolution():
    frame = np.zeros((BASE_HEIGHT, 1000, 3), dtype=np.uint8)
    result = _normalize_frame_resolution(frame)
    assert result.shape[:2] == (BASE_HEIGHT, BASE_WIDTH)


def test_none_frame_returns_none():
    assert _normalize_frame_resolution(None) is None
