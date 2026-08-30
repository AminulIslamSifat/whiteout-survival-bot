"""Merge-gate fixture crop suite (E-3A): frozen-text oracle, not engine agreement.

Each manifest entry freezes the text a human verified on the fixture frame.
The suite runs the FULL production read path (_recognize_crop_unlocked with
the per-crop fallback rule) so the badge-digit fallback is exercised, and
scores with the same fuzzy>=80 rule the bot uses (core/core.py rapidfuzz).

Extend coverage by dropping extra frames + a manifest into
tests/fixtures/local/ (gitignored — for screens carrying the player's own ID).
"""
import json
import sys
from pathlib import Path

import pytest

darwin_only = pytest.mark.skipif(sys.platform != "darwin", reason="vision engine is macOS-only")

FIXTURES = Path(__file__).parent / "fixtures"
PADDLE_MODELS = (Path.home() / ".paddleocr" / "whl").is_dir()


def _load_manifests():
    manifests = [FIXTURES / "crop_manifest.json"]
    local = FIXTURES / "local" / "crop_manifest.json"
    if local.exists():
        manifests.append(local)
    return manifests


def _cases():
    cases = []
    for manifest_path in _load_manifests():
        manifest = json.loads(manifest_path.read_text())
        for frame, spec in manifest["frames"].items():
            for name, entry in spec["entries"].items():
                cases.append(pytest.param(
                    frame, spec["roi_source"], name, entry,
                    id=f"{Path(frame).stem}:{name.split('.')[-1]}",
                ))
    return cases


def _read_crop(frame, roi_source, name):
    import cv2
    import numpy as np
    import core.ocr as ocr_mod

    img = cv2.imread(frame)
    assert img is not None, f"fixture frame missing: {frame}"
    h, w = img.shape[:2]
    box = json.loads(Path(roi_source).read_text())[name]["box"]
    x1, y1 = int(box[0] / 100 * w), int(box[1] / 100 * h)
    x2, y2 = int(box[2] / 100 * w), int(box[3] / 100 * h)
    crop = img[y1:y2, x1:x2]
    pad = 50
    avg = crop.mean(axis=(0, 1))
    padded = np.full((crop.shape[0] + 2 * pad, crop.shape[1] + 2 * pad, 3),
                     avg, dtype=crop.dtype)
    padded[pad:pad + crop.shape[0], pad:pad + crop.shape[1]] = crop
    return padded


@darwin_only
@pytest.mark.parametrize("frame,roi_source,name,entry", _cases())
def test_crop_reads_frozen_text(frame, roi_source, name, entry):
    import re
    from rapidfuzz import fuzz
    import core.ocr as ocr_mod

    if entry.get("needs_fallback") and not PADDLE_MODELS:
        pytest.skip("entry needs the paddle fallback; models not prefetched")

    padded = _read_crop(frame, roi_source, name)
    read_kind = "value" if "digits" in entry else None
    items, engine, fallback_hit = ocr_mod._recognize_crop_unlocked(
        padded, expected_text=entry["expect"], read_kind=read_kind
    )

    assert items, f"{name}: no text read at all (engine={engine})"
    expect = entry["expect"]
    best = max(fuzz.ratio(expect.lower(), i["text"].lower()) for i in items)
    assert best >= 80, (
        f"{name}: expected {expect!r}, best read "
        f"{[i['text'] for i in items]!r} (fuzzy {best:.0f}, engine={engine})"
    )

    if "digits" in entry:
        got_digits = re.sub(r"\D", "", "".join(i["text"] for i in items))
        assert got_digits == entry["digits"], (
            f"{name}: digit mismatch — expected {entry['digits']}, got {got_digits} "
            f"(engine={engine}, fallback={fallback_hit})"
        )
