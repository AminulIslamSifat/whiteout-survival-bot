import os
import sys

workspace_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if workspace_root not in sys.path:
    sys.path.insert(0, workspace_root)
elif sys.path[0] != workspace_root:
    sys.path.remove(workspace_root)
    sys.path.insert(0, workspace_root)

# Disable remote model source probing during PaddleOCR init to avoid startup delays.
os.environ.setdefault("PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK", "True")


# --- AGGRESSIVE GARBAGE COLLECTION FLAGS ---
# These MUST be set before importing paddle or paddleocr to affect the C++ backend
os.environ["FLAGS_eager_delete_tensor_gb"] = "0.0"
os.environ["FLAGS_fast_eager_deletion_mode"] = "True"
os.environ["FLAGS_allocator_strategy"] = "naive_best_fit"
# -------------------------------------------


import cv2
import json
import time
import gc
import ctypes
import paddle           #Important for paddleocr 2.10.0
import uvicorn
import threading
import numpy as np
from pathlib import Path
from typing import Optional
from fastapi import FastAPI
from pydantic import BaseModel
from paddleocr import PaddleOCR
from rich.panel import Panel
from rich.prompt import Prompt
from rich.console import Console
from concurrent.futures import ThreadPoolExecutor
from cmd_program.screen_action import take_screenshot
from cmd_program.screen_stream import screen_capture as stream_screen_capture
from cmd_program.screen_stream import start_screen_stream, setup_v4l2loopback
from cmd_program.resolution_utils import get_stream_resolution, reset_resolution_cache
import paddleocr

from core.logging_config import get_logger

logger = get_logger(__name__)



#Printing the version of paddleocr
logger.info("PaddleOCR Version: %s", paddleocr.__version__)
logger.info("PaddlePaddle Version: %s", paddle.__version__)

#Disabling logging from the paddleocr
import logging
logging.getLogger("ppocr").setLevel(logging.ERROR)
logging.getLogger("uvicorn").setLevel(logging.WARNING)
logging.getLogger("uvicorn.access").setLevel(logging.ERROR)


#------------------- Data Models ---------------------------------#

#input schema for fastapi
class OCRRequest(BaseModel):
    img_path: Optional[str] = None
    save_result: Optional[bool] = False
    save_frame: Optional[bool] = False
    rois: Optional[list[list[int]]] = None
    name: Optional[str] = None
    expected_text: Optional[str] = None


class TemplateMatchRequest(BaseModel):
    name: str
    threshold: Optional[float] = None
    save_result: Optional[bool] = False
    rois: Optional[list[list[int]]] = None
    parallel: Optional[bool] = None
    session_id: Optional[str] = None


class ClearCacheRequest(BaseModel):
    session_id: str


#------------------- Configuration ------------------------------#
SCREENSHOT_TTL = 0.1
CPU_THREADS = min(os.cpu_count() or 1, 4)
TEMPLATE_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "references", "icon"))
RAM_CAP_GB = float(os.getenv("OCR_RAM_CAP_GB", "3.0"))
RAM_CAP_BYTES = int(RAM_CAP_GB * 1024 * 1024 * 1024)

# Dynamic stream resolution - will be initialized at startup
STREAM_WIDTH = 1080   # Default fallback
STREAM_HEIGHT = 2456  # Default fallback

STREAM_TIMEOUT_S = 2.0
STREAM_RETRY_COOLDOWN_S = 3.0
STREAM_SUDO_RETRY_COOLDOWN_S = 120.0
STREAM_VIDEO_DEVICE = os.getenv("OCR_STREAM_DEVICE", "/dev/video10")

# Keep oneDNN primitive cache bounded on CPU workloads.
os.environ.setdefault("ONEDNN_PRIMITIVE_CACHE_CAPACITY", "10")


#---------------------- Globals ---------------------------------#
app = FastAPI()
console = Console()
_template_cache = {}
_cache = {}
_cache_lock = threading.Lock()
_capture_lock = threading.Lock()
_ocr_lock = threading.Lock()
_ocr_init_lock = threading.Lock()
_ram_guard_lock = threading.Lock()
_stream_state_lock = threading.Lock()
_stream_ready = False
_stream_retry_after = 0.0
_stream_sudo_retry_after = 0.0
_preferred_screen_capture_tool = None



