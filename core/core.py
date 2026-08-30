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
from cmd_program.screen_action import tap_screen, take_screenshot, long_press
from concurrent.futures import ThreadPoolExecutor
from core.coord_utils import box_percent_to_pixel





_OCR_PORT = os.getenv("OCR_PORT", "8000")
ocr_url = f"http://127.0.0.1:{_OCR_PORT}/ocr"
template_matching_url = f"http://127.0.0.1:{_OCR_PORT}/template"
cache_clearing_url = f"http://127.0.0.1:{_OCR_PORT}/clear_cache"

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

    files = [f for f in Path("references/TextArea").rglob("*.json") if f.is_file()]

    for file in files:
        try:
            with open(file, "r") as f:
                data = json.load(f)

                if isinstance(data, dict):
                    text_area.update(data)
                else:
                    print(f"Skipped non-dict file: {file}")

        except Exception as e:
            print(f"Error in {file} - {e}")


def _convert_rois_percent_to_pixel(rois):
    """Convert ROI coordinates from percentages to pixels.
    
    Handles formats:
    - None: returns None
    - Single box (4 elements): converts to pixel coordinates
    - List of boxes: converts each box
    """
    if rois is None:
        return None
    
    if isinstance(rois, list):
        if len(rois) == 0:
            return rois
        
        # Check if it's a single box [x1, y1, x2, y2]
        if len(rois) == 4 and isinstance(rois[0], (int, float)):
            # Check if any value is > 100 (likely already pixels)
            if any(v > 100 for v in rois):
                return rois
            # Convert from percentage to pixels
            return box_percent_to_pixel(rois)
        
        # Check if it's a list of boxes [[x1,y1,x2,y2], ...]
        if isinstance(rois[0], list):
            result = []
            for box in rois:
                if len(box) == 4:
                    # Check if already in pixels
                    if any(v > 100 for v in box):
                        result.append(box)
                    else:
                        result.append(box_percent_to_pixel(box))
                else:
                    result.append(box)
            return result
    
    return rois


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
            print(f"{request_name} attempt {attempt} returned failure: {err}")

        except (requests.RequestException, ValueError) as e:
            print(f"{request_name} attempt {attempt} failed: {e}")

        elapsed = time.time() - start
        if elapsed >= wait_sec:
            print(f"{request_name} replay timed out after {elapsed:.1f}s")
            return None

        time.sleep(backoff)
        backoff = min(backoff * 2, OCR_REPLAY_BACKOFF_MAX_SEC)






def req_ocr(img_path=None, save_result=None, rois=None, name=None, expected_text = None,
            read_kind=None, decision_id=None):
    # read_kind="value": this read feeds numeric state (power, levels, timers) —
    # the server gives it zero-item fallback + burn-in shadow-compare. Tag at
    # the CALLING site, never here. decision_id groups retried reads into one
    # decision for burn-in rate math; callers that retry pass a shared one.
    # Convert percentage-based ROIs to pixels
    rois = _convert_rois_percent_to_pixel(rois)

    payload = {
        "img_path": img_path,
        "save_result" : save_result,
        "rois": rois,
        "name" : name,
        "expected_text": expected_text,
        "read_kind": read_kind,
        "decision_id": decision_id or uuid.uuid4().hex
    }

    data = _post_json_with_replay(ocr_url, payload, "OCR request")
    if not data:
        return None
    
    result = data["results"]
    return result





def req_temp_match(name, threshold=0.8, save_result=None, rois=None, parallel=None, session_id=None):
    # Convert percentage-based ROIs to pixels
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
    
    results = data["results"]
    return results



