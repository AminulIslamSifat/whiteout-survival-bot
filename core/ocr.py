import os
import sys

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

# Paddle env flags (model-source probing, GC/allocator) moved into
# _build_paddle_engine(): they must be set before paddle is imported, and
# paddle is now imported lazily so vision-default boots never pay for it.


import cv2
import json
import re
import sys
import time
import gc
import json
import ctypes
import psutil
import uvicorn
import platform
import threading
import numpy as np
from pathlib import Path
from typing import Optional
from fastapi import FastAPI
from pydantic import BaseModel
from rich.panel import Panel
from rich.prompt import Prompt
from rich.console import Console
from concurrent.futures import ThreadPoolExecutor
from cmd_program.screen_action import take_screenshot
from cmd_program.screen_stream import screen_capture as stream_screen_capture
from cmd_program.screen_stream import start_screen_stream, setup_v4l2loopback
from core.coord_utils import BASE_WIDTH, BASE_HEIGHT

# paddle / paddleocr are imported lazily inside _build_paddle_engine();
# core.vision_engine is imported lazily inside _build_vision_engine().
# Neither engine's import cost is paid unless that engine is actually used.

import logging
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
    # read_kind="value" marks reads whose text feeds numeric state (power,
    # levels, timers): they qualify for zero-item fallback and burn-in
    # shadow-compare. Set by CALLERS at value-read sites, never in shared
    # plumbing.
    read_kind: Optional[str] = None
    # One UUID per caller decision (tap_on_text / req_text invocation);
    # retries share it, so burn-in rates count decisions, not read attempts.
    decision_id: Optional[str] = None


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
# Engine selection: unset -> vision on macOS >= 13, paddle everywhere else.
# Explicit OCR_ENGINE=vision on an unsupported platform fails loudly at boot.
# OCR_ENGINE=paddle is the one-variable rollback for the Vision swap.
OCR_ENGINE_ENV = "OCR_ENGINE"
# Server port. run.sh defaults this to 8210 on macOS: port 8000 is a common
# dev-server default and a foreign FastAPI there answers /docs, fooling the
# readiness gate while every /ocr call 404s (observed live 2026-08-30).
OCR_PORT = int(os.getenv("OCR_PORT", "8000"))
OCR_SCORE_FLOOR = 0.8  # per-line confidence filter, shared by both engines
# Burn-in instrumentation (Vision swap): per-read JSONL + Paddle shadow reads
# on value reads. Default ON until the burn-in exit criteria are met
# (see docs/designs/vision-ocr-swap.md), then flip to "0".
BURNIN_ENABLED = os.getenv("OCR_BURNIN", "1") == "1"
BURNIN_LOG_PATH = Path("logs/ocr_burnin.jsonl")
VISION_EXC_BREAKER_LIMIT = 3  # consecutive exceptions -> paddle for the session
TEMPLATE_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "references", "icon"))
RAM_CAP_GB = float(os.getenv("OCR_RAM_CAP_GB", "16.0"))
RAM_CAP_BYTES = int(RAM_CAP_GB * 1024 * 1024 * 1024)
# STREAM_WIDTH / STREAM_HEIGHT feed start_screen_stream() (the Linux-only scrcpy path,
# see below) and are deliberately NOT unified with BASE_WIDTH/BASE_HEIGHT below: on
# Linux, 2456 may genuinely be scrcpy's real output height, and this codebase cannot
# verify scrcpy behaviour from a Mac. Do not repurpose these for frame normalization.
STREAM_WIDTH = 1080
STREAM_HEIGHT = 2456
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
_resolved_engine = None          # "vision" | "paddle", set by init_services()
_vision_engine = None
_paddle_engine = None            # lazy: built on first paddle use
_vision_exc_streak = 0           # consecutive VisionEngineError count
_vision_disabled_session = False # breaker tripped: paddle until restart



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
        print(f"Saved frame to {save_path}")


