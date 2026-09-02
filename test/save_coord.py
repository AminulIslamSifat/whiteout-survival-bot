import os
import sys

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import cv2
import json
import time
import uvicorn
import numpy as np
from typing import Optional
from fastapi import FastAPI
from paddleocr import PaddleOCR
from pydantic import BaseModel

from core.core import req_ocr, req_temp_match, tap_on_text

from cmd_program.screen_action import take_screenshot




t1 = time.time()
data_dict = {}

data = req_ocr(save_result=True)
for d in data:
    box = d["box"]
    box[0], box[1], box[2], box[3] = box[0]/1080, box[1]/2460, box[2]/1080, box[3]/2460
    box = [round(b, 2) for b in box]

    print(f"{d['text']} ----- {d['score']} ---- {box}")
for i,d in enumerate(data):
    d["box"] = box
    data_dict[f"Home.Labyrinth.Challenge.Defeat.{i}"] = d


with open("Home.json", "w") as file:
    json.dump(data_dict, file, indent=4)

t2 = time.time()
print(t2-t1)