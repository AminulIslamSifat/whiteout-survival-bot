#!/usr/bin/env bash
set -euo pipefail
PORT="${WOS_ADB_PORT:-16384}"
export WOS_ADB_SERIAL="127.0.0.1:$PORT"
export OCR_CAPTURE_TOOL=adb
export OCR_RAM_CAP_GB="${OCR_RAM_CAP_GB:-16}"

adb connect "$WOS_ADB_SERIAL"

# Gate on real framebuffer dimensions, not `wm size` — that can print both
# Physical and Override lines, and proves neither screenshot size nor viewport.
adb -s "$WOS_ADB_SERIAL" exec-out screencap -p > /tmp/wos-gate.png
uv run python -c "
from PIL import Image; import sys
w,h = Image.open('/tmp/wos-gate.png').size
sys.exit(0 if (w,h)==(1080,2460) else f'FATAL: framebuffer {w}x{h}, expected 1080x2460')"

uv run core/ocr.py &
OCR_PID=$!
trap 'kill $OCR_PID 2>/dev/null' EXIT INT TERM

# PaddleOCR downloads models on first run — wait for readiness, do not race it.
for i in $(seq 1 120); do
  curl -sf localhost:8000/docs >/dev/null && break
  sleep 2
done

uv run python Main/main.py