# Coordinate space. The capture leg and the tap leg must agree on ONE base.
#
#   MuMu @ 1080x2460
#     | adb exec-out screencap -p
#     v
#   take_screenshot()              screen_action.py   -> 1080x2460
#     v
#   _normalize_frame_resolution()  <- YOU ARE HERE
#     |  dims == base -> early return, no resize
#     v
#   ROI percentages                references/TextArea/*.json
#     v
#   OCR engine (vision|paddle)  -> text + coords   core/vision_engine.py | paddle
#     v
#   tap_screen(x%, y%)             _convert_if_percentage(y, BASE_HEIGHT)
#     v
#   adb shell input tap -> MuMu @ 1080x2460
#
# Historical bug: this function normalised to STREAM_HEIGHT=2456 while taps used
# 2460, so the vision leg ran 0.16% short and ocr.py:678 carried a `y1 -= 5` fudge
# to compensate. Both are gone. BASE_* in core/coord_utils is the single authority.
def _normalize_frame_resolution(frame):
    if frame is None:
        return None

    h, w = frame.shape[:2]
    if w == BASE_WIDTH and h == BASE_HEIGHT:
        return frame

    return cv2.resize(frame, (BASE_WIDTH, BASE_HEIGHT), interpolation=cv2.INTER_LINEAR)


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
            print(f"screen_stream start failed, falling back to adb: {e}")
            _stream_ready = False
            _stream_retry_after = now + STREAM_RETRY_COOLDOWN_S
            return False


# The sensor is repaired but the actuator is held dormant during the Mac port:
# the in-code RAM_CAP_GB default above (16.0) IS the dormancy mechanism -- it
# keeps _enforce_ram_cap() reporting honest RSS without arming
# _reinitialize_ocr_engine(), a teardown/rebuild path that has never executed
# on macOS. OCR_RAM_CAP_GB still overrides it if a caller sets it explicitly.
# Lower the in-code default to 3 once the daily loop is stable.
def _get_process_rss_bytes():
    """Current process RSS in bytes. Cross-platform (macOS has no /proc)."""
    try:
        return psutil.Process().memory_info().rss
    except Exception:
        return 0


def _trim_allocator():
    """Attempt to return free heap pages to OS on glibc systems."""
    try:
        libc = ctypes.CDLL("libc.so.6")
        libc.malloc_trim(0)
    except Exception:
        pass


def _enforce_ram_cap(context="runtime"):
    """Try to keep process RSS under configured cap by recycling OCR engine.

    Paddle-only machinery: it exists to babysit Paddle's memory behavior.
    While no Paddle engine is instantiated (vision path), it is a no-op —
    Vision leak safety is per-call autorelease pools + RSS in burn-in logs."""
    global _paddle_engine
    if _paddle_engine is None:
        return
    rss_before = _get_process_rss_bytes()
    if rss_before <= RAM_CAP_BYTES:
        return

    with _ram_guard_lock:
        # Re-check after lock to avoid duplicate recycle work.
        rss_before = _get_process_rss_bytes()
        if rss_before <= RAM_CAP_BYTES:
            return

        print(
            f"RAM guard triggered in {context}: "
            f"rss={rss_before / (1024**3):.2f}GB cap={RAM_CAP_GB:.2f}GB. Recycling OCR engine..."
        )

        with _ocr_init_lock:
            _paddle_engine = _build_paddle_engine()
        gc.collect()
        _trim_allocator()

        rss_after = _get_process_rss_bytes()
        if rss_after > RAM_CAP_BYTES:
            raise MemoryError(
                f"RAM cap exceeded after recycle in {context}. "
                f"rss={rss_after / (1024**3):.2f}GB cap={RAM_CAP_GB:.2f}GB"
            )


#------------------- Engine management ---------------------------#
# Engine dispatch state machine (see docs/designs/vision-ocr-swap.md):
#
#           boot: resolve_engine()
#            | unset -> vision on macOS>=13, else paddle
#            v
#       +- VISION ---------------------------------------------+
#       |  read ok -----------------------> stay (streak = 0)  |
#       |  zero items + (expected|value) -> paddle one-shot    |
#       |  VisionEngineError -> streak++                       |
#       |     streak < 3 -> stay (treated as zero items)       |
#       |     streak = 3 -> PADDLE for the session (loud log)  |
#       +------------------------------------------------------+
#       PADDLE_SESSION never flips back mid-run (no flapping);
#       restart re-resolves. Models absent -> NEVER flip, NEVER
#       download mid-session: stay on vision and log loudly.


def _macos_major():
    try:
        return int(platform.mac_ver()[0].split(".")[0])
    except (ValueError, IndexError):
        return 0


def _vision_supported():
    return sys.platform == "darwin" and _macos_major() >= 13


