"""Vision engine unit + integration tests (macOS-only; skipped elsewhere)."""
import sys

import pytest

darwin_only = pytest.mark.skipif(sys.platform != "darwin", reason="Apple Vision is macOS-only")


class TestConvertBox:
    """Pure math: Vision normalized bottom-left rect -> pixel top-left box."""

    def test_full_image_rect(self):
        from core.vision_engine import convert_box
        assert convert_box(0.0, 0.0, 1.0, 1.0, 1080, 2460) == [0, 0, 1080, 2460]

    def test_bottom_left_origin_flip(self):
        from core.vision_engine import convert_box
        # A rect hugging Vision's bottom edge (origin_y=0) maps to the IMAGE bottom.
        box = convert_box(0.0, 0.0, 0.5, 0.1, 1000, 1000)
        assert box == [0, 900, 500, 1000]

    def test_top_edge_rect(self):
        from core.vision_engine import convert_box
        # A rect hugging Vision's top edge (origin_y + h = 1) maps to image y=0.
        box = convert_box(0.25, 0.9, 0.5, 0.1, 1000, 1000)
        assert box == [250, 0, 750, 100]

    def test_known_title_geometry(self):
        from core.vision_engine import convert_box
        # 'Chief Profile' title on a 1080x2460 frame sits near y~155-213 px.
        # Vision-normalized equivalent: origin_y = 1 - (213/2460) - h.
        y1_px, y2_px = 155, 213
        h_norm = (y2_px - y1_px) / 2460
        origin_y = 1.0 - (y2_px / 2460)
        box = convert_box(128 / 1080, origin_y, (430 - 128) / 1080, h_norm, 1080, 2460)
        assert box == [128, 155, 430, 213]


@darwin_only
class TestRecognize:
    def test_rejects_invalid_buffer(self):
        import numpy as np
        from core.vision_engine import VisionEngine, VisionEngineError
        engine = VisionEngine()
        with pytest.raises(VisionEngineError):
            engine.recognize(np.zeros((10, 10), dtype=np.uint8))  # 2-D, not BGR

    def test_reads_synthetic_text(self):
        import cv2
        import numpy as np
        from core.vision_engine import VisionEngine
        img = np.full((120, 640, 3), 255, dtype=np.uint8)
        cv2.putText(img, "HELLO 12345", (20, 80), cv2.FONT_HERSHEY_SIMPLEX,
                    2.0, (0, 0, 0), 4)
        items = VisionEngine().recognize(img)
        joined = " ".join(i["text"] for i in items)
        assert "12345" in joined.replace(" ", "") or "12345" in joined

    def test_zero_observations_is_empty_list_not_error(self):
        import numpy as np
        from core.vision_engine import VisionEngine
        blank = np.full((100, 100, 3), 200, dtype=np.uint8)
        assert VisionEngine().recognize(blank) == []

    def test_memory_vs_file_parity(self, tmp_path):
        """The in-memory CGImage path must read identically to a file-URL
        handler with the same request config — catches channel-order and
        bitmap-info mistakes in _cgimage_from_bgr."""
        import cv2
        import Vision
        from Foundation import NSURL
        from core.vision_engine import VisionEngine, PINNED_REVISION

        img = cv2.imread("test/test.png")
        crop = img[145:210, 130:430]  # 'Chief Profile' title
        engine = VisionEngine()
        mem_texts = [i["text"] for i in engine.recognize(crop)]

        p = tmp_path / "crop.png"
        cv2.imwrite(str(p), crop)
        handler = Vision.VNImageRequestHandler.alloc().initWithURL_options_(
            NSURL.fileURLWithPath_(str(p)), None
        )
        req = Vision.VNRecognizeTextRequest.alloc().init()
        req.setRevision_(PINNED_REVISION)
        req.setRecognitionLevel_(Vision.VNRequestTextRecognitionLevelAccurate)
        req.setUsesLanguageCorrection_(False)
        req.setRecognitionLanguages_(["en-US"])
        ok, _ = handler.performRequests_error_([req], None)
        assert ok
        file_texts = [str(o.topCandidates_(1)[0].string()) for o in req.results() or []]

        assert mem_texts == file_texts
        assert "Chief Profile" in mem_texts

    def test_revision_is_pinned(self):
        from core.vision_engine import VisionEngine, PINNED_REVISION
        engine = VisionEngine()
        assert engine._build_request().revision() == PINNED_REVISION
