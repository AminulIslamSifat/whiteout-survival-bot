"""Apple Vision text recognition engine (macOS-only).

Drop-in recognizer behind run_ocr()'s engine seam. Returns the same item shape
as the Paddle path: [{"text": str, "score": float, "box": [x1, y1, x2, y2]}]
with boxes in pixel space, top-left origin — Vision's normalized bottom-left
boxes are converted here so callers never see the difference.

The request revision is PINNED (see PINNED_REVISION): macOS updates move the
default recognizer, which would silently shift accuracy under the bot.
Revision bumps are deliberate: re-run the fixture crop suite, then update the
pin. Revision 3 is what the 2026-08-29 bake-off validated (31 crops/4 frames,
fuzzy>=80 parity with PaddleOCR, ~17ms/crop).

Every call runs inside an explicit autorelease pool: this module lives in a
persistent FastAPI server, and repeated CoreGraphics/Vision calls accumulate
Objective-C objects without one.
"""
import platform

import numpy as np
import objc
import Quartz
import Vision

PINNED_REVISION = 3  # VNRecognizeTextRequestRevision3 — bake-off-validated


class VisionEngineError(RuntimeError):
    """Vision framework failed to process a request (bridge/NSError path)."""


def convert_box(origin_x, origin_y, size_w, size_h, img_w, img_h):
    """Vision normalized bottom-left rect -> pixel top-left [x1, y1, x2, y2]."""
    x1 = origin_x * img_w
    y1 = (1.0 - origin_y - size_h) * img_h
    return [
        int(round(x1)),
        int(round(y1)),
        int(round(x1 + size_w * img_w)),
        int(round(y1 + size_h * img_h)),
    ]


def _cgimage_from_bgr(img_bgr):
    """Build a CGImage from a numpy BGR frame in memory — no temp files.

    Returns (cgimage, data_ref); the caller must keep data_ref alive until the
    request has been performed (CGDataProviderCreateWithData does not copy).
    """
    if img_bgr is None or img_bgr.size == 0 or img_bgr.ndim != 3 or img_bgr.shape[2] != 3:
        raise VisionEngineError(f"invalid image buffer: shape={getattr(img_bgr, 'shape', None)}")

    h, w = img_bgr.shape[:2]
    rgb = np.ascontiguousarray(img_bgr[:, :, ::-1])
    data = rgb.tobytes()
    provider = Quartz.CGDataProviderCreateWithData(None, data, len(data), None)
    cg = Quartz.CGImageCreate(
        w, h,
        8,          # bits per component
        24,         # bits per pixel (RGB, no alpha)
        3 * w,      # bytes per row
        Quartz.CGColorSpaceCreateDeviceRGB(),
        Quartz.kCGImageAlphaNone,
        provider,
        None,
        False,
        Quartz.kCGRenderingIntentDefault,
    )
    if cg is None:
        raise VisionEngineError(f"CGImageCreate failed for {w}x{h} frame")
    return cg, data


class VisionEngine:
    def __init__(self, console=None):
        self._log = console.print if console is not None else print
        supported = Vision.VNRecognizeTextRequest.supportedRevisions()
        if not supported.containsIndex_(PINNED_REVISION):
            raise VisionEngineError(
                f"pinned Vision revision {PINNED_REVISION} not supported on this macOS "
                f"({platform.mac_ver()[0]}) — re-validate with the crop suite before changing the pin"
            )
        self._log(
            f"Vision engine: revision {PINNED_REVISION} (pinned), "
            f"macOS {platform.mac_ver()[0]}, "
            f"framework current revision {Vision.VNRecognizeTextRequest.currentRevision()}"
        )

    def _build_request(self):
        req = Vision.VNRecognizeTextRequest.alloc().init()
        req.setRevision_(PINNED_REVISION)
        req.setRecognitionLevel_(Vision.VNRequestTextRecognitionLevelAccurate)
        req.setUsesLanguageCorrection_(False)
        req.setRecognitionLanguages_(["en-US"])
        return req

    def recognize(self, img_bgr):
        """OCR a BGR numpy frame. Returns items; raises VisionEngineError on failure.

        Zero observations is a normal outcome (empty list), not an error —
        run_ocr's fallback rule keys on it.
        """
        h, w = img_bgr.shape[:2] if img_bgr is not None and img_bgr.ndim >= 2 else (0, 0)
        with objc.autorelease_pool():
            cg, data_ref = _cgimage_from_bgr(img_bgr)
            handler = Vision.VNImageRequestHandler.alloc().initWithCGImage_options_(cg, None)
            req = self._build_request()
            ok, err = handler.performRequests_error_([req], None)
            del data_ref  # request performed; buffer no longer needed
            if not ok:
                raise VisionEngineError(f"VNImageRequestHandler failed: {err}")

            items = []
            for obs in req.results() or []:
                candidates = obs.topCandidates_(1)
                if not candidates:
                    continue
                bb = obs.boundingBox()
                items.append({
                    "text": str(candidates[0].string()),
                    "score": float(candidates[0].confidence()),
                    "box": convert_box(
                        bb.origin.x, bb.origin.y, bb.size.width, bb.size.height, w, h
                    ),
                })
            return items

    def warmup(self):
        """Pay the first-call model-load cost at boot instead of on the first read."""
        blank = np.full((64, 256, 3), 128, dtype=np.uint8)
        try:
            self.recognize(blank)
        except VisionEngineError:
            pass  # warmup is best-effort; real reads surface real errors