def take_preferred_screen_capture_tool():
    global _preferred_screen_capture_tool
    tools = ["adb", "scrcpy"]
    
    # Check for environment variable first for non-interactive use
    env_choice = os.getenv("OCR_CAPTURE_TOOL")
    if env_choice in tools:
        _preferred_screen_capture_tool = env_choice
        console.print(f"[bold green]✅ Using Capture Tool from Env:[/bold green] [bold white]{_preferred_screen_capture_tool.upper()}[/bold white]")
        return

    console.print(Panel.fit(
        "[bold cyan]1.[/bold cyan] ADB\n[bold cyan]2.[/bold cyan] SCRCPY",
        title="[bold magenta]🎮 Select Screen Capture Tool[/bold magenta]",
        border_style="bright_blue"
    ))
    
    choice = Prompt.ask("[bold yellow]Enter your choice[/bold yellow]")
    
    try:
        choice = int(choice) - 1
        _preferred_screen_capture_tool = tools[choice]
        console.print(f"\n[bold green]✅ Selected:[/bold green] [bold white]{_preferred_screen_capture_tool.upper()}[/bold white]\n")
    except Exception as e:
        console.print(f"[bold red]❌ Invalid choice — {e}, Try Again[/bold red]")
        take_preferred_screen_capture_tool()



def _save_frame_to_cache(frame):
    cache_dir = Path("cache")
    cache_dir.mkdir(parents=True, exist_ok=True)
    save_path = cache_dir / f"frame_{int(time.time() * 1000)}.png"
    ok = cv2.imwrite(str(save_path), frame)
    if ok:
        logger.debug("Saved frame to %s", save_path)


def _normalize_frame_resolution(frame):
    if frame is None:
        return None

    h, w = frame.shape[:2]
    if w == STREAM_WIDTH and h == STREAM_HEIGHT:
        return frame

    return cv2.resize(frame, (STREAM_WIDTH, STREAM_HEIGHT), interpolation=cv2.INTER_LINEAR)


def _try_start_stream():
    global _stream_ready, _stream_retry_after, _stream_sudo_retry_after
    now = time.time()

    with _stream_state_lock:
        if _stream_ready:
            return True
        if now < _stream_retry_after:
            return False

    # If loopback device already exists, skip modprobe and avoid unnecessary sudo prompts.
    loopback_ready = Path(STREAM_VIDEO_DEVICE).exists()
    if not loopback_ready:
        # First try non-interactive sudo. If user has a valid sudo ticket, no prompt is needed.
        loopback_ready = setup_v4l2loopback(password=None)

    if not loopback_ready:
        # Cannot prompt for password interactively without a TTY (e.g. dashboard subprocess)
        if not sys.stdin.isatty():
            logger.warning("Stream capture unavailable: v4l2loopback needs sudo but no TTY for password prompt")
            with _stream_state_lock:
                _stream_retry_after = now + STREAM_RETRY_COOLDOWN_S
            return False

        with _stream_state_lock:
            if now < _stream_sudo_retry_after:
                return False

        console.print(Panel.fit(
            "[dim]Type your sudo password and press Enter.[/dim]",
            title="[bold magenta]🔑 Sudo Authentication Required[/bold magenta]",
            border_style="yellow"
        ))
        sudo_pass = Prompt.ask("[bold yellow]  Enter sudo password[/bold yellow]", password=False)
        loopback_ready = setup_v4l2loopback(password=sudo_pass)

        if not loopback_ready:
            with _stream_state_lock:
                _stream_ready = False
                _stream_retry_after = now + STREAM_RETRY_COOLDOWN_S
                _stream_sudo_retry_after = now + STREAM_SUDO_RETRY_COOLDOWN_S
            return False

        with _stream_state_lock:
            _stream_sudo_retry_after = 0.0

    with _stream_state_lock:
        if _stream_ready:
            return True
        if time.time() < _stream_retry_after:
            return False

        try:
            start_screen_stream(
                video_device=STREAM_VIDEO_DEVICE,
                width=STREAM_WIDTH,
                height=STREAM_HEIGHT,
            )
            _stream_ready = True
            return True
        except Exception as e:
            logger.warning("screen_stream start failed, falling back to adb: %s", e)
            _stream_ready = False
            _stream_retry_after = now + STREAM_RETRY_COOLDOWN_S
            return False


def _get_process_rss_bytes():
    """Read current process RSS in bytes from /proc for low overhead."""
    try:
        with open("/proc/self/status", "r", encoding="utf-8") as f:
            for line in f:
                if line.startswith("VmRSS:"):
                    parts = line.split()
                    # VmRSS is reported as kB.
                    return int(parts[1]) * 1024
    except Exception:
        pass
    return 0