def resolve_engine():
    explicit = os.getenv(OCR_ENGINE_ENV, "").strip().lower()
    if explicit == "paddle":
        return "paddle"
    if explicit == "vision":
        if not _vision_supported():
            raise RuntimeError(
                f"OCR_ENGINE=vision requires macOS >= 13 (this host: "
                f"{sys.platform} {platform.mac_ver()[0] or 'n/a'})"
            )
        return "vision"
    if explicit:
        raise RuntimeError(f"OCR_ENGINE must be 'vision' or 'paddle', got {explicit!r}")
    return "vision" if _vision_supported() else "paddle"


def _paddle_models_present():
    whl = Path.home() / ".paddleocr" / "whl"
    return whl.is_dir() and any(whl.iterdir())


def _build_paddle_engine():
    # Env flags MUST be set before paddle is imported to affect the C++ backend.
    os.environ.setdefault("PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK", "True")
    os.environ["FLAGS_eager_delete_tensor_gb"] = "0.0"
    os.environ["FLAGS_fast_eager_deletion_mode"] = "True"
    os.environ["FLAGS_allocator_strategy"] = "naive_best_fit"

    import paddle
    import paddleocr
    from paddleocr import PaddleOCR
    logging.getLogger("ppocr").setLevel(logging.ERROR)
    print(f"PaddleOCR Version: {paddleocr.__version__}")
    print(f"PaddlePaddle Version: {paddle.__version__}")

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


def _get_paddle_engine():
    global _paddle_engine
    with _ocr_init_lock:
        if _paddle_engine is None:
            _paddle_engine = _build_paddle_engine()
    return _paddle_engine


def _build_vision_engine():
    from core.vision_engine import VisionEngine
    engine = VisionEngine(console=console)
    engine.warmup()
    return engine


def _active_engine():
    if _resolved_engine == "paddle" or _vision_disabled_session:
        return "paddle"
    return "vision"


def _paddle_lines_to_items(output):
    """Paddle raw output -> canonical [{text, score, box}] with the shared
    score floor. Single conversion point for both ROI and full-frame paths."""
    items = []
    if not output or not output[0]:
        return items
    for line in output[0]:
        if not line or not isinstance(line, list) or len(line) < 2:
            continue
        pts = np.array(line[0])
        text = line[1][0]
        score = float(line[1][1])
        if score > OCR_SCORE_FLOOR:
            items.append({
                "text": text,
                "score": score,
                "box": [int(pts[:, 0].min()), int(pts[:, 1].min()),
                        int(pts[:, 0].max()), int(pts[:, 1].max())],
            })
    return items


def _paddle_recognize_unlocked(image):
    """Paddle read with the primitive-failure recovery retry. Caller holds _ocr_lock."""
    global _paddle_engine
    engine = _get_paddle_engine()
    try:
        output = engine.ocr(image, cls=False)
    except RuntimeError as e:
        # Paddle sometimes throws this when predictor state gets unstable.
        if "could not execute a primitive" not in str(e):
            raise
        print("OCR primitive execution failed. Reinitializing OCR engine and retrying once...")
        with _ocr_init_lock:
            _paddle_engine = _build_paddle_engine()
        output = _paddle_engine.ocr(image, cls=False)
    return _paddle_lines_to_items(output)


def _vision_recognize_unlocked(image):
    """Vision read behind the exception circuit breaker. Caller holds _ocr_lock.

    Returns (items, error_flag): framework errors are logged, counted, and
    surfaced as (zero items, True) so the caller's fallback rule applies.
    """
    global _vision_exc_streak, _vision_disabled_session
    from core.vision_engine import VisionEngineError
    try:
        items = _vision_engine.recognize(image)
        _vision_exc_streak = 0
        return [i for i in items if i["score"] > OCR_SCORE_FLOOR], False
    except VisionEngineError as e:
        _vision_exc_streak += 1
        console.print(
            f"[bold red]Vision engine error ({_vision_exc_streak}/"
            f"{VISION_EXC_BREAKER_LIMIT}): {e}[/bold red]"
        )
        if _vision_exc_streak >= VISION_EXC_BREAKER_LIMIT:
            if _paddle_models_present():
                _vision_disabled_session = True
                console.print(Panel.fit(
                    "[bold red]Vision breaker tripped: "
                    f"{VISION_EXC_BREAKER_LIMIT} consecutive errors — using PADDLE "
                    "for the rest of this session. Restart to re-resolve.[/bold red]",
                    border_style="red",
                ))
            else:
                console.print(
                    "[bold red]Vision breaker limit reached but Paddle models are "
                    "absent (~/.paddleocr/whl) — staying on Vision; models are NEVER "
                    "downloaded mid-session. Run the setup prefetch.[/bold red]"
                )
        return [], True


