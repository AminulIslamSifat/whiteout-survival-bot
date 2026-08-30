"""REGRESSION (CRITICAL): the lazy-import restructure must not change Paddle output.

Baseline captured from the PRE-refactor engine (commit d2bdf57 working tree)
with identical settings: tests/fixtures/paddle_parity_baseline.json. The
restructured lazy factory must produce byte-identical items on the same
deterministic inputs. If this fails, paddle mode (the rollback path!) broke.

Slow (~15s: paddle import + engine init). Skipped when Paddle models are
absent (fresh machine before the documented prefetch).
"""
import json
from pathlib import Path

import cv2
import numpy as np
import pytest

import core.ocr as ocr_mod

pytestmark = pytest.mark.skipif(
    not (Path.home() / ".paddleocr" / "whl").is_dir(),
    reason="paddle models not prefetched",
)

BASELINE = Path(__file__).parent / "fixtures" / "paddle_parity_baseline.json"

CP_BOXES = {
    "Title": [12.96, 6.1, 39.54, 8.33],
    "CollectionGalleryRank": [76.57, 61.26, 97.78, 62.52],
    "PlayerName": [40.09, 76.26, 81.48, 78.33],
    "PlayerID": [43.52, 79.88, 62.78, 81.54],
    "FurnaceLevel": [76.85, 82.68, 92.59, 83.78],
    "Stamina": [12.96, 89.11, 20.56, 90.61],  # baseline used the pre-widening box
    "State": [48.15, 89.8, 60.0, 91.1],
    "Skins": [8.61, 96.71, 17.41, 98.29],
    "Troops": [31.67, 96.63, 43.43, 98.62],
    "Leaderboard": [52.59, 96.79, 72.04, 98.25],
}


def _add_padding(img, pad=50):
    h, w, k = img.shape
    avg_color = img.mean(axis=(0, 1))
    new_img = np.full((h + 2 * pad, w + 2 * pad, k), avg_color, dtype=img.dtype)
    new_img[pad:pad + h, pad:pad + w] = img
    return new_img


def _normalize(items):
    return [{"text": i["text"], "score": round(i["score"], 4), "box": i["box"]} for i in items]


@pytest.fixture(scope="module")
def baseline():
    return json.loads(BASELINE.read_text())


def test_full_frame_parity(baseline):
    for frame, expected in baseline["frames"].items():
        img = cv2.imread(frame)
        got = _normalize(ocr_mod._paddle_recognize_unlocked(img))
        assert got == expected, f"paddle full-frame output drifted for {frame}"


def test_crop_parity(baseline):
    img = cv2.imread("test/test.png")
    h, w = img.shape[:2]
    for name, box in CP_BOXES.items():
        x1, y1 = int(box[0] / 100 * w), int(box[1] / 100 * h)
        x2, y2 = int(box[2] / 100 * w), int(box[3] / 100 * h)
        padded = _add_padding(img[y1:y2, x1:x2])
        got = _normalize(ocr_mod._paddle_recognize_unlocked(padded))
        assert got == baseline["crops"][name], f"paddle crop output drifted for {name}"