def _trim_allocator():
    """Attempt to return free heap pages to OS on glibc systems."""
    try:
        libc = ctypes.CDLL("libc.so.6")
        libc.malloc_trim(0)
    except Exception:
        pass


def _enforce_ram_cap(context="runtime"):
    """Try to keep process RSS under configured cap by recycling OCR engine."""
    rss_before = _get_process_rss_bytes()
    if rss_before <= RAM_CAP_BYTES:
        return

    with _ram_guard_lock:
        # Re-check after lock to avoid duplicate recycle work.
        rss_before = _get_process_rss_bytes()
        if rss_before <= RAM_CAP_BYTES:
            return

        logger.warning(
            "RAM guard triggered in %s: rss=%.2fGB cap=%.2fGB. Recycling OCR engine...",
            context, rss_before / (1024**3), RAM_CAP_GB,
        )

        _reinitialize_ocr_engine()
        gc.collect()
        _trim_allocator()

        rss_after = _get_process_rss_bytes()
        if rss_after > RAM_CAP_BYTES:
            raise MemoryError(
                f"RAM cap exceeded after recycle in {context}. "
                f"rss={rss_after / (1024**3):.2f}GB cap={RAM_CAP_GB:.2f}GB"
            )


def _build_ocr_engine():
    paddle.set_device("cpu")
    return PaddleOCR(
        use_angle_cls=False,
        lang='en',
        use_gpu=False,
        det_limit_side_len=1024,
        cpu_threads=CPU_THREADS,
        ir_optim=True,
        layout=False,
        table=False,
        formula=False,
    )


def _capture_frame(img_path=None, save_frame=False):
    global _stream_ready, _stream_retry_after

    if img_path:
        img = cv2.imread(img_path)
        img = _normalize_frame_resolution(img)
        if save_frame and img is not None:
            _save_frame_to_cache(img)
        return img

    img = None
    if _preferred_screen_capture_tool == "adb":
        with _capture_lock:
            img = take_screenshot()
            img = _normalize_frame_resolution(img)
        if img is not None:
            return img 
        else:
            return None

    if _try_start_stream():
        try:
            img = stream_screen_capture(wait=True, timeout=STREAM_TIMEOUT_S)
            img = _normalize_frame_resolution(img)
            if img is None:
                raise RuntimeError("screen_stream returned no frame")
        except Exception as e:
            logger.warning("screen_stream capture failed, using adb: %s", e)
            with _stream_state_lock:
                _stream_ready = False
                _stream_retry_after = time.time() + STREAM_RETRY_COOLDOWN_S
            img = None

    if img is None:
        # ADB screencap can become unstable under concurrent calls.
        with _capture_lock:
            img = take_screenshot()
        img = _normalize_frame_resolution(img)

    if save_frame and img is not None:
        _save_frame_to_cache(img)

    return img


def _reinitialize_ocr_engine():
    global ocr
    with _ocr_init_lock:
        ocr = _build_ocr_engine()


def _call_ocr_with_recovery(image):
    global ocr
    with _ocr_lock:
        try:
            return ocr.ocr(image, cls=False)
        except RuntimeError as e:
            # Paddle sometimes throws this when predictor state gets unstable.
            if "could not execute a primitive" not in str(e):
                raise
            logger.warning("OCR primitive execution failed. Reinitializing OCR engine and retrying once...")
            _reinitialize_ocr_engine()
            return ocr.ocr(image, cls=False)


def _get_cached_image(session_id):
    with _cache_lock:
        if session_id in _cache:
            return _cache[session_id]

        img = _capture_frame()
        _cache[session_id] = img
        return img


#----------------------- Functions -------------------------------#

def _init_stream_resolution():
    """
    Initialize dynamic stream resolution from the connected device.
    Applies scrcpy quirk correction (6-pixel reduction in larger value).
    Falls back to defaults if detection fails.
    """
    global STREAM_WIDTH, STREAM_HEIGHT
    
    try:
        from cmd_program.screen_action import device_id
        if device_id:
            width, height = get_stream_resolution(device_id, apply_scrcpy_quirk=True)
            STREAM_WIDTH = width
            STREAM_HEIGHT = height
            console.print(f"[bold green]✅ Dynamic Stream Resolution:[/bold green] {STREAM_WIDTH}×{STREAM_HEIGHT}")
            return
    except Exception as e:
        console.print(f"[bold yellow]⚠️ Could not detect stream resolution:[/bold yellow] {e}")
    
    console.print(f"[bold yellow]⚠️ Using fallback resolution:[/bold yellow] {STREAM_WIDTH}×{STREAM_HEIGHT}")


