import os
import sys

import cv2
import time
import uuid
import json
import requests
from itertools import repeat
from pathlib import Path
from rapidfuzz import fuzz
from cmd_program.screen_action import tap_screen, take_screenshot, long_press, _get_screen_size
from concurrent.futures import ThreadPoolExecutor
from core.coord_utils import box_percent_to_pixel, box_pixel_to_percent, round_percentages, set_base_resolution
from core.logging_config import get_logger

logger = get_logger(__name__)





def _get_ocr_base_url() -> str:
    """Read OCR port from system/.ocr_port file, fall back to env var or 8000."""
    port_file = Path(__file__).resolve().parent.parent / "system" / ".ocr_port"
    try:
        port = int(port_file.read_text().strip())
    except (FileNotFoundError, ValueError):
        port = int(os.environ.get("OCR_PORT", "8000"))
    return f"http://127.0.0.1:{port}"

_ocr_base = _get_ocr_base_url()
ocr_url = f"{_ocr_base}/ocr"
template_matching_url = f"{_ocr_base}/template"
cache_clearing_url = f"{_ocr_base}/clear_cache"

OCR_HTTP_TIMEOUT_SEC = float(os.getenv("OCR_HTTP_TIMEOUT_SEC", "8"))
OCR_REPLAY_WAIT_SEC = float(os.getenv("OCR_REPLAY_WAIT_SEC", "35"))
OCR_REPLAY_BACKOFF_START_SEC = float(os.getenv("OCR_REPLAY_BACKOFF_START_SEC", "0.35"))
OCR_REPLAY_BACKOFF_MAX_SEC = float(os.getenv("OCR_REPLAY_BACKOFF_MAX_SEC", "2.5"))


#------------------- DataBase --------------------------#
text_area = {}
template_area = {}


def init_database():
    global text_area, template_area

    with open("references/icon/template_config.json") as f:
        template_area = json.load(f)

    # Load default text area
    files = [f for f in Path("references/TextArea").rglob("*.json") if f.is_file()]

    for file in files:
        try:
            with open(file, "r") as f:
                data = json.load(f)

                if isinstance(data, dict):
                    text_area.update(data)
                else:
                    logger.warning("Skipped non-dict file: %s", file)

        except Exception as e:
            logger.error("Error in %s - %s", file, e)
    
    # Load device-specific calibration (overrides defaults)
    _load_device_specific_calibration()


def _load_device_specific_calibration():
    """Load device-specific calibration data if available."""
    global text_area
    
    try:
        from cmd_program.screen_action import device_id
        
        if not device_id:
            return  # No device connected
        
        device_folder = Path(f"references/{device_id}")
        if not device_folder.exists():
            return  # No device-specific calibration yet
        
        files = [f for f in device_folder.glob("*.json") if f.is_file() and not f.name.startswith("_")]
        
        if not files:
            return  # No calibration files
        
        logger.info("📱 Loading device-specific calibration for %s...", device_id)
        
        for file in files:
            try:
                with open(file, "r") as f:
                    data = json.load(f)
                    if isinstance(data, dict):
                        old_count = len(text_area)
                        text_area.update(data)
                        new_items = len(text_area) - old_count
                        logger.info("   ✅ %s: +%d items", file.name, new_items)
            except Exception as e:
                logger.warning("   ⚠️ Error loading %s: %s", file.name, e)
        
        logger.info("   📊 Total text areas: %d", len(text_area))
        
    except Exception as e:
        logger.warning("   ⚠️ Could not load device calibration: %s", e)


def sync_resolution_with_device():
    """
    Sync the base resolution in coord_utils with the actual device resolution.
    Call this to update percentage-based coordinate calculations for the current device.
    """
    try:
        width, height = _get_screen_size()
        set_base_resolution(width, height)
        logger.info("✅ Coordinate system synchronized: %d×%d", width, height)
    except Exception as e:
        logger.warning("⚠️ Could not sync device resolution: %s", e)