def req_cache_clear(session_id):
    payload = {
        "session_id" : session_id
    }
    try:
        requests.post(cache_clearing_url, json=payload, timeout=OCR_HTTP_TIMEOUT_SEC)
    except requests.RequestException as e:
        print(f"Cache clear skipped (OCR unavailable): {e}")


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
        coord = ((coord[0]+coord[2])//2, (coord[1]+coord[3])//2)

        if coord and hold:
            long_press(coord, duration=hold)
        elif coord and tap:
            tap_screen(coord)

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
    start = time.time()
    for _ in range(3):
        elapsed = time.time() - start
        if passed_threshold == None:
            steps = int(elapsed / 0.4)
            threshold = _orig_threshold - steps * 0.05
            if threshold < 0.6:
                threshold = 0.6

        if try_match():
            print(f"Pressed on - {name}")
            return True
        else:
            print(f"No match found for - {name}")
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
    threshold = threshold * 100

    def normalize_rois(box):
        if box is None:
            return None

        # already correct format [[...]]
        if isinstance(box, list) and len(box) == 1 and isinstance(box[0], list):
            return box

        # single box → wrap it
        if isinstance(box, list) and len(box) == 4:
            return [box]

        print("Invalid ROI format:", box)
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
                coord = (
                    (box[0] + box[2] + align[0]) // 2,
                    (box[1] + box[3] + align[1]) // 2
                )

                if coord and hold:
                    long_press(coord, duration=hold)
                elif coord and tap:
                    tap_screen(coord)
                    print(f"Pressed on {target_text}, Skipped OCR")
                if sleep:
                    time.sleep(sleep)
                return True

            box = normalize_rois(box)
            res = req_ocr(img_path, save_result, rois=box, name=name, expected_text=target_text,
                          decision_id=decision_id)

            if res is None:
                print("OCR failed")
                continue

            found = False
            for item in res:
                if item["text"].lower() == target_text.lower():

                    use_box = item.get("box")
                    if not use_box:
                        continue

                    coord = (
                        (use_box[0] + use_box[2] + align[0]) // 2,
                        (use_box[1] + use_box[3] + align[1]) // 2
                    )
                    if coord and hold:
                        long_press(coord, duration=hold)
                    elif coord and tap:
                        tap_screen(coord)
                        print(f"Pressed on {item['text']}")

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

                    coord = (
                        (use_box[0] + use_box[2] + align[0]) // 2,
                        (use_box[1] + use_box[3] + align[1]) // 2
                    )
                    if coord and hold:
                        long_press(coord, duration=hold)
                    elif coord and tap:
                        tap_screen(coord)
                        print(f"Pressed on {best_match['text']}")

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
                        res2 = req_ocr(img_path, save_result, rois=[expanded], name=name, expected_text=target_text,
                                       decision_id=decision_id)
                        if res2:
                            # exact match
                            for item in res2:
                                if item["text"].lower() == target_text.lower():
                                    use_box = item.get("box")
                                    if not use_box:
                                        continue
                                    coord = (
                                        (use_box[0] + use_box[2] + align[0]) // 2,
                                        (use_box[1] + use_box[3] + align[1]) // 2
                                    )
                                    if coord and hold:
                                        long_press(coord, duration=hold)
                                    elif coord and tap:
                                        tap_screen(coord)
                                        print(f"Pressed on {item['text']}")
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
                                    coord = (
                                        (use_box[0] + use_box[2] + align[0]) // 2,
                                        (use_box[1] + use_box[3] + align[1]) // 2
                                    )
                                    if coord and hold:
                                        long_press(coord, duration=hold)
                                    elif coord and tap:
                                        tap_screen(coord)
                                        print(f"Pressed on {best_match2['text']}")
                                    if sleep:
                                        time.sleep(sleep)
                                    return True
                except Exception:
                    pass

        return False


    # ✅ FIXED POSITION (outside try_match)
    # One decision id for the whole tap_on_text invocation: every retried read
    # below shares it, so burn-in rates count decisions, not attempts.
    decision_id = uuid.uuid4().hex
    texts = load_config(text, rois=rois)

    if not texts:
        print("No text to press on")
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

        print(f"No match found for the text - {texts[text]['text']}")
        return None

    for i in range(3):
        # increase expansion by 5px each retry (5, 10, 15)
        expand_px = (i + 1) * 5
        if try_match(texts, expand_px=expand_px):
            return True
        time.sleep(1)

    print(f"No match found for the text - {texts[text]["text"]}")
    return None




def req_text(names=None, img_path=None, rois=None, save_result=False, coord=None,
             read_kind=None):
    # read_kind is passed through by callers whose result feeds numeric state.
    decision_id = uuid.uuid4().hex

    # If no name is provided, send full page OCR
    if not names:
        res = req_ocr(img_path, save_result, rois=None, name="full_page",
                      read_kind=read_kind, decision_id=decision_id)
        if res is None:
            print("OCR failed")
            return None
        texts = []
        for t in res:
            texts.append([t['text'], t['box']])
        return texts

    def load_config(names, rois=None):
        if isinstance(names, str):
            names = [names]

        names_boxes = []
        title = ""

        for name in names:
            if name in text_area:
                title += name + ", "
                box = text_area[name]["box"]
            else:
                box = [0, 0, 100, 100]  # Full screen in percentage (100% width, 100% height)

            if rois is not None:
                names_boxes = rois

            names_boxes.append(box)

        return names_boxes, title

    boxes, title = load_config(names, rois)

    if not boxes:
        print("No location found")
        return None
    
    res = req_ocr(img_path, save_result, rois=boxes, name=title,
                  read_kind=read_kind, decision_id=decision_id)

    if res is None:
        print("OCR failed")
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
            tap_screen(coord_xy)
            print(f"Pressed on {names[i]}")
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
    
    def center(box):
        x1, y1, x2, y2 = box
        return ((x1 + x2) // 2, (y1 + y2) // 2)
    
    def distance(c1, c2):
        return ((c1[0]-c2[0])**2 + (c1[1]-c2[1])**2)**0.5

    def apply_align(point):
        if not align:
            return point
        return (point[0] + align[0], point[1] + align[1])
    
    decision_id = uuid.uuid4().hex

    def try_match():
        try:
            res = req_ocr(rois=rois, save_result=save_result, decision_id=decision_id)
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
            
            target_center = apply_align(center(closest_target["box"]))
            if target_center:
                tap_screen(target_center)
                if sleep:
                    time.sleep(sleep)
                print(f"Distance: {distance(center(closest_target['box']), base_center)}")
                return True
            else:
                return None
        except Exception as e:
            print(f"Reading Error - {e}")
            return None
        
    if wait:
        start = time.time()
        while((time.time() - start) < wait):
            if try_match():
                print(f"Pressed on closent {target_text} of {base_text}")
                return True
        print("No match found")
        return False
            
    for _ in range(3):
        if try_match():
            print(f"Pressed on closent {target_text} of {base_text}")
            return True
        else:
            print("No match found")
        time.sleep(1)

    return False




init_database()