import subprocess
import threading
import time
import os
from pathlib import Path

import numpy as np
import json
from cmd_program.resolution_utils import get_stream_resolution, get_device_resolution
from core.logging_config import get_logger

logger = get_logger(__name__)


try:
    with open("cmd_program/scrcpy_config.json", "r") as file:
        config = json.load(file)
except Exception as e:
    logger.error("Config Loading Error: %s", e)
    config = None



def setup_v4l2loopback(password: str | None = None):
    cmd = ["sudo"]
    if password is None:
        cmd.append("-n")
    else:
        cmd.append("-S")

    cmd.extend([
        "modprobe",
        "v4l2loopback",
        "devices=1",
        "video_nr=10",
        "card_label=scrcpy",
    ])

    kwargs = {
        "capture_output": True,
        "text": True,
    }
    if password is not None:
        kwargs["input"] = f"{password}\n"

    result = subprocess.run(cmd, **kwargs)
    
    return result.returncode == 0




class ScreenStreamService:
    def __init__(
        self,
        video_device="/dev/video10",
        width=1080,
        height=2456,
        startup_timeout=15.0,
        video_bit_rate="8M",
        ffmpeg_start_retries=6,
        max_fps = None,
        audio = False,
        show_screen = True,
        turn_screen_off = True,
        max_size = 0,
        device_id: str = None,
        use_dynamic_resolution: bool = True
    ):
        if config != None:
            video_device=config["video_device"]
            width=config["width"]
            height=config["height"]
            startup_timeout=config["startup_timeout"]
            video_bit_rate=config["video_bit_rate"]
            ffmpeg_start_retries=config["ffmpeg_start_retries"]
            max_fps = config["max_fps"]
            audio = config["audio"]
            show_screen = config["show_screen"]
            turn_screen_off = config["turn_screen_off"]
            max_size = config["max_size"]
        
        self.video_device = Path(video_device)
        self.width = int(width)
        self.height = int(height)
        self.device_id = device_id
        self.use_dynamic_resolution = use_dynamic_resolution
        self.startup_timeout = float(startup_timeout)
        self.video_bit_rate = str(video_bit_rate)
        self.ffmpeg_start_retries = int(ffmpeg_start_retries)
        self.max_fps = int(max_fps) if max_fps else None
        self.audio = audio
        self.show_screen = show_screen
        self.turn_screen_off = turn_screen_off
        self.max_size = int(max_size) if max_size else 0

        self._scrcpy_proc = None
        self._ffmpeg_proc = None
        self._reader_thread = None
        self._stop_event = threading.Event()

        self._latest_frame = None
        self._frame_lock = threading.Lock()

    @property
    def is_running(self):
        return (
            self._scrcpy_proc is not None
            and self._scrcpy_proc.poll() is None
            and self._ffmpeg_proc is not None
            and self._ffmpeg_proc.poll() is None
        )

    def start(self):
        if self.is_running:
            return

        # Fetch dynamic resolution if enabled and device_id is available
        if self.use_dynamic_resolution and self.device_id:
            try:
                stream_width, stream_height = get_stream_resolution(self.device_id, apply_scrcpy_quirk=True)
                self.width = stream_width
                self.height = stream_height
                logger.info("Dynamic resolution: %dx%d", self.width, self.height)
            except Exception as e:
                logger.warning("Failed to detect dynamic resolution: %s. Using configured: %dx%d", e, self.width, self.height)

        self.stop()
        self._stop_event.clear()

        scrcpy_cmd = [
            "scrcpy",
            "--max-size",
            str(self.max_size),
            f"--v4l2-sink={self.video_device}",
            "--video-bit-rate",
            self.video_bit_rate,
        ]
        if not self.audio:
            scrcpy_cmd.append("--no-audio")
        if not self.show_screen:
            scrcpy_cmd.append("--no-window")
        if self.turn_screen_off:
            scrcpy_cmd.append("--turn-screen-off")
        if self.max_fps:
            scrcpy_cmd.extend(["--max-fps", str(self.max_fps)])
        
        self._scrcpy_proc = subprocess.Popen(scrcpy_cmd)

        deadline = time.time() + self.startup_timeout
        while time.time() < deadline:
            if self._scrcpy_proc.poll() is not None:
                raise RuntimeError("scrcpy exited before V4L2 stream was available")
            if self.video_device.exists():
                break
            time.sleep(0.2)

        if not self.video_device.exists():
            self.stop()
            raise RuntimeError(f"V4L2 device was not created: {self.video_device}")

        self._wait_for_stream_signal()
        self._ffmpeg_proc = self._start_ffmpeg_with_retries()

        self._reader_thread = threading.Thread(target=self._reader_loop, daemon=True)
        self._reader_thread.start()

    def stop(self):
        self._stop_event.set()

        if self._reader_thread is not None:
            self._reader_thread.join(timeout=1.0)
            self._reader_thread = None

        self._stop_process(self._ffmpeg_proc)
        self._ffmpeg_proc = None

        self._stop_process(self._scrcpy_proc)
        self._scrcpy_proc = None

    def screen_capture(self, wait=True, timeout=2.0):
        if not self.is_running:
            raise RuntimeError("Screen stream service is not running")

        end_time = time.time() + float(timeout)
        while True:
            with self._frame_lock:
                if self._latest_frame is not None:
                    return self._latest_frame.copy()

            if not wait:
                return None

            if self._scrcpy_proc.poll() is not None:
                raise RuntimeError("scrcpy exited while waiting for frame")
            if self._ffmpeg_proc.poll() is not None:
                raise RuntimeError("ffmpeg exited while waiting for frame")
            if time.time() >= end_time:
                return None

            time.sleep(0.01)

    def _build_ffmpeg_cmd(self):
        cmd = [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "v4l2",
            "-thread_queue_size",
            "512",
            "-i",
            str(self.video_device),
        ]

        # Force ffmpeg to output frames at the configured width/height so
        # the raw frame reader can compute a stable frame size.
        if self.width and self.height:
            cmd.extend(["-s", f"{self.width}x{self.height}"])

        cmd.extend([
            "-f",
            "rawvideo",
            "-pix_fmt",
            "bgr24",
            "pipe:1",
        ])

        return cmd

    def _start_ffmpeg_with_retries(self):
        last_error = "unknown"
        attempts = max(1, self.ffmpeg_start_retries)
        for attempt in range(1, attempts + 1):
            if self._scrcpy_proc is None or self._scrcpy_proc.poll() is not None:
                raise RuntimeError("scrcpy exited before ffmpeg could start")

            ffmpeg_proc = subprocess.Popen(
                self._build_ffmpeg_cmd(),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                bufsize=10**8,
            )

            # ffmpeg fails fast on VIDIOC_STREAMON issues; give it a short grace window.
            time.sleep(0.35)
            if ffmpeg_proc.poll() is None:
                return ffmpeg_proc

            stderr_data = ffmpeg_proc.stderr.read().decode("utf-8", errors="replace").strip()
            if stderr_data:
                last_error = stderr_data

            backoff = min(0.25 * attempt, 1.0)
            time.sleep(backoff)

        raise RuntimeError(
            f"Failed to start ffmpeg on {self.video_device} after {attempts} attempts: {last_error}"
        )

    def _wait_for_stream_signal(self):
        # v4l2 loopback node can exist before scrcpy actually starts producing frames.
        deadline = time.time() + self.startup_timeout
        while time.time() < deadline:
            if self._scrcpy_proc is None or self._scrcpy_proc.poll() is not None:
                raise RuntimeError("scrcpy exited before stream became active")

            try:
                fd = os.open(self.video_device, os.O_RDONLY | os.O_NONBLOCK)
                try:
                    sample = os.read(fd, 4096)
                finally:
                    os.close(fd)

                if sample:
                    return
            except OSError:
                pass

            time.sleep(0.2)

        # Continue anyway and let ffmpeg retries handle final readiness.

    def _reader_loop(self):
        # compute frame_size at loop start so any dynamic changes are honored
        frame_size = int(self.width) * int(self.height) * 3
        while not self._stop_event.is_set():
            raw = self._read_exact(frame_size)
            if raw is None:
                if self._ffmpeg_proc is None or self._ffmpeg_proc.poll() is not None:
                    break
                continue

            try:
                frame = np.frombuffer(raw, np.uint8).reshape((int(self.height), int(self.width), 3))
            except Exception:
                # If frame size doesn't match expectations, attempt to recover by
                # inferring dimensions from the raw length (dividing by 3) and
                # falling back to width/height swap if needed.
                total_pixels = len(raw) // 3
                if total_pixels == 0:
                    continue
                # try using configured width to compute height
                if int(self.width) and total_pixels % int(self.width) == 0:
                    inferred_h = total_pixels // int(self.width)
                    frame = np.frombuffer(raw, np.uint8).reshape((inferred_h, int(self.width), 3))
                    # update stored height to match inferred
                    self.height = inferred_h
                else:
                    # fallback: try configured height to compute width
                    if int(self.height) and total_pixels % int(self.height) == 0:
                        inferred_w = total_pixels // int(self.height)
                        frame = np.frombuffer(raw, np.uint8).reshape((int(self.height), inferred_w, 3))
                        self.width = inferred_w
                    else:
                        # give up on this frame
                        continue
            with self._frame_lock:
                self._latest_frame = frame

    def _read_exact(self, size):
        if self._ffmpeg_proc is None or self._ffmpeg_proc.stdout is None:
            return None

        chunks = []
        remaining = size
        while remaining > 0 and not self._stop_event.is_set():
            chunk = self._ffmpeg_proc.stdout.read(remaining)
            if not chunk:
                return None
            chunks.append(chunk)
            remaining -= len(chunk)

        if remaining != 0:
            return None

        return b"".join(chunks)

    @staticmethod
    def _stop_process(proc):
        if proc is None or proc.poll() is not None:
            return

        proc.terminate()
        try:
            proc.wait(timeout=2)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=2)


_stream_service = ScreenStreamService()


def start_screen_stream(device_id: str = None, **kwargs):
    global _stream_service
    if device_id:
        kwargs['device_id'] = device_id
    if kwargs:
        _stream_service = ScreenStreamService(**kwargs)
    _stream_service.start()
    return _stream_service


def stop_screen_stream():
    _stream_service.stop()


def screen_capture(wait=True, timeout=2.0):
    return _stream_service.screen_capture(wait=wait, timeout=timeout)