def reload_device_calibration():
    """
    Reload device-specific calibration data.
    Useful when switching devices or after running recalibrate_device.py
    """
    global text_area
    
    logger.info("🔄 Reloading calibration...")
    text_area.clear()
    init_database()


def _convert_rois_percent_to_pixel(rois):
    """Convert percentage-based ROI coordinates to pixel coordinates for the OCR service."""
    if rois is None:
        return None

    def _is_percent_box(box):
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
        
        if len(rois) == 4 and isinstance(rois[0], (int, float)):
            return box_percent_to_pixel(rois) if _is_percent_box(rois) else rois
        
        if isinstance(rois[0], list):
            result = []
            for box in rois:
                if len(box) == 4:
                    result.append(box_percent_to_pixel(box) if _is_percent_box(box) else box)
                else:
                    result.append(box)
            return result
    
    return rois


def _convert_results_boxes_to_percent(results):
    if not results:
        return results

    converted = []
    for item in results:
        if not isinstance(item, dict):
            converted.append(item)
            continue

        converted_item = item.copy()
        box = converted_item.get("box")
        if isinstance(box, list) and len(box) == 4:
            converted_item["box"] = round_percentages(box_pixel_to_percent(box), decimals=2)
        converted.append(converted_item)

    return converted


def _post_json_with_replay(url, payload, request_name, wait_sec=OCR_REPLAY_WAIT_SEC):
    """Replay the same request payload until OCR service recovers or timeout is hit."""
    start = time.time()
    attempt = 0
    backoff = OCR_REPLAY_BACKOFF_START_SEC

    while True:
        attempt += 1
        try:
            response = requests.post(url, json=payload, timeout=OCR_HTTP_TIMEOUT_SEC)
            response.raise_for_status()
            data = response.json()

            if isinstance(data, dict) and data.get("success") is True:
                return data

            # OCR service reachable but still reports failure (e.g., restarting/recycling).
            err = data.get("error") if isinstance(data, dict) else "non-dict response"
            logger.warning("%s attempt %d returned failure: %s", request_name, attempt, err)

        except (requests.RequestException, ValueError) as e:
            logger.error("%s attempt %d failed: %s", request_name, attempt, e)

        elapsed = time.time() - start
        if elapsed >= wait_sec:
            logger.error("%s replay timed out after %.1fs", request_name, elapsed)
            return None

        time.sleep(backoff)
        backoff = min(backoff * 2, OCR_REPLAY_BACKOFF_MAX_SEC)






def req_ocr(img_path=None, save_result=None, rois=None, name=None, expected_text = None):
    import inspect
    # Log caller for debugging unnamed OCR requests
    if name is None:
        frame = inspect.currentframe().f_back
        caller_file = frame.f_code.co_filename.split("/")[-1]
        caller_line = frame.f_lineno
        caller_func = frame.f_code.co_name
        logger.warning("req_ocr called WITHOUT name from %s:%d in %s()", caller_file, caller_line, caller_func)
    else:
        logger.info("req_ocr: name=%s expected=%s", name, expected_text)

    # Convert percentage-based ROIs to pixels for the OCR service.
    rois = _convert_rois_percent_to_pixel(rois)
    
    payload = {
        "img_path": img_path,
        "save_result" : save_result,
        "rois": rois,
        "name" : name,
        "expected_text": expected_text
    }

    data = _post_json_with_replay(ocr_url, payload, "OCR request")
    if not data:
        return None
    
    # Return results with pixel coordinates directly (no conversion back to percentages)
    result = data["results"]
    return result





