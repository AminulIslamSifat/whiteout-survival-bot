"""Engine resolver matrix, circuit breaker, per-crop fallback rule, RAM-cap gating.

These tests manipulate core.ocr module globals with stub engines — no real
Paddle or Vision inference runs here.
"""
import json
import sys

import numpy as np
import pytest

import core.ocr as ocr_mod
from core.vision_engine import VisionEngineError

darwin_only = pytest.mark.skipif(sys.platform != "darwin", reason="vision default is macOS-only")

FAKE_ITEM = {"text": "fallback!", "score": 0.99, "box": [0, 0, 10, 10]}
VISION_ITEM = {"text": "vision", "score": 0.95, "box": [0, 0, 5, 5]}
IMG = np.zeros((20, 20, 3), dtype=np.uint8)


@pytest.fixture
def clean_engine_state(monkeypatch):
    """Snapshot/restore the engine dispatch globals around each test."""
    saved = (ocr_mod._resolved_engine, ocr_mod._vision_engine, ocr_mod._paddle_engine,
             ocr_mod._vision_exc_streak, ocr_mod._vision_disabled_session)
    yield monkeypatch
    (ocr_mod._resolved_engine, ocr_mod._vision_engine, ocr_mod._paddle_engine,
     ocr_mod._vision_exc_streak, ocr_mod._vision_disabled_session) = saved


class _StubVision:
    def __init__(self, script):
        # script: list of lists (results) or Exception instances, consumed in order
        self.script = list(script)

    def recognize(self, img):
        step = self.script.pop(0) if self.script else []
        if isinstance(step, Exception):
            raise step
        return step


class TestResolverMatrix:
    def test_explicit_paddle_always_wins(self, clean_engine_state):
        clean_engine_state.setenv("OCR_ENGINE", "paddle")
        assert ocr_mod.resolve_engine() == "paddle"

    def test_explicit_vision_on_unsupported_platform_fails_loudly(self, clean_engine_state):
        clean_engine_state.setenv("OCR_ENGINE", "vision")
        clean_engine_state.setattr(ocr_mod, "_vision_supported", lambda: False)
        with pytest.raises(RuntimeError, match="OCR_ENGINE=vision requires"):
            ocr_mod.resolve_engine()

    def test_unset_resolves_by_platform_support(self, clean_engine_state):
        clean_engine_state.delenv("OCR_ENGINE", raising=False)
        clean_engine_state.setattr(ocr_mod, "_vision_supported", lambda: True)
        assert ocr_mod.resolve_engine() == "vision"
        clean_engine_state.setattr(ocr_mod, "_vision_supported", lambda: False)
        assert ocr_mod.resolve_engine() == "paddle"

    def test_garbage_value_rejected(self, clean_engine_state):
        clean_engine_state.setenv("OCR_ENGINE", "tesseract")
        with pytest.raises(RuntimeError, match="must be 'vision' or 'paddle'"):
            ocr_mod.resolve_engine()


class TestBreaker:
    def _arm(self, mp, script, models_present=True):
        mp.setattr(ocr_mod, "_vision_engine", _StubVision(script))
        mp.setattr(ocr_mod, "_paddle_models_present", lambda: models_present)
        ocr_mod._vision_exc_streak = 0
        ocr_mod._vision_disabled_session = False

    def test_three_consecutive_errors_flip_session(self, clean_engine_state):
        self._arm(clean_engine_state, [VisionEngineError("x")] * 3)
        for _ in range(3):
            items, errored = ocr_mod._vision_recognize_unlocked(IMG)
            assert items == [] and errored
        assert ocr_mod._vision_disabled_session is True

    def test_success_resets_the_streak(self, clean_engine_state):
        self._arm(clean_engine_state, [
            VisionEngineError("a"), VisionEngineError("b"),
            [VISION_ITEM],
            VisionEngineError("c"), VisionEngineError("d"),
        ])
        for _ in range(5):
            ocr_mod._vision_recognize_unlocked(IMG)
        # 2 errors, success (reset), 2 errors -> never reaches 3 consecutive
        assert ocr_mod._vision_disabled_session is False
        assert ocr_mod._vision_exc_streak == 2

    def test_models_absent_never_flips_and_never_downloads(self, clean_engine_state):
        self._arm(clean_engine_state, [VisionEngineError("x")] * 5, models_present=False)
        for _ in range(5):
            ocr_mod._vision_recognize_unlocked(IMG)
        assert ocr_mod._vision_disabled_session is False