def init_services():
    global ocr, _template_cache

    #initializeng the ocr once for all
    # ocr = PaddleOCR(
    #         use_doc_orientation_classify=False,
    #         use_doc_unwarping=False,
    #         use_textline_orientation=False
    #     )
    
    ocr = _build_ocr_engine()

    root_dir = Path(TEMPLATE_PATH)
    logger.debug("root_dir: %s", root_dir)
    for file_path in root_dir.rglob("*.png"):
        if file_path.is_file():
            fn = os.path.splitext(file_path.name)[0]
            img = cv2.imread(file_path)
            if img is not None:
                _template_cache[fn] = img
    


def clamp_roi(roi, width, height):
    x1, y1, x2, y2 = roi

    # clamp values inside image bounds
    x1 = max(0, min(x1, width - 1))
    y1 = max(0, min(y1, height - 1))
    x2 = max(0, min(x2, width))
    y2 = max(0, min(y2, height))

    # ensure valid rectangle
    if x2 <= x1 or y2 <= y1:
        return None

    return [x1, y1, x2, y2]



def match_template(
        name, 
        img = None, 
        threshold=0.8, 
        save_result=None, 
        rois=None, 
        parallel=None, 
        session_id=None
    ):
    if name not in _template_cache:
        template = cv2.imread(name)
    else:
        template = _template_cache[name]

    if not parallel:
        try:
            img = _capture_frame()
        except Exception as e:
            raise RuntimeError(f"Error loading image - {e}")
    else:
        img = _get_cached_image(session_id)

    if template is None:
        return None

    if len(img.shape) != len(template.shape):
        template = cv2.cvtColor(template, cv2.COLOR_BGR2GRAY)
        img = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

    h, w = template.shape[:2]
    img_h, img_w = img.shape[:2]

    # If no ROI → use full image
    if not rois:
        rois = [[0, 0, img_w, img_h]]

    matches = []

    for roi in rois:
        roi = clamp_roi(roi, img_w, img_h)
        if roi is None:
            continue  # skip invalid ROI

        x1, y1, x2, y2 = roi
        roi_img = img[y1:y2, x1:x2]

        # skip empty regions
        if roi_img.size == 0:
            continue

        result = cv2.matchTemplate(roi_img, template, cv2.TM_CCOEFF_NORMED)
        _, max_value, _, max_loc = cv2.minMaxLoc(result)
        score_color = "green" if max_value >= 0.9 else "yellow" if max_value >= 0.7 else "red"
        console.print(
            Panel.fit(
                f"[bold white]Location:[/bold white] {max_loc}   [{score_color}]Score: {max_value:.4f}[/{score_color}]",
                title=f"[bold magenta]🎯 Template Match - {name}[/bold magenta]",
                border_style=score_color
            )
        )

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



# def run_ocr(img_path=None, save_result=False, rois=None):
#     # Adding padding to process small rois better
#     # 👉 Modified to return the pad value so we can subtract it later
#     def add_padding(img, pad=50):
#         h, w, k = img.shape
#         avg_color = img.mean(axis=(0,1))

#         new_img = np.full((h + 2*pad, w + 2*pad, k), avg_color, dtype=img.dtype)
#         new_img[pad:pad+h, pad:pad+w] = img

#         return new_img, pad

#     if img_path:
#         img = cv2.imread(img_path)
#     else:
#         img = take_screenshot()

#     all_results =[]

#     # 👉 If ROI is provided
#     if rois:
#         h, w = img.shape[:2]
#         for roi in rois:
#             roi = clamp_roi(roi, w, h)
            
#             if not roi:
#                 continue
            
#             x1, y1, x2, y2 = roi
#             cropped = img[y1:y2, x1:x2]
            
#             # Unpack the padded image and the padding amount used
#             cropped, pad_val = add_padding(cropped, pad=50)
            
#             output = ocr.predict(cropped)[0]

