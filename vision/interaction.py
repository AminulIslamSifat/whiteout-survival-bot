"""
High-level interaction functions: tap_on_text, tap_on_template, req_text, etc.

These replace the global functions from core/core.py.
All functions take DeviceContext + OCRClient + CalibrationDB explicitly.
No module-level state.
"""

from __future__ import annotations

import inspect
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from itertools import repeat
from typing import Any, Optional

from rapidfuzz import fuzz

from config import BotConfig
from core.logging_config import get_logger
from device.adb import DeviceContext
from vision.calibration import CalibrationDB
from vision.ocr_client import OCRClient

logger = get_logger(__name__)


class Interaction:
    """
    Stateful interaction layer binding DeviceContext + OCRClient + CalibrationDB.

    Usage:
        ix = Interaction(device, ocr, calibration, config)
        ix.tap_on_text("Home.World", wait=2)
    """

    def __init__(
        self,
        device: DeviceContext,
        ocr: OCRClient,
        calibration: CalibrationDB,
        config: BotConfig,
    ) -> None:
        self.device = device
        self.ocr = ocr
        self.cal = calibration
        self.config = config

    # ── Coordinate helpers ───────────────────────────────────────────

    def _convert_rois_percent_to_pixel(self, rois: Any) -> Any:
        """Convert percentage-based ROI coordinates to pixel coordinates."""
        if rois is None:
            return None

        def _is_percent_box(box: Any) -> bool:
            try:
                return (
                    isinstance(box, (list, tuple))
                    and len(box) == 4
                    and all(isinstance(v, (int, float)) for v in box)
                    and all(0 <= v <= 100 for v in box)
                )
            except Exception:
                return False

        if isinstance(rois, list):
            if len(rois) == 0:
                return rois
            # Single flat box [x1,y1,x2,y2]
            if len(rois) == 4 and isinstance(rois[0], (int, float)):
                return self._box_pct_to_px(rois) if _is_percent_box(rois) else rois
            # List of boxes
            if isinstance(rois[0], list):
                result = []
                for box in rois:
                    if len(box) == 4:
                        result.append(self._box_pct_to_px(box) if _is_percent_box(box) else box)
                    else:
                        result.append(box)
                return result

        return rois

    def _box_pct_to_px(self, box: list[float]) -> list[int]:
        x1, y1 = self.device.pct_to_px(box[0], box[1])
        x2, y2 = self.device.pct_to_px(box[2], box[3])
        return [x1, y1, x2, y2]

    def _center_of_box(self, box: list[int]) -> tuple[int, int]:
        return ((box[0] + box[2]) // 2, (box[1] + box[3]) // 2)

    # ── OCR requests ─────────────────────────────────────────────────

    def req_ocr(
        self,
        *,
        img_path: Optional[str] = None,
        save_result: Optional[bool] = None,
        rois: Any = None,
        name: Optional[str] = None,
        expected_text: Optional[str] = None,
    ) -> Optional[list[dict[str, Any]]]:
        """Send OCR request with automatic percent-to-pixel ROI conversion."""
        if name is None:
            frame = inspect.currentframe().f_back
            caller = frame.f_code.co_filename.split("/")[-1]
            line = frame.f_lineno
            func = frame.f_code.co_name
            logger.warning("req_ocr called WITHOUT name from %s:%d in %s()", caller, line, func)

        rois = self._convert_rois_percent_to_pixel(rois)
        return self.ocr.request_ocr(
            img_path=img_path,
            save_result=save_result,
            rois=rois,
            name=name,
            expected_text=expected_text,
        )

    def req_text(
        self,
        names: Optional[str | list[str]] = None,
        *,
        img_path: Optional[str] = None,
        rois: Any = None,
        save_result: bool = False,
    ) -> Optional[list[list[Any]]]:
        """
        Request OCR for named text areas.
        Returns list of [text, box] pairs, or None on failure.
        """
        if not names:
            frame = inspect.currentframe().f_back
            caller = frame.f_code.co_filename.split("/")[-1]
            line = frame.f_lineno
            func = frame.f_code.co_name
            logger.warning("req_text() called WITHOUT names from %s:%d in %s() — full_page scan", caller, line, func)
            res = self.req_ocr(img_path=img_path, save_result=save_result, rois=rois, name="full_page")
            if res is None:
                return None
            return [[t["text"], t["box"]] for t in res]

        if isinstance(names, str):
            names = [names]

        # Build ROI boxes from calibration
        boxes: list[list[float]] = []
        if rois is not None:
            if isinstance(rois, list) and len(rois) > 0 and isinstance(rois[0], (list, tuple)):
                for i, name in enumerate(names):
                    boxes.append(rois[i] if i < len(rois) else self.cal.get_text_box(name) or [0, 0, 100, 100])
            elif isinstance(rois, list) and len(rois) == 4 and all(isinstance(v, (int, float)) for v in rois):
                boxes = [rois for _ in names]
            else:
                boxes = [self.cal.get_text_box(n) or [0, 0, 100, 100] for n in names]
        else:
            boxes = [self.cal.get_text_box(n) or [0, 0, 100, 100] for n in names]

        title = ", ".join(names)
        pixel_boxes = self._convert_rois_percent_to_pixel(boxes)
        res = self.ocr.request_ocr(img_path=img_path, save_result=save_result, rois=pixel_boxes, name=title)
        if res is None:
            return None
        return [[t["text"], t["box"]] for t in res]

    def req_temp_match(
        self,
        name: str,
        *,
        threshold: float = 0.8,
        save_result: Optional[bool] = None,
        rois: Any = None,
        parallel: Optional[bool] = None,
        session_id: Optional[str] = None,
    ) -> Optional[list[dict[str, Any]]]:
        """Template match request with automatic ROI conversion."""
        rois = self._convert_rois_percent_to_pixel(rois)
        return self.ocr.request_template_match(
            name,
            threshold=threshold,
            save_result=save_result,
            rois=rois,
            parallel=parallel,
            session_id=session_id,
        )

    # ── Tap actions ──────────────────────────────────────────────────

    def tap_on_template(
        self,
        name: str,
        *,
        threshold: Optional[float] = None,
        save_result: Optional[bool] = None,
        wait: Optional[float] = None,
        sleep: float = 0.3,
        tap: bool = True,
        rois: Any = None,
        hold: Optional[int] = None,
    ) -> Optional[bool]:
        """Find and tap a template match."""
        passed_threshold = threshold
        cal_entry = self.cal.get_template(name)
        if cal_entry:
            if threshold is None:
                threshold = cal_entry.get("threshold") or 0.8
            if rois is None:
                rois = cal_entry.get("box")
        if threshold is None:
            threshold = 0.8

        _orig_threshold = threshold

        def try_match() -> Optional[bool]:
            results = self.req_temp_match(name, threshold=threshold, save_result=save_result, rois=rois)
            if not results:
                return None
            result = max(results, key=lambda x: x["score"])
            coord = self._center_of_box(result["box"])

            if coord and hold:
                self.device.long_press(coord[0], coord[1], duration=hold, coord=True)
                logger.info("Long pressed on %s for %dms", name, hold)
            elif coord and tap:
                self.device.tap(coord[0], coord[1], coord=True)
                logger.info("Pressed on %s", name)
                if sleep:
                    time.sleep(sleep)
            return bool(coord)

        if wait:
            start = time.time()
            while time.time() - start < wait:
                elapsed = time.time() - start
                if passed_threshold is None:
                    steps = int(elapsed / 0.4)
                    threshold = max(_orig_threshold - steps * 0.05, 0.6)
                if try_match():
                    return True
            return None

        for steps in range(3):
            if passed_threshold is None:
                threshold = max(_orig_threshold - steps * 0.05, 0.6)
            if try_match():
                return True
            logger.warning("No match found for %s", name)
            time.sleep(1)
        return None

    def tap_on_text(
        self,
        text: str | list[str],
        *,
        img_path: Optional[str] = None,
        save_result: Optional[bool] = None,
        rois: Any = None,
        wait: Optional[float] = None,
        sleep: float = 0.3,
        skip_ocr: bool = False,
        tap: bool = True,
        hold: Optional[int] = None,
        threshold: float = 0.8,
        align: Optional[list[float]] = None,
    ) -> Optional[bool]:
        """Find and tap text via OCR with fuzzy matching."""
        name = text if isinstance(text, str) else text[0] if text else "unknown"

        if align is None or not isinstance(align, list) or len(align) != 2:
            align = [0, 0]

        sw, sh = self.device.screen_size
        align_px = (int((align[0] / 100) * sw), int((align[1] / 100) * sh))
        threshold_pct = threshold * 100

        def normalize_rois(box: Any) -> Optional[list[list[int]]]:
            if box is None:
                return None
            if isinstance(box, list) and all(isinstance(b, list) and len(b) == 4 for b in box):
                return box
            if isinstance(box, list) and len(box) == 4 and all(isinstance(v, (int, float)) for v in box):
                return [box]
            logger.warning("Invalid ROI format: %s", box)
            return None

        def load_config(texts: str | list[str], rois_override: Any = None) -> dict[str, dict]:
            if isinstance(texts, str):
                texts = [texts]
            text_data: dict[str, dict] = {}
            for t in texts:
                entry = self.cal.get_text(t)
                item = entry.copy() if entry else {"text": t, "score": None, "box": None}
                if rois_override is not None:
                    item["box"] = rois_override
                text_data[t] = item
            return text_data

        def try_match(texts: dict[str, dict], expand_px: int = 0) -> bool:
            for key, value in texts.items():
                target_text = value["text"]
                box = value["box"]

                if skip_ocr and box is not None:
                    def _is_percent_box(b: Any) -> bool:
                        try:
                            if not isinstance(b, (list, tuple)) or len(b) != 4:
                                return False
                            return all(isinstance(v, (int, float)) and 0 <= v <= 100 for v in b)
                        except Exception:
                            return False

                    pixel_box = self._box_pct_to_px(box) if _is_percent_box(box) else box
                    cx = (pixel_box[0] + pixel_box[2]) // 2
                    cy = (pixel_box[1] + pixel_box[3]) // 2
                    coord = (cx + align_px[0], cy + align_px[1])
                    if hold:
                        self.device.long_press(coord[0], coord[1], duration=hold, coord=True)
                    elif tap:
                        self.device.tap(coord[0], coord[1], coord=True)
                        logger.info("Pressed on %s (skip OCR)", target_text)
                    if sleep:
                        time.sleep(sleep)
                    return True

                roi_box = normalize_rois(box)
                res = self.req_ocr(img_path=img_path, save_result=save_result, rois=roi_box, name=name, expected_text=target_text)
                if res is None:
                    continue

                # Exact match
                for item in res:
                    if item["text"].lower() == target_text.lower():
                        use_box = item.get("box")
                        if not use_box:
                            continue
                        cx = (use_box[0] + use_box[2]) // 2
                        cy = (use_box[1] + use_box[3]) // 2
                        coord = (cx + align_px[0], cy + align_px[1])
                        if hold:
                            self.device.long_press(coord[0], coord[1], duration=hold, coord=True)
                        elif tap:
                            self.device.tap(coord[0], coord[1], coord=True)
                            logger.info("Pressed on %s", item["text"])
                        if sleep:
                            time.sleep(sleep)
                        return True

                # Fuzzy match
                for item in res:
                    item["fuzzy_score"] = fuzz.ratio(item["text"].lower(), target_text.lower())
                sorted_res = sorted(res, key=lambda x: x["fuzzy_score"], reverse=True)
                sorted_res = [item for item in sorted_res if item["fuzzy_score"] > threshold_pct]
                best = max(sorted_res, key=lambda x: x["fuzzy_score"], default=None)
                if best:
                    use_box = best.get("box")
                    if use_box:
                        cx = (use_box[0] + use_box[2]) // 2
                        cy = (use_box[1] + use_box[3]) // 2
                        coord = (cx + align_px[0], cy + align_px[1])
                        if hold:
                            self.device.long_press(coord[0], coord[1], duration=hold, coord=True)
                        elif tap:
                            self.device.tap(coord[0], coord[1], coord=True)
                            logger.info("Pressed on %s", best["text"])
                        if sleep:
                            time.sleep(sleep)
                        return True

            return False

        texts = load_config(text, rois)
        if not texts:
            logger.warning("No text to press on")
            return None

        if wait:
            start = time.time()
            while time.time() - start < wait:
                elapsed = time.time() - start
                expand_px = int(elapsed / 0.4) * 5
                if try_match(texts, expand_px=expand_px):
                    return True
                time.sleep(0.1)
            logger.warning("No match found for text: %s", name)
            return None

        for i in range(3):
            expand_px = (i + 1) * 5
            if try_match(texts, expand_px=expand_px):
                return True
            time.sleep(1)

        logger.warning("No match found for text: %s", name)
        return None

    def tap_on_templates_batch(
        self,
        names: list[str],
        *,
        thresholds: Optional[list[float]] = None,
        save_results: Optional[list[Optional[bool]]] = None,
        wait: Optional[float] = None,
        tap: bool | list[bool] = True,
        sleep: Optional[float] = None,
        rois: Any = None,
        parallel: bool = False,
        max_workers: int = 8,
    ) -> bool:
        """Batch template matching — find best match across multiple templates."""
        n = len(names)
        if n == 0:
            return False

        passed_threshold = thresholds
        thresholds = thresholds or [0.8] * n
        save_results = save_results or [None] * n
        if isinstance(tap, bool):
            tap_flags = [tap] * n
        else:
            tap_flags = tap
        _orig_thresholds = list(thresholds)

        def match_one(i: int, session_id: str) -> Optional[tuple[int, dict]]:
            results = self.req_temp_match(
                names[i],
                threshold=thresholds[i],
                save_result=save_results[i],
                rois=rois,
                parallel=True,
                session_id=session_id,
            )
            if results:
                best = max(results, key=lambda x: x["score"])
                return (i, best)
            return None

        def run_batch(session_id: str) -> list[tuple[int, dict]]:
            if parallel and n > 1:
                workers = max(1, min(max_workers, n))
                with ThreadPoolExecutor(max_workers=workers) as ex:
                    raw = list(ex.map(match_one, range(n), repeat(session_id)))
            else:
                raw = [match_one(i, session_id) for i in range(n)]
            return [r for r in raw if r is not None]

        def pick_best_and_tap(cleaned: list[tuple[int, dict]]) -> bool:
            i, best = max(cleaned, key=lambda x: x[1]["score"])
            coord = self._center_of_box(best["box"])
            if tap_flags[i]:
                self.device.tap(coord[0], coord[1], coord=True)
                logger.info("Pressed on %s", names[i])
                if sleep:
                    time.sleep(sleep)
            return True

        if wait:
            session_id = str(uuid.uuid4())
            start = time.time()
            try:
                while time.time() - start < wait:
                    elapsed = time.time() - start
                    if passed_threshold is None:
                        steps = int(elapsed / 0.4)
                        thresholds = [max(orig - steps * 0.05, 0.6) for orig in _orig_thresholds]
                    cleaned = run_batch(session_id)
                    if cleaned:
                        return pick_best_and_tap(cleaned)
            finally:
                if parallel:
                    self.ocr.clear_cache(session_id)
            return False

        start = time.time()
        for _ in range(3):
            session_id = str(uuid.uuid4())
            try:
                elapsed = time.time() - start
                if passed_threshold is None:
                    steps = int(elapsed / 0.4)
                    thresholds = [max(orig - steps * 0.05, 0.6) for orig in _orig_thresholds]
                cleaned = run_batch(session_id)
            finally:
                if parallel:
                    self.ocr.clear_cache(session_id)
            if cleaned:
                return pick_best_and_tap(cleaned)
        return False

    def tap_on_closest_text(
        self,
        base_text: str,
        target_text: str,
        *,
        rois: Any = None,
        threshold: float = 0.8,
        save_result: Optional[bool] = None,
        wait: Optional[float] = None,
        sleep: float = 0.3,
        align: Optional[list[float]] = None,
        maximum_distance: Optional[float] = None,
    ) -> Optional[bool]:
        """Find base_text via OCR, then tap the closest instance of target_text."""
        threshold_pct = threshold * 100 if threshold else 80

        if align is None or not isinstance(align, list) or len(align) != 2:
            align = [0, 0]
        sw, sh = self.device.screen_size
        align_px = (int((align[0] / 100) * sw), int((align[1] / 100) * sh))

        def center(box: list[int]) -> tuple[int, int]:
            return ((box[0] + box[2]) // 2, (box[1] + box[3]) // 2)

        def distance(c1: tuple[int, int], c2: tuple[int, int]) -> float:
            return ((c1[0] - c2[0]) ** 2 + (c1[1] - c2[1]) ** 2) ** 0.5

        def try_match() -> Optional[bool]:
            res = self.req_ocr(rois=rois, save_result=save_result, name=f"closest:{base_text}->{target_text}")
            if not res:
                return None

            base_items = []
            target_items = []
            for item in res:
                score = fuzz.ratio(item["text"].lower(), base_text.lower())
                if score > threshold_pct:
                    base_items.append(item)
                score2 = fuzz.ratio(item["text"].lower(), target_text.lower())
                if score2 > threshold_pct:
                    target_items.append(item)

            if not base_items or not target_items:
                return None

            best_base = max(base_items, key=lambda x: fuzz.ratio(x["text"].lower(), base_text.lower()))
            base_center = center(best_base["box"])

            max_dist_px = None
            if maximum_distance is not None:
                max_dist_px = (maximum_distance / 100) * sw

            closest = None
            closest_dist = float("inf")
            for item in target_items:
                d = distance(base_center, center(item["box"]))
                if d < closest_dist:
                    if max_dist_px is None or d <= max_dist_px:
                        closest_dist = d
                        closest = item

            if closest is None:
                return None

            coord = center(closest["box"])
            final_coord = (coord[0] + align_px[0], coord[1] + align_px[1])
            self.device.tap(final_coord[0], final_coord[1], coord=True)
            logger.info("Pressed on closest '%s' near '%s'", target_text, base_text)
            if sleep:
                time.sleep(sleep)
            return True

        if wait:
            start = time.time()
            while time.time() - start < wait:
                if try_match():
                    return True
                time.sleep(0.5)
            return None

        for _ in range(3):
            if try_match():
                return True
            time.sleep(1)
        return None
