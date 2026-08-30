#!/usr/bin/env bash
set -euo pipefail
PORT="${WOS_ADB_PORT:-16384}"
export WOS_ADB_SERIAL="127.0.0.1:$PORT"
export OCR_CAPTURE_TOOL=adb
export OCR_RAM_CAP_GB="${OCR_RAM_CAP_GB:-16}"
# 8210, not 8000: a foreign dev server on 8000 answers /docs (fooling the
# readiness gate below) while every /ocr call 404s — observed live 2026-08-30.
export OCR_PORT="${OCR_PORT:-8210}"
# Unbuffered stdout: when this script's output is piped (logging, watchdogs),
# block buffering otherwise delays progress lines by minutes.
export PYTHONUNBUFFERED=1

# adb reads stdin; </dev/null keeps it from draining input piped to this
# script before Main.main's task selector gets to read it.
adb connect "$WOS_ADB_SERIAL" </dev/null

# Gate on real framebuffer dimensions, not `wm size` — that can print both
# Physical and Override lines, and proves neither screenshot size nor viewport.
adb -s "$WOS_ADB_SERIAL" exec-out screencap -p > /tmp/wos-gate.png </dev/null
uv run python -c "
from PIL import Image; import sys
w,h = Image.open('/tmp/wos-gate.png').size
sys.exit(0 if (w,h)==(1080,2460) else f'FATAL: framebuffer {w}x{h}, expected 1080x2460')"

uv run python -m core.ocr </dev/null &
OCR_PID=$!
trap 'kill $OCR_PID 2>/dev/null' EXIT INT TERM

# PaddleOCR downloads models on first run — wait for readiness, do not race it.
for i in $(seq 1 120); do
  curl -sf "localhost:$OCR_PORT/docs" >/dev/null && break
  sleep 2
done
curl -sf "localhost:$OCR_PORT/docs" >/dev/null || { echo "FATAL: OCR server never came up"; exit 1; }

# Module form, not path form: running Main/main.py puts Main/ (not the repo
# root) on sys.path[0], so `import cmd_program` fails. Same fix as core.ocr above.
uv run python -m Main.main