#             results =[
#                 {
#                     "text": text,
#                     "score": float(score),
#                     # 👉 Fix: Subtract the padding amount, then add x1/y1
#                     "box": (box + np.array([x1 - pad_val, y1 - pad_val, x1 - pad_val, y1 - pad_val])).tolist()
#                 }
#                 for text, score, box in zip(
#                     output["rec_texts"],
#                     output["rec_scores"],
#                     output["rec_boxes"]
#                 )
#                 if score > 0.8
#             ]

#             all_results.extend(results)
#             print(all_results)

#             if save_result:
#                 cv2.imwrite(f"test/debug/roi-{time.time()}.png", cropped)

#     # 👉 If no ROI → normal full image OCR
#     else:
#         output = ocr.predict(img)[0]

#         all_results =[
#             {
#                 "text": text,
#                 "score": float(score),
#                 "box": box.tolist()
#             }
#             for text, score, box in zip(
#                 output["rec_texts"],
#                 output["rec_scores"],
#                 output["rec_boxes"]
#             ) if score > 0.8
#         ]

#         if save_result:
#             output.save_to_img("test/debug")
#     print(all_results)
#     return all_results


def run_ocr(
        img_path=None, 
        save_result=False, 
        rois=None, 
        save_frame=False,
        name = None,
        expected_text = None
    ):
    #Printing the OCR result a bit beautifully
    def print_ocr_results(results, capture_time_s=0, ocr_time_s=0, post_time_s=0):
        from rich.table import Table

        if not results:
            console.print(Panel.fit("[bold red]No OCR results found.[/bold red]", border_style="red"))
            return

        table = Table(title="📋 OCR Results", border_style="cyan", header_style="bold magenta")
        table.add_column("TEXT", style="white", max_width=25)
        table.add_column("SCORE", justify="center")
        table.add_column("BOX", style="dim cyan")

        for res in results:
            score = res["score"]
            color = "green" if score >= 0.95 else "yellow" if score >= 0.85 else "red"
            table.add_row(
                res["text"][:25],
                f"[{color}]{score:.2f}[/{color}]",
                str(res["box"])
            )

        console.print(table)
        console.print(Panel.fit(
            f"[dim]capture [bold white]{capture_time_s*1000:.2f}ms[/bold white]   "
            f"ocr [bold white]{ocr_time_s*1000:.2f}ms[/bold white]   "
            f"post [bold white]{post_time_s*1000:.2f}ms[/bold white][/dim]",
            title="[bold magenta]Timings[/bold magenta]",
            border_style="cyan"
        ))
        console.print(Panel.fit(
            f"[dim]Name: [bold white]{name}[/bold white]   "
            f"[dim]Expected: [bold white]{expected_text}[/bold white]   ",
            title="[bold magneta]Summary[/bold magneta]",
            border_style="cyan"
        ))


    #A function to add extra padding around the rois, OCR always fail for tiny image    
    def add_padding(img, pad=50):
        h, w, k = img.shape
        avg_color = img.mean(axis=(0, 1))
        new_img = np.full((h + 2*pad, w + 2*pad, k), avg_color, dtype=img.dtype)
        new_img[pad:pad+h, pad:pad+w] = img
        return new_img, pad
    
    _enforce_ram_cap("run_ocr:start")

    capture_time_s = 0.0
    ocr_time_s = 0.0
    post_time_s = 0.0

    img = None
    try:
        capture_start = time.perf_counter()
        img = _capture_frame(img_path, save_frame=save_frame)
        capture_time_s = time.perf_counter() - capture_start
    except Exception as e:
        logger.error("Error - %s", e)

    if img is None:
        return []

    all_results = []
    h, w = img.shape[:2]
    logger.debug("Height: %d, Width: %d", h, w)
    
    # Ensure debug directory exists if saving
    if save_result and not os.path.exists("test/debug"):
        os.makedirs("test/debug", exist_ok=True)

    if rois:
        for i, roi in enumerate(rois):
            roi = clamp_roi(roi, w, h) 
            if not roi:
                continue

            x1, y1, x2, y2 = roi
            #a slight adjustment so that it could take scrcpy image to with a res of 1080x2456
            y1 = y1 - 5
            y2 = y2
            # Only pad if the crop actually has dimensions
            raw_crop = img[y1:y2, x1:x2]
            if raw_crop.size == 0:
                continue
                
            cropped, pad_val = add_padding(raw_crop, pad=50)

            ocr_start = time.perf_counter()
            output = _call_ocr_with_recovery(cropped)
            ocr_time_s += time.perf_counter() - ocr_start
            
            if not output or not output[0]:
                # If save_result is true, save the empty crop to see what OCR saw
                if save_result:
                    cv2.imwrite(f"test/debug/roi_empty_{int(time.time())}_{i}.png", cropped)
                continue
                
            post_start = time.perf_counter()
            lines = output[0]
            offset_x = x1 - pad_val
            offset_y = y1 - pad_val

            for line in lines:
                if not line or not isinstance(line, list) or len(line) < 2:
                    continue

                pts = np.array(line[0])
                text = line[1][0]
                score = float(line[1][1])

                if score > 0.8:
                    xmin = int(pts[:, 0].min())
                    ymin = int(pts[:, 1].min())
                    xmax = int(pts[:, 0].max())
                    ymax = int(pts[:, 1].max())

                    all_results.append({
                        "text": text,
                        "score": score,
                        "box": [
                            xmin + offset_x, 
                            ymin + offset_y, 
                            xmax + offset_x, 
                            ymax + offset_y
                        ]
                    })
            
            if save_result:
                # Save the specific crop being processed
                cv2.imwrite(f"test/debug/roi_crop_{int(time.time())}_{i}.png", cropped)

            post_time_s += time.perf_counter() - post_start

    else:
        ocr_start = time.perf_counter()
        output = _call_ocr_with_recovery(img)
        ocr_time_s += time.perf_counter() - ocr_start

        if output and output[0]:
            post_start = time.perf_counter()
            for line in output[0]:
                if not line: continue
                
                pts = np.array(line[0])
                text = line[1][0]
                score = float(line[1][1])

                if score > 0.8:
                    xmin = int(pts[:, 0].min())
                    ymin = int(pts[:, 1].min())
                    xmax = int(pts[:, 0].max())
                    ymax = int(pts[:, 1].max())

                    all_results.append({
                        "text": text,
                        "score": score,
                        "box": [xmin, ymin, xmax, ymax]
                    })
            post_time_s += time.perf_counter() - post_start

    # 👉 SAVE FULL RESULT IMAGE
    if save_result and all_results:
        post_start = time.perf_counter()
        debug_img = img.copy()
        for res in all_results:
            b = res["box"]
            # Draw rectangle: (xmin, ymin), (xmax, ymax)
            cv2.rectangle(debug_img, (int(b[0]), int(b[1])), (int(b[2]), int(b[3])), (0, 255, 0), 2)
            cv2.putText(debug_img, res["text"], (int(b[0]), int(b[1]) - 10), 
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 1)
        
        cv2.imwrite(f"test/debug/full_res_{int(time.time())}.png", debug_img)
        post_time_s += time.perf_counter() - post_start

    print_ocr_results(all_results, capture_time_s, ocr_time_s, post_time_s)
    _enforce_ram_cap("run_ocr:end")
        
    return all_results