def req_temp_match(name, threshold=0.8, save_result=None, rois=None, parallel=None, session_id=None):
    # Convert percentage-based ROIs to pixels for the template service.
    rois = _convert_rois_percent_to_pixel(rois)
    
    payload = {
        "name" : name,
        "threshold" : threshold,
        "save_result": save_result,
        "rois": rois,
        "parallel" : parallel,
        "session_id" : session_id
    }
    
    data = _post_json_with_replay(template_matching_url, payload, "Template request")
    if not data:
        return None
    
    # Return results with pixel coordinates directly (no conversion back to percentages)
    results = data["results"]
    return results



def req_cache_clear(session_id):
    payload = {
        "session_id" : session_id
    }
    try:
        requests.post(cache_clearing_url, json=payload, timeout=OCR_HTTP_TIMEOUT_SEC)
    except requests.RequestException as e:
        logger.warning("Cache clear skipped (OCR unavailable): %s", e)


def tap_on_template(
    name, 
    threshold=None, 
    save_result=None, 
    wait=None, 
    sleep=0.3, 
    tap=True, 
    rois=None, 
    hold=None
    ):
    
    passed_threshold = threshold
    if name in template_area:
        if threshold == None:
            threshold = (template_area[name]["threshold"] or 0.8)
        rois = template_area.get(name,{}).get("box", None)
    
    if not threshold:
        threshold = 0.8
    # remember original threshold for time-based decay
    _orig_threshold = threshold

    def try_match():
        results = req_temp_match(
            name,
            threshold=threshold,
            save_result=save_result,
            rois=rois,
        )
        if not results:
            return None
        result = max(results, key=lambda x:x["score"])
        coord = result["box"]
        # Calculate center from pixel coordinates (result["box"] is in pixels)
        coord = ((coord[0]+coord[2])//2, (coord[1]+coord[3])//2)

        if coord and hold:
            # Pass coord=True since coordinates are already in pixels
            long_press(coord, duration=hold, coord=True)
            logger.info("Long pressed on - %s for %dms", name, hold)
        elif coord and tap:
            # Pass coord=True since coordinates are already in pixels
            tap_screen(coord, coord=True)
            logger.info("Pressed on - %s", name)
            if sleep:
                time.sleep(sleep)

        return bool(coord)

    # --- wait mode ---
    if wait:
        start = time.time()
        while time.time() - start < wait:
            elapsed = time.time() - start
            if passed_threshold == None:
                steps = int(elapsed / 0.4)
                threshold = _orig_threshold - steps * 0.05
                if threshold < 0.6:
                    threshold = 0.6

            if try_match():
                return True

        return None

    # --- retry mode ---
    for steps in range(3):
        if passed_threshold == None:
            threshold = _orig_threshold - steps * 0.05
            if threshold < 0.6:
                threshold = 0.6

        if try_match():
            return True
        else:
            logger.warning("No match found for - %s", name)
        time.sleep(1)

    return None



def tap_on_text(
    text, 
    img_path=None, 
    save_result=None, 
    rois=None, 
    wait=None, 
    sleep=0.3, 
    skip_ocr=False, 
    tap=True, 
    hold=None, 
    threshold=0.8,
    align=None
    ):

    name = text

    if align == None or not isinstance(align, list) or len(align) != 2:
        align = [0, 0]
    
    # Convert align from percentage offset to pixel offset
    screen_width, screen_height = _get_screen_size()
    align_px = (
        int((align[0] / 100) * screen_width),
        int((align[1] / 100) * screen_height)
    )
    
    threshold = threshold * 100

    def normalize_rois(box):
        if box is None:
            return None

        # Already list of lists [[x1,y1,x2,y2], [x1,y1,x2,y2]]
        if isinstance(box, list) and all(isinstance(b, list) and len(b) == 4 for b in box):
            return box  # ✅ multiple rois!!

        # Single flat box [x1,y1,x2,y2] → wrap it
        if isinstance(box, list) and len(box) == 4 and all(isinstance(v, (int, float)) for v in box):
            return [box]  # ✅

        logger.warning("Invalid ROI format: %s", box)
        return None
    

    def load_config(text, rois=None):
        if isinstance(text, str):
            text = [text]

        text_data = {}

        for t in text:
            if t in text_area:
                item = text_area[t].copy()
            else:
                item = {"text": t, "score": None, "box": None}

            if rois is not None:
                item["box"] = rois

            text_data[t] = item

        return text_data


    def try_match(texts, expand_px=0):
        for key, value in texts.items():
            target_text = value["text"]
            box = value["box"]
            if skip_ocr and box is not None:
                # Robust percent detection: treat box as percentages if all values are numeric and within 0..100
                def _is_percent_box(b):
                    try:
                        if not isinstance(b, (list, tuple)) or len(b) != 4:
                            return False
                        return all(isinstance(v, (int, float)) and 0 <= v <= 100 for v in b)
                    except Exception:
                        return False

                pixel_box = box_percent_to_pixel(box) if _is_percent_box(box) else box

                # Compute center first, then apply screen-alignment offset (align_px)
                center_x = (pixel_box[0] + pixel_box[2]) // 2
                center_y = (pixel_box[1] + pixel_box[3]) // 2
                coord = (center_x + align_px[0], center_y + align_px[1])

                if coord and hold:
                    # Coordinates are in pixels
                    long_press(coord, duration=hold, coord=True)
                elif coord and tap:
                    # Coordinates are in pixels
                    tap_screen(coord, coord=True)
                    logger.info("Pressed on %s (skip OCR", target_text)
                if sleep:
                    time.sleep(sleep)
                return True

            box = normalize_rois(box)
            res = req_ocr(img_path, save_result, rois=box, name=name, expected_text=target_text)

            if res is None:
                logger.warning("OCR failed")
                continue

            found = False
            for item in res:
                if item["text"].lower() == target_text.lower():

                    use_box = item.get("box")
                    if not use_box:
                        continue

                    # OCR results are in pixels
                    # Compute center first, then apply screen-alignment offset (align_px)
                    center_x = (use_box[0] + use_box[2]) // 2
                    center_y = (use_box[1] + use_box[3]) // 2
                    coord = (center_x + align_px[0], center_y + align_px[1])
                    if coord and hold:
                        # Coordinates are in pixels
                        long_press(coord, duration=hold, coord=True)
                    elif coord and tap:
                        # Coordinates are in pixels
                        tap_screen(coord, coord=True)
                        logger.info("Pressed on %s", item['text'])

                    if sleep:
                        time.sleep(sleep)

                    found = True
                    return True

            if not found:
                for item in res:
                    fuzzy_score = fuzz.ratio(item["text"].lower(), target_text.lower())
                    item["fuzzy_score"] = fuzzy_score
                sorted_res = sorted(res, key=lambda item: item["fuzzy_score"], reverse=True)
                sorted_res = [item for item in sorted_res if item["fuzzy_score"]>threshold]
                best_match = max(sorted_res, key=lambda item: item["fuzzy_score"], default=None)
                if best_match:
                    use_box = best_match.get("box")
                    if not use_box:
                        continue

                    # OCR results are in pixels
                    # Compute center first, then apply screen-alignment offset (align_px)
                    center_x = (use_box[0] + use_box[2]) // 2
                    center_y = (use_box[1] + use_box[3]) // 2
                    coord = (center_x + align_px[0], center_y + align_px[1])
                    if coord and hold:
                        # Coordinates are in pixels
                        long_press(coord, duration=hold, coord=True)
                    elif coord and tap:
                        # Coordinates are in pixels
                        tap_screen(coord, coord=True)
                        logger.info("Pressed on %s", best_match['text'])

                    if sleep:
                        time.sleep(sleep)
                    return True

            # If not found and expansion requested, try once with expanded ROI (pixels)
            if expand_px and box is not None:
                # normalize_rois produces [[x1,y1,x2,y2]] for a single box
                try:
                    inner = box[0] if isinstance(box, list) and len(box) > 0 else None
                    if inner and len(inner) == 4:
                        pixel_box = _convert_rois_percent_to_pixel(inner)
                        x1, y1, x2, y2 = pixel_box
                        ex = int(expand_px)
                        expanded = [max(0, x1 - ex), max(0, y1 - ex), x2 + ex, y2 + ex]
                        res2 = req_ocr(img_path, save_result, rois=[expanded], name=name, expected_text=target_text)
                        if res2:
                            # exact match
                            for item in res2:
                                if item["text"].lower() == target_text.lower():
                                    use_box = item.get("box")
                                    if not use_box:
                                        continue
                                    # OCR results are in pixels
                                    # Compute center then apply align offset
                                    center_x = (use_box[0] + use_box[2]) // 2
                                    center_y = (use_box[1] + use_box[3]) // 2
                                    coord = (center_x + align_px[0], center_y + align_px[1])
                                    if coord and hold:
                                        long_press(coord, duration=hold, coord=True)
                                    elif coord and tap:
                                        tap_screen(coord, coord=True)
                                        logger.info("Pressed on %s", item['text'])
                                    if sleep:
                                        time.sleep(sleep)
                                    return True

                            # fuzzy match on expanded region
                            for item in res2:
                                fuzzy_score = fuzz.ratio(item["text"].lower(), target_text.lower())
                                item["fuzzy_score"] = fuzzy_score
                            sorted_res2 = sorted(res2, key=lambda item: item["fuzzy_score"], reverse=True)
                            sorted_res2 = [item for item in sorted_res2 if item["fuzzy_score"] > threshold]
                            best_match2 = max(sorted_res2, key=lambda item: item["fuzzy_score"], default=None)
                            if best_match2:
                                use_box = best_match2.get("box")
                                if use_box:
                                    # OCR results are in pixels
                                    # Compute center then apply align offset
                                    center_x = (use_box[0] + use_box[2]) // 2
                                    center_y = (use_box[1] + use_box[3]) // 2
                                    coord = (center_x + align_px[0], center_y + align_px[1])
                                    if coord and hold:
                                        long_press(coord, duration=hold, coord=True)
                                    elif coord and tap:
                                        tap_screen(coord, coord=True)
                                        logger.info("Pressed on %s", best_match2['text'])
                                    if sleep:
                                        time.sleep(sleep)
                                    return True
                except Exception:
                    pass

        return False


    # ✅ FIXED POSITION (outside try_match)
    texts = load_config(text, rois=rois)

    if not texts:
        logger.warning("No text to press on")
        return None

    if wait:
        start = time.time()

        while time.time() - start < wait:
            elapsed = time.time() - start
            steps = int(elapsed / 0.4)
            expand_px = steps * 5 if steps > 0 else 0
            if try_match(texts, expand_px=expand_px):
                return True
            time.sleep(0.1)

        logger.warning("No match found for the text - %s", texts[text]['text'])
        return None

    for i in range(3):
        # increase expansion by 5px each retry (5, 10, 15)
        expand_px = (i + 1) * 5
        if try_match(texts, expand_px=expand_px):
            return True
        time.sleep(1)

    logger.warning("No match found for the text - %s", texts[text]["text"])
    return None




def req_text(names=None, img_path=None, rois=None, save_result=False, coord=None):
    import inspect

    # If no name is provided, send OCR for the caller-supplied ROI(s), or full page if none were given.
    if not names:
        frame = inspect.currentframe().f_back
        caller_file = frame.f_code.co_filename.split("/")[-1]
        caller_line = frame.f_lineno
        caller_func = frame.f_code.co_name
        logger.warning("req_text() called WITHOUT names from %s:%d in %s() — doing full_page scan", caller_file, caller_line, caller_func)
        res = req_ocr(img_path, save_result, rois=rois, name="full_page")
        if res is None:
            logger.warning("OCR failed")
            return None
        texts = []
        for t in res:
            texts.append([t['text'], t['box']])
        return texts

    def load_config(names, rois=None):
        if isinstance(names, str):
            names = [names]

        # Determine boxes to use for each name.
        names_boxes = []
        title = ", ".join(names) + (", " if len(names) == 1 else "")

        # If rois provided, handle three possibilities:
        # 1) rois is a single box [x1,y1,x2,y2] -> apply to all names
        # 2) rois is a list of boxes [[...], [...]] -> map by index (reuse last if short)
        # 3) rois is None -> use text_area boxes or full screen fallback
        if rois is not None:
            # list of boxes ([[...], [...]])
            if isinstance(rois, list) and len(rois) > 0 and isinstance(rois[0], (list, tuple)):
                for i, name in enumerate(names):
                    if i < len(rois):
                        names_boxes.append(rois[i])
                    else:
                        names_boxes.append(text_area.get(name, {}).get("box", [0, 0, 100, 100]))
                return names_boxes, title

            # single box [x1,y1,x2,y2]
            if isinstance(rois, list) and len(rois) == 4 and all(isinstance(v, (int, float)) for v in rois):
                return [rois for _ in names], title

            # unexpected format -> ignore rois

        for name in names:
            if name in text_area:
                names_boxes.append(text_area[name].get("box", [0, 0, 100, 100]))
            else:
                names_boxes.append([0, 0, 100, 100])

        return names_boxes, title

    boxes, title = load_config(names, rois)

    if not boxes:
        logger.warning("No location found")
        return None
    
    res = req_ocr(img_path, save_result, rois=boxes, name=title)

    if res is None:
        logger.warning("OCR failed")
        return None

    texts = []
    for t in res:
        texts.append([t['text'], t['box']])
    return texts




def tap_on_templates_batch(
    names,
    thresholds=None,
    save_results=None,
    wait=None,
    tap=True,
    sleep=None,
    rois=None,
    parallel=False,
    max_workers=8,
):
    n = len(names)

    if n == 0:
        return False

    passed_threshold = thresholds

    thresholds = thresholds or [0.8] * n
    save_results = save_results or [None] * n
    if isinstance(tap, bool):
        tap = [tap] * n
    # remember original thresholds for time-based decay
    _orig_thresholds = list(thresholds)

    # ✅ Fix 1: return (i, result) tuple so index is never lost
    def match_one(i, session_id):
        results = req_temp_match(
            names[i],
            threshold=thresholds[i], 
            save_result=save_results[i], 
            rois=rois,
            parallel=True,
            session_id = session_id
        )
        if results:
            best = max(results, key=lambda x: x["score"])
            return (i, best)   # always a clean (index, dict) pair
        return None

    def run_batch(session_id):
        if parallel and n > 1:
            workers = max(1, min(max_workers, n))
            with ThreadPoolExecutor(max_workers=workers) as ex:
                # session_id is a string; repeat it so each worker gets the full id.
                raw = list(ex.map(match_one, range(n), repeat(session_id)))
        else:
            raw = [match_one(i, session_id) for i in range(n)]
        return [r for r in raw if r is not None]  # filter out None

    def pick_best_and_tap(cleaned_results):
        # cleaned_results is a list of (i, result_dict)
        i, best = max(cleaned_results, key=lambda x: x[1]["score"])
        box = best["box"]  # ✅ Fix 2: always access like this, no [0] indexing
        coord_xy = ((box[0] + box[2]) // 2, (box[1] + box[3]) // 2)
        if tap[i]:
            # Coordinates from template matching are in pixels
            tap_screen(coord_xy, coord=True)
            logger.info("Pressed on %s", names[i])
            if sleep:
                time.sleep(sleep)
        return True

    # --- wait mode ---
    if wait:
        session_id = str(uuid.uuid4())
        start = time.time()
        try:
            while time.time() - start < wait:
                elapsed = time.time() - start
                if passed_threshold == None:
                    steps = int(elapsed / 0.4)
                    thresholds = [max(orig - steps * 0.05, 0.6) for orig in _orig_thresholds]

                cleaned = run_batch(session_id)
                if cleaned:
                    return pick_best_and_tap(cleaned)
        finally:
            if parallel:
                req_cache_clear(session_id)
        return False

    # --- retry mode ---
    start = time.time()
    for _ in range(3):
        session_id = str(uuid.uuid4())

        try:
            elapsed = time.time() - start
            if passed_threshold == None:
                steps = int(elapsed / 0.4)
                thresholds = [max(orig - steps * 0.05, 0.6) for orig in _orig_thresholds]

            cleaned = run_batch(session_id)
        finally:
            if parallel:
                req_cache_clear(session_id)

        if cleaned:
            return pick_best_and_tap(cleaned)

    return False



def tap_on_closest_text(
        base_text, 
        target_text, 
        img=None, 
        rois=None, 
        threshold=0.8, 
        save_result=None, 
        wait=None, 
        sleep=0.3, 
        align=None,
        maximum_distance=None
    ):
    threshold = threshold * 100 if threshold else 80
    
    # Convert align from percentage offset to pixel offset
    if align == None or not isinstance(align, list) or len(align) != 2:
        align = [0, 0]
    screen_width, screen_height = _get_screen_size()
    align_px = (
        int((align[0] / 100) * screen_width),
        int((align[1] / 100) * screen_height)
    )
    
    def center(box):
        x1, y1, x2, y2 = box
        return ((x1 + x2) // 2, (y1 + y2) // 2)
    
    def distance(c1, c2):
        return ((c1[0]-c2[0])**2 + (c1[1]-c2[1])**2)**0.5

    # apply_align removed; align is converted at function start
    
    def try_match():
        try:
            res = req_ocr(rois=rois, save_result=save_result)
            if not res:
                return None

            for item in res:
                fuzzy_score = fuzz.ratio(item["text"].lower(), base_text.lower())
                item["fuzzy_score"] = fuzzy_score
                del item["score"]

            sorted_res = sorted(res, key=lambda item: item["fuzzy_score"], reverse=True)
            sorted_res = [item for item in sorted_res if item["fuzzy_score"]>threshold]
            best_match = max(sorted_res, key=lambda item: item["fuzzy_score"], default=None)
            if not best_match:
                return None

            target_boxes = []

            base_center = center(best_match["box"])
            base_bottom = best_match["box"][3]

            for item in res:
                target_center = center(item["box"])
                if fuzz.ratio(item["text"].lower(), target_text.lower()) > threshold and target_center[1] > base_bottom:
                    del item["fuzzy_score"]
                    target_boxes.append(item)

            if not target_boxes:
                return None

            closest_target = min(
                target_boxes,
                key = lambda g: distance(center(g["box"]), base_center)        
            )

            if maximum_distance:
                if distance(center(closest_target["box"]), base_center) > maximum_distance:
                    return None
            
            target_center_raw = center(closest_target["box"])
            target_center = (target_center_raw[0] + align_px[0], target_center_raw[1] + align_px[1])
            if target_center:
                # target_center computed from OCR boxes (pixels)
                tap_screen(target_center, coord=True)
                if sleep:
                    time.sleep(sleep)
                logger.debug("Distance: %.2f", distance(center(closest_target['box']), base_center))
                return True
            else:
                return None
        except Exception as e:
            logger.error("Reading Error - %s", e)
            return None
        
    if wait:
        start = time.time()
        while((time.time() - start) < wait):
            if try_match():
                logger.info("Pressed on closest %s of %s", target_text, base_text)
                return True
        logger.warning("No match found")
        return False
            
    for _ in range(3):
        if try_match():
            logger.info("Pressed on closest %s of %s", target_text, base_text)
            return True
        else:
            logger.warning("No match found")
        time.sleep(1)

    return False




init_database()