class TestPerCropFallback:
    def _arm(self, mp, vision_script, models_present=True):
        mp.setattr(ocr_mod, "_vision_engine", _StubVision(vision_script))
        mp.setattr(ocr_mod, "_paddle_models_present", lambda: models_present)
        mp.setattr(ocr_mod, "_paddle_recognize_unlocked", lambda img: [dict(FAKE_ITEM)])
        ocr_mod._resolved_engine = "vision"
        ocr_mod._vision_exc_streak = 0
        ocr_mod._vision_disabled_session = False

    def test_zero_items_with_expected_text_does_NOT_fall_back(self, clean_engine_state):
        # Label taps POLL for text that isn't on screen yet; a fallback there
        # doubles every poll tick for nothing (first live run: 23/38 reads).
        self._arm(clean_engine_state, [[]])
        items, engine, fb = ocr_mod._recognize_crop_unlocked(IMG, expected_text="Read & Claim")
        assert items == [] and engine == "vision" and fb is False

    def test_zero_items_with_value_kind_falls_back(self, clean_engine_state):
        self._arm(clean_engine_state, [[]])
        items, engine, fb = ocr_mod._recognize_crop_unlocked(IMG, read_kind="value")
        assert fb is True and engine == "vision+fallback"
        assert items[0]["text"] == "fallback!"

    def test_zero_items_without_expectation_stays_empty(self, clean_engine_state):
        self._arm(clean_engine_state, [[]])
        items, engine, fb = ocr_mod._recognize_crop_unlocked(IMG)
        assert items == [] and engine == "vision" and fb is False

    def test_nonzero_vision_read_never_falls_back(self, clean_engine_state):
        self._arm(clean_engine_state, [[dict(VISION_ITEM)]])
        items, engine, fb = ocr_mod._recognize_crop_unlocked(IMG, expected_text="something else")
        assert fb is False and items[0]["text"] == "vision"

    def test_models_absent_disables_fallback(self, clean_engine_state):
        self._arm(clean_engine_state, [[]], models_present=False)
        items, engine, fb = ocr_mod._recognize_crop_unlocked(IMG, read_kind="value")
        assert items == [] and fb is False

    def test_paddle_mode_bypasses_vision_entirely(self, clean_engine_state):
        self._arm(clean_engine_state, [[dict(VISION_ITEM)]])
        ocr_mod._resolved_engine = "paddle"
        items, engine, fb = ocr_mod._recognize_crop_unlocked(IMG, read_kind="value")
        assert engine == "paddle" and items[0]["text"] == "fallback!" and fb is False

    def test_exception_counts_as_zero_and_falls_back(self, clean_engine_state):
        self._arm(clean_engine_state, [VisionEngineError("boom")])
        items, engine, fb = ocr_mod._recognize_crop_unlocked(IMG, read_kind="value")
        assert fb is True and items[0]["text"] == "fallback!"

    def test_score_floor_applied_to_vision_items(self, clean_engine_state):
        low = {"text": "faint", "score": 0.5, "box": [0, 0, 1, 1]}
        self._arm(clean_engine_state, [[low]])
        items, engine, fb = ocr_mod._recognize_crop_unlocked(IMG)
        assert items == []  # 0.5 < OCR_SCORE_FLOOR -> dropped

    def test_breaker_trip_mid_call_uses_paddle_as_session_engine(self, clean_engine_state):
        # Two errors already on the streak; THIS read's error trips the breaker
        # during the call. The paddle read that follows is the session engine
        # now ("paddle"), not a one-shot fallback ("vision+fallback").
        self._arm(clean_engine_state, [VisionEngineError("boom")])
        ocr_mod._vision_exc_streak = 2
        items, engine, fb = ocr_mod._recognize_crop_unlocked(IMG, read_kind="value")
        assert engine == "paddle" and fb is False
        assert items[0]["text"] == "fallback!"
        assert ocr_mod._vision_disabled_session is True