@app.post("/ocr")
def ocr_endpoint(req:OCRRequest):
    try:
        start_time = time.perf_counter()
        results = run_ocr(req.img_path, req.save_result, req.rois, req.save_frame, req.name, req.expected_text)
        finish_time = time.perf_counter()
        logger.debug("(%.3fs)", finish_time - start_time)
    except MemoryError as e:
        return {
            "success": False,
            "count": 0,
            "results": None,
            "error": str(e),
        }

    if results is None:
        return{
            "success" : False,
            "results" : None
        }

    return {
        "success" : True,
        "count" : len(results),
        "results" : results
    }



@app.post("/template")
def template_matching(req:TemplateMatchRequest):
    try:
        _enforce_ram_cap("template:start")
        results = match_template(
            name=req.name,
            threshold=req.threshold,
            save_result=req.save_result,
            rois=req.rois,
            parallel=req.parallel,
            session_id=req.session_id,
        )
        _enforce_ram_cap("template:end")
    except MemoryError as e:
        return {
            "success": False,
            "results": None,
            "error": str(e),
        }

    if results is None:
        return{
            "success" : False,
            "results" : None
        }

    return {
        "success" : True,
        "results" : results
    }


@app.get("/health")
def health_check():
    return {"status": "ok", "ocr_loaded": ocr is not None}


@app.post("/clear_cache")
def _clear_session_cache(req:ClearCacheRequest):
    with _cache_lock:
        _cache.pop(req.session_id, None)


take_preferred_screen_capture_tool()
_init_stream_resolution()
init_services()

if __name__ == "__main__":
    uvicorn.run(
        app,
        host="127.0.0.1",
        port=8000
    )
