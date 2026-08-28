# Batch C+D — RAM sensor repair (T7) and the run.sh launcher (T8)

Two small independent pieces. C edits `core/ocr.py` + `pyproject.toml`. D creates a new
file `run.sh`. They share no code.

---

# C (T7) — Repair the RAM sensor, leave the actuator dormant

## Problem

`core/ocr.py` `_get_process_rss_bytes()` reads `/proc/self/status`, which does not exist
on macOS. The exception is swallowed and the function returns `0`, so
`_enforce_ram_cap()` sees `0 <= cap` and returns immediately, every time. The guard is
not weakened on macOS — it is completely inert.

It is called at FOUR hot points wrapping every OCR run and every template match. Find
them with: `grep -n "_enforce_ram_cap" core/ocr.py`

Consequence: `_reinitialize_ocr_engine()` — the mechanism that recycles the leaky
PaddleOCR engine when memory grows — never runs on macOS.

## Required

1. Add `psutil` as a runtime dependency: run `uv add psutil` from the repo root. (Pillow
   is already present transitively; psutil is not.)

2. Replace the body of `_get_process_rss_bytes()` so it works cross-platform:

       def _get_process_rss_bytes():
           """Current process RSS in bytes. Cross-platform (macOS has no /proc)."""
           try:
               return psutil.Process().memory_info().rss
           except Exception:
               return 0

   Add `import psutil` with the other imports.

3. **Do NOT use `resource.getrusage`.** `ru_maxrss` is a PEAK that never decreases, so
   once the process touched the cap the guard would latch on permanently and recycle the
   engine forever. This is the trap; avoid it.

4. Above the function, add a comment recording why the cap is deliberately set high
   during the port:

       # The sensor is repaired but the actuator is held dormant during the Mac port:
       # run with OCR_RAM_CAP_GB=16 so _enforce_ram_cap() reports honest RSS without
       # arming _reinitialize_ocr_engine(), a teardown/rebuild path that has never
       # executed on macOS. Lower the cap to 3 once the daily loop is stable.

5. Do NOT change `RAM_CAP_GB`'s default in the source. It already reads
   `OCR_RAM_CAP_GB` from the environment; `run.sh` sets the high value.

## Constraint

The `except Exception: return 0` here is DELIBERATE and must stay — a memory probe must
never crash the OCR server. This is the one place a broad catch is correct.

---

# D (T8) — run.sh at the repo root

## Why

Both processes need adb connected BEFORE Python imports anything, and both must run from
the repo root (`cmd_program/screen_stream.py:13` opens `cmd_program/scrcpy_config.json`
by a relative path; `cache/` and `test/debug/` writes are relative too).

## Required — create `run.sh` at the repo root with exactly this content

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

Then `chmod +x run.sh`.

Notes on why each piece exists — preserve all of them:
- `OCR_CAPTURE_TOOL=adb` makes `core/ocr.py` take the adb capture path, which skips the
  Linux-only v4l2loopback/sudo bootstrap AND skips an interactive prompt at module scope.
- `WOS_ADB_SERIAL` is read by `cmd_program/screen_action.py::resolve_device()`.
- The readiness loop exists because PaddleOCR downloads models on first run; without it
  `Main/main.py` races the server and hits connection-refused.
- The `trap` exists so Ctrl-C does not orphan the background OCR server.
- The dimension gate is a HARD failure. Resolution mismatch is this ecosystem's most
  common silent failure and it produces mis-taps, not errors.

## Verification you must run

    cd /Users/melsawah1/Developer/wos-bot
    bash -n run.sh && echo "run.sh: syntax OK"
    test -x run.sh && echo "run.sh: executable"
    uv run python -c "import psutil; print('psutil', psutil.__version__)"
    uv run python -c "
    import re
    src = open('core/ocr.py').read()
    assert 'psutil.Process().memory_info().rss' in src, 'psutil RSS call missing'
    assert 'getrusage' not in src, 'getrusage must NOT be used'
    assert '/proc/self/status' not in src, '/proc read must be gone'
    print('ocr.py RSS sensor: OK')"
    grep -n '_enforce_ram_cap' core/ocr.py

`adb` is NOT installed yet, so do NOT execute `run.sh` — `bash -n` (syntax check) only.
Do NOT import `core.ocr` — it hits an interactive prompt at module scope and will hang.
Verify your ocr.py edit by reading the file, as the assertion snippet above does.

## Constraints

- Edit only `core/ocr.py`, `pyproject.toml`, `uv.lock` (via `uv add`), and create `run.sh`.
- Do NOT touch `cmd_program/screen_action.py` — previous batches own it and it is correct.
- Do NOT add tests or a test framework — a later batch owns that.

Two commits please: one starting `T7: `, one starting `T8: `.
