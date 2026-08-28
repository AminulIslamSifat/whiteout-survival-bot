# Batch A — Unify the coordinate space on core/coord_utils

## Why this exists

Three files declare the same 1080x2460 base resolution and one has drifted:
- `core/coord_utils.py:7-9` — `BASE_WIDTH = 1080`, `BASE_HEIGHT = 2460` (canonical; its
  docstring calls itself the base resolution)
- `cmd_program/screen_action.py:9-10` — `SCREEN_WIDTH = 1080`, `SCREEN_HEIGHT = 2460`
- `core/ocr.py:85-86` — `STREAM_WIDTH = 1080`, `STREAM_HEIGHT = 2456`  <-- DRIFTED

Consequence: `_normalize_frame_resolution()` (core/ocr.py:152-160) resizes EVERY captured
frame to 2456, including on the adb path (core/ocr.py:304). Then core/ocr.py:678-679
applies a hardcoded `y1 = y1 - 5` fudge to compensate. Taps were always correct (they use
SCREEN_HEIGHT=2460). The OCR path squashes the frame 0.16% and band-aids the drift.

## Exact changes

### 1. cmd_program/screen_action.py:9-10
Replace the two module-level constants with an import from the canonical module:

    from core.coord_utils import BASE_WIDTH, BASE_HEIGHT

Update the uses inside `_convert_if_percentage` call sites in this file
(`tap_screen` :73-74, `swipe_screen` :90-93, `long_press` :112-113) to pass
`BASE_WIDTH` / `BASE_HEIGHT` instead of `SCREEN_WIDTH` / `SCREEN_HEIGHT`.

Import safety (already verified, do not re-litigate): `core/coord_utils.py` imports
nothing at all, all three `__init__.py` files are empty, and `core/core.py:12,14` already
imports from BOTH `cmd_program.screen_action` AND `core.coord_utils`. No cycle is created.

### 2. core/ocr.py — _normalize_frame_resolution
Make it normalise against the canonical base, not STREAM_*. Add the import and change
the three references inside the function (:157 comparison, :160 resize target):

    from core.coord_utils import BASE_WIDTH, BASE_HEIGHT

Result: a 1080x2460 frame now early-returns at :157 instead of being resized.

### 3. core/ocr.py:85-86 — LEAVE STREAM_WIDTH / STREAM_HEIGHT IN PLACE
Do NOT delete them and do NOT change 2456. They are still passed to
`start_screen_stream()` at core/ocr.py:210-213 for the scrcpy path. On Linux 2456 may
genuinely be scrcpy's output height; repurposing it would change upstream behaviour we
cannot verify from a Mac. Add a short comment above them saying exactly that.

### 4. core/ocr.py:678-679 — DELETE the fudge
Remove these two lines and the comment above them:

    #a slight adjustment so that it could take scrcpy image to with a res of 1080x2456
    y1 = y1 - 5
    y2 = y2

(`y2 = y2` is a no-op; remove it too.)

### 5. core/ocr.py — add this diagram as a comment directly above _normalize_frame_resolution

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
    #   PaddleOCR -> text + coords
    #     v
    #   tap_screen(x%, y%)             _convert_if_percentage(y, BASE_HEIGHT)
    #     v
    #   adb shell input tap -> MuMu @ 1080x2460
    #
    # Historical bug: this function normalised to STREAM_HEIGHT=2456 while taps used
    # 2460, so the vision leg ran 0.16% short and ocr.py:678 carried a `y1 -= 5` fudge
    # to compensate. Both are gone. BASE_* in core/coord_utils is the single authority.

## Constraints

- Do NOT touch `cmd_program/screen_action.py:40-47` (device binding), `:51-56`
  (run_adb_command), `:124-137` (take_screenshot), or `:150-157` (input_text).
  A separate batch owns those; edits there will collide.
- Do NOT add a test framework or tests. A later batch owns that.
- Do NOT reformat, re-order imports, or "improve" adjacent code. Surgical only.
- Preserve the existing `_convert_if_percentage` semantics exactly (int -> pixels,
  float 0-100 -> percentage). Do not "fix" that ambiguity; it is deliberately out of scope.

## Verification you must run

    cd /Users/melsawah1/Developer/wos-bot
    uv run python -c "
    import numpy as np
    from core.coord_utils import BASE_WIDTH, BASE_HEIGHT
    print('base', BASE_WIDTH, BASE_HEIGHT)
    from cmd_program import screen_action as sa
    print('pct->px', sa._convert_if_percentage(50.0, BASE_HEIGHT), 'expect 1230')
    print('int passthrough', sa._convert_if_percentage(1230, BASE_HEIGHT), 'expect 1230')
    "

Importing `core.ocr` will HANG on an interactive prompt (core/ocr.py:848 calls
take_preferred_screen_capture_tool at module scope). Do NOT import core.ocr to verify.
Verify your ocr.py edits by reading the file back, not by importing it.

Then commit. One commit, message starting `T4: `.