class TestShadowCompare:
    def test_digit_agreement_returns_none(self, clean_engine_state):
        clean_engine_state.setattr(ocr_mod, "_paddle_models_present", lambda: True)
        clean_engine_state.setattr(
            ocr_mod, "_paddle_recognize_unlocked",
            lambda img: [{"text": "X:1019 Y:308", "score": 0.99, "box": [0, 0, 1, 1]}])
        # Same digits split across differently-segmented lines still agree.
        vision_items = [{"text": "X:1019", "score": 1.0, "box": [0, 0, 1, 1]},
                        {"text": "Y:308", "score": 1.0, "box": [0, 0, 1, 1]}]
        assert ocr_mod._shadow_compare_unlocked(IMG, vision_items) is None

    def test_digit_disagreement_reports_mismatch(self, clean_engine_state):
        clean_engine_state.setattr(ocr_mod, "_paddle_models_present", lambda: True)
        clean_engine_state.setattr(
            ocr_mod, "_paddle_recognize_unlocked",
            lambda img: [{"text": "102,481", "score": 0.99, "box": [0, 0, 1, 1]}])
        vision_items = [{"text": "102,431", "score": 1.0, "box": [0, 0, 1, 1]}]
        m = ocr_mod._shadow_compare_unlocked(IMG, vision_items)
        assert m is not None
        assert m["vision_digits"] == "102431" and m["paddle_digits"] == "102481"

    def test_models_absent_skips_shadow_read(self, clean_engine_state):
        clean_engine_state.setattr(ocr_mod, "_paddle_models_present", lambda: False)
        clean_engine_state.setattr(
            ocr_mod, "_paddle_recognize_unlocked",
            lambda img: pytest.fail("shadow read must not run without paddle models"))
        vision_items = [{"text": "123", "score": 1.0, "box": [0, 0, 1, 1]}]
        assert ocr_mod._shadow_compare_unlocked(IMG, vision_items) is None


class TestBurninLedger:
    """The producer side of the burn-in contract: _burnin_log must emit the
    keys scripts/burnin_report.py's verdict math consumes."""

    def test_disabled_writes_nothing(self, clean_engine_state, tmp_path):
        clean_engine_state.setattr(ocr_mod, "BURNIN_ENABLED", False)
        clean_engine_state.setattr(ocr_mod, "BURNIN_LOG_PATH", tmp_path / "burnin.jsonl")
        ocr_mod._burnin_log({"decision_id": "d1"})
        assert not (tmp_path / "burnin.jsonl").exists()

    def test_enabled_appends_record_with_ts_and_rss(self, clean_engine_state, tmp_path):
        clean_engine_state.setattr(ocr_mod, "BURNIN_ENABLED", True)
        clean_engine_state.setattr(ocr_mod, "BURNIN_LOG_PATH", tmp_path / "burnin.jsonl")
        ocr_mod._burnin_log({"decision_id": "d1", "read_kind": "value",
                             "expected": False, "fallback_hits": 0,
                             "digit_mismatch": False})
        rec = json.loads((tmp_path / "burnin.jsonl").read_text().splitlines()[0])
        assert rec["decision_id"] == "d1"
        # ts and rss_mb are stamped by the logger itself; compute_verdict
        # keys on both (duration window and RSS-growth criterion).
        assert "ts" in rec and "rss_mb" in rec