def _recognize_crop_unlocked(image, expected_text=None, read_kind=None):
    """One crop through the active engine, with the per-crop fallback rule.

    Fallback: Vision yielded zero items AND read_kind=='value' -> one-shot
    Paddle read of the SAME crop. Value reads target always-rendered numerics
    (the isolated-badge-digit case Vision refuses), so zero items there means
    "Vision missed it". expected_text alone does NOT trigger fallback: label
    taps POLL for text that legitimately isn't on screen yet (first live run:
    23/38 reads were absent-text polls where Paddle also found nothing — a
    fallback there just doubles every poll tick and drags Paddle into RSS).
    A genuinely present label Vision can't read costs one poll tick and is
    absorbed by the client's retry/ROI-expansion machinery, same as a Paddle
    miss today. Wrong-nonzero reads never fall back (caller fuzzy nets own
    those). Returns (items, engine_used, fallback_hit).
    """
    if _active_engine() == "paddle":
        return _paddle_recognize_unlocked(image), "paddle", False

    items, _errored = _vision_recognize_unlocked(image)
    if items or read_kind != "value":
        return items, "vision", False
    if _vision_disabled_session:
        # Breaker flipped mid-call: the paddle read below is the session engine now.
        return _paddle_recognize_unlocked(image), "paddle", False
    if not _paddle_models_present():
        return items, "vision", False
    fallback_items = _paddle_recognize_unlocked(image)
    if fallback_items:
        console.print(f"[yellow]Vision zero-item fallback hit -> paddle read succeeded[/yellow]")
    return fallback_items, "vision+fallback", True


def _digits(text):
    return re.sub(r"\D", "", text)


def _shadow_compare_unlocked(image, vision_items):
    """Burn-in only: Paddle shadow read of the SAME crop, digit comparison.
    Returns a mismatch dict or None. Caller holds _ocr_lock."""
    if not _paddle_models_present():
        return None
    paddle_items = _paddle_recognize_unlocked(image)
    v_digits = _digits("".join(i["text"] for i in vision_items))
    p_digits = _digits("".join(i["text"] for i in paddle_items))
    if v_digits == p_digits:
        return None
    return {
        "vision_texts": [i["text"] for i in vision_items],
        "paddle_texts": [i["text"] for i in paddle_items],
        "vision_digits": v_digits,
        "paddle_digits": p_digits,
    }


def _burnin_log(record):
    if not BURNIN_ENABLED:
        return
    try:
        BURNIN_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        record["ts"] = time.time()
        record["rss_mb"] = round(_get_process_rss_bytes() / (1024 * 1024), 1)
        with open(BURNIN_LOG_PATH, "a") as f:
            f.write(json.dumps(record) + "\n")
    except OSError as e:
        print(f"burn-in log write failed: {e}")


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
            print(f"screen_stream capture failed, using adb: {e}")
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


def _get_cached_image(session_id):
    with _cache_lock:
        if session_id in _cache:
            return _cache[session_id]

        img = _capture_frame()
        _cache[session_id] = img
        return img


