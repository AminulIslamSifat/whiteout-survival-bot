# Final whole-branch review — findings to fix

FIX_BASE = 4fc3e11. Fix ALL of these in one pass, then run the full suite.

## 1. CRITICAL — the launcher cannot start the OCR server

CONTROLLER-VERIFIED, not a hypothesis:
    OCR_CAPTURE_TOOL=adb uv run core/ocr.py
    -> ImportError: cannot import name 'tap_screen' from partially initialized module
       'cmd_program.screen_action' (most likely due to a circular import)

    OCR_CAPTURE_TOOL=adb uv run python -m core.ocr
    -> INFO: Uvicorn running on http://127.0.0.1:8000   (works)

Root cause: running `core/ocr.py` AS A SCRIPT puts `<repo>/core` at sys.path[0]. An
earlier commit on this branch added `from core.coord_utils import BASE_WIDTH, BASE_HEIGHT`
to cmd_program/screen_action.py. With `<repo>/core` first on the path, the name `core`
resolves to `core/core.py` (the module) instead of the `core/` package, and core/core.py
imports back into the half-initialised screen_action. Circular import.

Fix:
- `run.sh:17` — change `uv run core/ocr.py` to `uv run python -m core.ocr`
- `README.md` lines 145, 227 and 445 — same change, all three occurrences.

Do NOT "fix" this by adding more sys.path manipulation. The module form is correct.

## 2. IMPORTANT — UnboundLocalError masks every new device error

`core/ocr.py` around lines 678-685: `img` is bound only inside the `try`. If
`_capture_frame` raises, the later reference raises `UnboundLocalError`, so the clear
device errors this branch just added ("no adb device available (WOS_ADB_SERIAL=...)")
reach the HTTP client as an opaque 500 instead of their message.

Fix: initialise `img = None` before the `try`, and handle the None case so the real
error message propagates.

## 3. IMPORTANT — WOS_ADB_SERIAL silently substitutes a different device

`cmd_program/screen_action.py:47-53`: when `WOS_ADB_SERIAL` is set but NOT present in
`adb devices`, resolution silently falls back to `devices[0]`.

I originally specified that fallback and I am REVERSING that decision. The reviewer is
right and I was wrong. `run.sh:12` gates the framebuffer of the NAMED serial only. If
resolution then picks a different device, `_normalize_frame_resolution` rescales that
other device's frames to 1080x2460 and taps land on the wrong device — with no error
at all. That is precisely the silent-failure pathology this whole branch exists to remove.

Fix: if `WOS_ADB_SERIAL` is set and that serial is NOT in the device list, raise a clear
RuntimeError naming the requested serial and listing what was actually found. Do not
substitute. An unset `WOS_ADB_SERIAL` still falls back to `devices[0]` as before.

`tests/test_device.py` currently asserts the OLD fallback behaviour (around line 73).
Update that test to assert the new loud failure. Keep a separate test proving that with
`WOS_ADB_SERIAL` UNSET, `devices[0]` is still chosen.

## 4. IMPORTANT — dormancy lives only in run.sh

`core/ocr.py:85` still defaults `OCR_RAM_CAP_GB` to `3.0`. The RAM sensor is now repaired,
so anyone launching without run.sh gets a working sensor that ARMS
`_reinitialize_ocr_engine()` — a teardown/rebuild path that has never executed on macOS —
at 3GB. The whole point of the split was that the sensor reports honestly while the
actuator stays dormant during the port.

Fix: change the in-code default to `16.0`, keeping the `OCR_RAM_CAP_GB` env override.
Update the nearby comment so it says the default itself is the dormancy mechanism and
should be lowered to 3 once the daily loop is stable.

## 5. IMPORTANT — readiness loop does not fail

`run.sh` lines ~22-26: if the OCR server never comes up, the loop simply ends after ~4
minutes and `Main/main.py` launches anyway into connection-refused. Combined with
finding 1 this produced a four-minute wait followed by a full run of "OCR failed".

Fix: make the loop's exhaustion fatal, e.g.
    for i in $(seq 1 120); do
      curl -sf localhost:8000/docs >/dev/null && break
      sleep 2
    done
    curl -sf localhost:8000/docs >/dev/null || { echo "FATAL: OCR server never came up"; exit 1; }

## Constraints

- Do not touch anything else. The reviewer explicitly cleared the rest of the branch.
- The full suite must pass: `uv run pytest tests/ -q`.
- Use `/opt/homebrew/bin/uv` for any lockfile-mutating command (the uv on PATH is 0.6.16
  and silently downgrades uv.lock revision 3 -> 2). You should not need one.

## Verification you must run and paste in full

    cd /Users/melsawah1/Developer/wos-bot
    uv run pytest tests/ -q
    bash -n run.sh && echo "run.sh syntax OK"
    grep -n "core.ocr\|core/ocr.py" run.sh README.md
    grep -n "OCR_RAM_CAP_GB" core/ocr.py run.sh
    # prove the launcher's import path now works (it will fail later on missing adb,
    # which is expected and fine — we only care that it gets PAST the import):
    OCR_CAPTURE_TOOL=adb timeout 25 uv run python -m core.ocr 2>&1 | head -20

The last command must NOT show ImportError or "partially initialized module".

One commit, message starting `fix: `.