class TestRunOcrPlumbing:
    """run_ocr's ROI leg offline (img_path fixture, stub engine): pad/offset
    box math back into frame space, and the burn-in record it emits."""

    def _arm(self, mp, tmp_path, items, shadow=None):
        mp.setattr(ocr_mod, "BURNIN_ENABLED", True)
        mp.setattr(ocr_mod, "BURNIN_LOG_PATH", tmp_path / "burnin.jsonl")
        ocr_mod._paddle_engine = None  # RAM guard must stay a no-op
        seen = {}

        def fake_crop_read(image, expected_text=None, read_kind=None):
            seen["shape"] = image.shape
            return [dict(i) for i in items], "vision", False

        mp.setattr(ocr_mod, "_recognize_crop_unlocked", fake_crop_read)
        mp.setattr(ocr_mod, "_shadow_compare_unlocked", lambda img, it: shadow)
        return seen

    def test_roi_offsets_and_burnin_record(self, clean_engine_state, tmp_path):
        seen = self._arm(clean_engine_state, tmp_path,
                         [{"text": "42", "score": 0.99, "box": [60, 60, 80, 70]}])
        results = ocr_mod.run_ocr(
            img_path="tests/fixtures/home_night.png",
            rois=[[100, 200, 300, 400]],
            name="unit.roi", read_kind="value", decision_id="abc123",
        )
        # 200x200 crop + 50px pad on every side reaches the engine...
        assert seen["shape"] == (300, 300, 3)
        # ...and the crop-relative box is re-offset into frame space:
        # x - pad + x1 = 60 - 50 + 100, y - pad + y1 = 60 - 50 + 200.
        assert results == [{"text": "42", "score": 0.99, "box": [110, 210, 130, 220]}]

        rec = json.loads((tmp_path / "burnin.jsonl").read_text().splitlines()[0])
        assert rec["decision_id"] == "abc123"
        assert rec["read_kind"] == "value"
        assert rec["engines"] == ["vision"]
        assert rec["fallback_hits"] == 0
        assert rec["digit_mismatch"] is False
        assert rec["results"] == 1

    def test_shadow_mismatch_lands_in_record_with_roi_index(self, clean_engine_state, tmp_path):
        mismatch = {"vision_digits": "102431", "paddle_digits": "102481",
                    "vision_texts": ["102,431"], "paddle_texts": ["102,481"]}
        self._arm(clean_engine_state, tmp_path,
                  [{"text": "102,431", "score": 0.99, "box": [0, 0, 9, 9]}],
                  shadow=mismatch)
        results = ocr_mod.run_ocr(
            img_path="tests/fixtures/home_night.png",
            rois=[[100, 200, 300, 400]],
            name="unit.mismatch", read_kind="value", decision_id="mm1",
        )
        assert results  # a mismatch flags the record, it does not eat the read
        rec = json.loads((tmp_path / "burnin.jsonl").read_text().splitlines()[0])
        assert rec["digit_mismatch"] is True
        assert rec["mismatches"][0]["roi_index"] == 0
        assert rec["mismatches"][0]["vision_digits"] == "102431"


class TestRamCapGating:
    def test_noop_while_no_paddle_engine(self, clean_engine_state):
        ocr_mod._paddle_engine = None
        clean_engine_state.setattr(
            ocr_mod, "_get_process_rss_bytes",
            lambda: (_ for _ in ()).throw(AssertionError("RSS checked on vision path")))
        ocr_mod._enforce_ram_cap("test")  # must return before touching RSS

    def test_active_with_paddle_engine_under_cap(self, clean_engine_state):
        ocr_mod._paddle_engine = object()
        clean_engine_state.setattr(ocr_mod, "_get_process_rss_bytes", lambda: 1024)
        ocr_mod._enforce_ram_cap("test")  # under cap -> returns quietly


class TestFallbackHonesty:
    def test_zero_both_engines_is_not_a_fallback_hit(self, clean_engine_state):
        # Empty march slot: Vision sees nothing, Paddle sees nothing. Counting
        # that as a fallback hit structurally inflates the burn-in rate.
        clean_engine_state.setattr(ocr_mod, "_vision_engine", _StubVision([[]]))
        clean_engine_state.setattr(ocr_mod, "_paddle_models_present", lambda: True)
        clean_engine_state.setattr(ocr_mod, "_paddle_recognize_unlocked", lambda img: [])
        ocr_mod._resolved_engine = "vision"
        ocr_mod._vision_exc_streak = 0
        ocr_mod._vision_disabled_session = False
        items, engine, fb = ocr_mod._recognize_crop_unlocked(IMG, read_kind="value")
        assert items == [] and engine == "vision" and fb is False
