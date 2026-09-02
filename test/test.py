import os
import sys
import requests
import numpy as np
from rapidfuzz import fuzz

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))


import cv2
import time
from core.core import tap_on_templates_batch, req_text, req_temp_match, tap_on_text,tap_on_template, tap_on_closest_text
from cmd_program.screen_action import swipe_screen, take_screenshot, tap_screen

ocr_url = "http://127.0.0.1:8000/ocr"

def req_ocr(img_path=None, save_result=None, rois=None):
    payload = {
        "img_path": img_path,
        "save_result" : save_result,
        "rois": rois
    }

    data = requests.post(ocr_url, json=payload)
    data = data.json()
    if not data:
        return None
    
    result = data["results"]
    return result





def match_template(name, img = None, threshold=0.8, save_result=None, rois=None, parallel=None, session_id=None):
    template = cv2.imread(name)
    if template is None:
        return None
    print(1)

    img = cv2.imread(img)
    if len(img.shape) != len(template.shape):
        template = cv2.cvtColor(template, cv2.COLOR_BGR2GRAY)
        img = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

    h, w = template.shape[:2]
    img_h, img_w = img.shape[:2]

    # If no ROI → use full image
    if not rois:
        rois = [[0, 0, img_w, img_h]]

    matches = []
    print(1)

    for roi in rois:
        if roi is None:
            continue  # skip invalid ROI

        x1, y1, x2, y2 = roi
        roi_img = img[y1:y2, x1:x2]

        # skip empty regions
        print(2)
        if roi_img.size == 0:
            continue

        result = cv2.matchTemplate(roi_img, template, cv2.TM_CCOEFF_NORMED)
        _, max_value, _, max_loc = cv2.minMaxLoc(result)
        print(f"Best Match: {max_loc} ------ Score: {max_value}")

        locations = np.where(result >= threshold)
        locations = list(zip(locations[1], locations[0]))  # (x, y)

        for pt in locations:
            score = result[pt[1], pt[0]]

            # 🔥 map back to original image coords
            x_center = int( x1 + pt[0] + w // 2 )
            y_center = int( y1 + pt[1] + h // 2 )
            x1_abs = int(x1 + pt[0])
            y1_abs = int(y1 + pt[1])
            x2_abs = int(x1_abs + w)
            y2_abs = int(y1_abs + h)


            too_close = False

            for m in matches:
                if abs(m["box"][0] - x_center) < w and abs(m["box"][1] - y_center) < h:
                    too_close = True
                    if score > m["score"]:
                        m["box"] = [x1_abs, y1_abs, x2_abs, y2_abs]
                        m["score"] = float(score)
                    break

            if not too_close:
                matches.append({
                    "box": [x1_abs, y1_abs, x2_abs, y2_abs],
                    "score": float(score)
                })

    # 🖼 debug
    if save_result:
        debug_img = img.copy()
        for m in matches:
            cx1, cy1, cx2, cy2 = m["box"]
            cv2.rectangle(debug_img,
                          (cx1, cy1),
                          (cx2, cy2),
                          (0, 0, 255), 2)
        cv2.imwrite(f"test/debug/{time.time()}.png", debug_img)

    return matches






# print(os.cpu_count())

# for i in range(1):
#     t1 = time.time()
#     # for i in range(10):
#     #     swipe_screen(100, 1600, 1080, 1400)
#     #     time.sleep(0.5)
#     # for i in range(4):
#     #     swipe_screen(800, 1455, 100, 1868)
#     #     time.sleep(1)
#     #     status = tap_on_template("Home.Labyrinth1", wait=2, threshold=0.5)
#     #     if status:
#     #         break
#     r = req_ocr(rois=[
#         [
#             830,
#             2034,
#             1030,
#             2061
#         ]
#     ], save_result=True)
#     print(r)
#     t2 = time.time()
#     #img = take_screenshot(save=True)
#     print(t2 - t1)