#----------------------- Functions -------------------------------#
def init_services():
    global _resolved_engine, _vision_engine, _template_cache

    _resolved_engine = resolve_engine()
    if _resolved_engine == "vision":
        _vision_engine = _build_vision_engine()
        console.print(
            "[bold green]OCR engine: VISION[/bold green] "
            "[dim](rollback: OCR_ENGINE=paddle + restart)[/dim]"
        )
    else:
        # Paddle mode keeps today's behavior: engine built eagerly at boot.
        _get_paddle_engine()
        console.print("[bold green]OCR engine: PADDLE[/bold green]")

    root_dir = Path(TEMPLATE_PATH)
    print(root_dir)
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
        expected_text = None,
        read_kind = None,
        decision_id = None
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
        print(f"Error - {e}")
        raise RuntimeError(f"OCR capture failed: {e}") from e

    if img is None:
        return []

    all_results = []
    engines_used = []
    fallback_hits = 0
    mismatches = []
    h, w = img.shape[:2]
    print(f"Height: {h}, Width: {w}")
    
    # Ensure debug directory exists if saving
    if save_result and not os.path.exists("test/debug"):
        os.makedirs("test/debug", exist_ok=True)

    if rois:
        for i, roi in enumerate(rois):
            roi = clamp_roi(roi, w, h) 
            if not roi:
                continue

            x1, y1, x2, y2 = roi
            # Only pad if the crop actually has dimensions
            raw_crop = img[y1:y2, x1:x2]
            if raw_crop.size == 0:
                continue
                
            cropped, pad_val = add_padding(raw_crop, pad=50)

            # Lock held ONCE around the engine call + optional shadow pair —
            # the engines themselves are lock-free (no self-nesting).
            ocr_start = time.perf_counter()
            with _ocr_lock:
                items, engine_used, fallback_hit = _recognize_crop_unlocked(
                    cropped, expected_text=expected_text, read_kind=read_kind
                )
                mismatch = None
                if (BURNIN_ENABLED and read_kind == "value"
                        and engine_used == "vision" and items):
                    mismatch = _shadow_compare_unlocked(cropped, items)
            ocr_time_s += time.perf_counter() - ocr_start

            engines_used.append(engine_used)
            fallback_hits += 1 if fallback_hit else 0
            if mismatch:
                mismatch["roi_index"] = i
                mismatches.append(mismatch)
                console.print(f"[bold red]DIGIT_MISMATCH[/bold red] roi={i} {mismatch}")

            if not items:
                # If save_result is true, save the empty crop to see what OCR saw
                if save_result:
                    cv2.imwrite(f"test/debug/roi_empty_{int(time.time())}_{i}.png", cropped)
                continue

            post_start = time.perf_counter()
            offset_x = x1 - pad_val
            offset_y = y1 - pad_val

            for item in items:
                b = item["box"]
                all_results.append({
                    "text": item["text"],
                    "score": item["score"],
                    "box": [
                        b[0] + offset_x,
                        b[1] + offset_y,
                        b[2] + offset_x,
                        b[3] + offset_y
                    ]
                })

            if save_result:
                # Save the specific crop being processed
                cv2.imwrite(f"test/debug/roi_crop_{int(time.time())}_{i}.png", cropped)

            post_time_s += time.perf_counter() - post_start

    else:
        ocr_start = time.perf_counter()
        with _ocr_lock:
            items, engine_used, fallback_hit = _recognize_crop_unlocked(
                img, expected_text=expected_text, read_kind=read_kind
            )
            mismatch = None
            if (BURNIN_ENABLED and read_kind == "value"
                    and engine_used == "vision" and items):
                mismatch = _shadow_compare_unlocked(img, items)
        ocr_time_s += time.perf_counter() - ocr_start

        engines_used.append(engine_used)
        fallback_hits += 1 if fallback_hit else 0
        if mismatch:
            mismatches.append(mismatch)
            console.print(f"[bold red]DIGIT_MISMATCH[/bold red] full-frame {mismatch}")

        if items:
            post_start = time.perf_counter()
            all_results.extend(items)
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

    _burnin_log({
        "decision_id": decision_id,
        "name": name,
        "read_kind": read_kind,
        "expected": bool(expected_text),
        "engines": engines_used,
        "fallback_hits": fallback_hits,
        "digit_mismatch": bool(mismatches),
        "mismatches": mismatches,
        "capture_ms": round(capture_time_s * 1000, 1),
        "ocr_ms": round(ocr_time_s * 1000, 1),
        "results": len(all_results),
    })

    return all_results


@app.post("/ocr")
def ocr_endpoint(req:OCRRequest):
    try:
        start_time = time.perf_counter()
        results = run_ocr(req.img_path, req.save_result, req.rois, req.save_frame,
                          req.name, req.expected_text, req.read_kind, req.decision_id)
        finish_time = time.perf_counter()
        print(f"({finish_time-start_time}s)")
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


@app.post("/clear_cache")
def _clear_session_cache(req:ClearCacheRequest):
    with _cache_lock:
        _cache.pop(req.session_id, None)


take_preferred_screen_capture_tool()
init_services()

if __name__ == "__main__":
    uvicorn.run(
        app,
        host="127.0.0.1",
        port=OCR_PORT
    )
