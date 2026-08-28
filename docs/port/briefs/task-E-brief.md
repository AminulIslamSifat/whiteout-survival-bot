# Batch E — pytest suite (T9)

Last code batch. Adds the first real tests this repo has ever had.

## Why

`pyproject.toml` declares no test framework. The only test-shaped file is `test_coords.py`
at the repo ROOT, and it has NO assertions — it prints four conversions then prints
"✓ All coordinate conversion utilities working correctly!" unconditionally. It would print
that if every conversion returned zero. It is worse than no test: it looks like coverage.
DELETE it and replace it with the real thing.

## Installing pytest — READ THIS, IT IS A TRAP

PATH resolves `uv` to `/Users/melsawah1/.local/bin/uv` version 0.6.16, which is OLDER than
this repo's lockfile format. A bare `uv add` with it silently DOWNGRADES uv.lock from
revision 3 to 2 and rewrites ~1838 lines. Use the Homebrew binary explicitly:

    /opt/homebrew/bin/uv add --dev pytest

Afterwards CHECK: `grep -m1 revision uv.lock` must still say `revision = 3`, and
`git diff --stat uv.lock` must be a small additive diff (tens of lines, not thousands).
If it is not, revert uv.lock and retry with the explicit path.

`uv run` is unaffected by this and is safe to use normally.

## Import-time hazard, and how it is already solved

`core/ocr.py:848` calls `take_preferred_screen_capture_tool()` at MODULE SCOPE, which
prompts interactively. `core/ocr.py` also builds an OCR engine at module scope.

I have already verified the fix: setting `OCR_CAPTURE_TOOL=adb` in the environment BEFORE
import satisfies the env branch at core/ocr.py:118-122, skips the prompt entirely, and the
whole import completes in ~3 seconds. It prints "✅ Using Capture Tool from Env: ADB".

So `tests/conftest.py` must set that env var at module top level, before anything else:

    import os
    os.environ.setdefault("OCR_CAPTURE_TOOL", "adb")

pytest imports conftest.py before collecting test modules, so this is sufficient. You do
NOT need to stub the engine build — it is fast and the models are already cached.

`cmd_program/screen_action.py` no longer touches adb at import (a previous batch made
device resolution lazy), so importing it is safe and needs no special handling.

## Tests to write, in tests/

### tests/conftest.py
The env var above, plus any shared fixtures you need.

### tests/test_coords.py  (core/coord_utils.py)
- `pixel_to_percent` -> `percent_to_pixel` round-trips within rounding for several points.
- Boundaries: 0, and the full extents 1080 (width) and 2460 (height) -> 100%.
- `box_pixel_to_percent` / `box_percent_to_pixel` round-trip on a box.

### tests/test_normalize.py  (core/ocr.py::_normalize_frame_resolution)  <-- THE IMPORTANT ONE
This is the test that makes the 2456/2460 drift impossible to reintroduce silently.
- A frame already at base height (numpy zeros, shape (2460, 1080, 3)) must be returned
  WITHOUT a resize. Assert identity: `result is frame`. I verified this passes.
- An off-height frame (e.g. (2400, 1080, 3)) must come back at (2460, 1080).
- `None` in -> `None` out.
Import BASE_WIDTH/BASE_HEIGHT from core.coord_utils rather than hardcoding 1080/2460, so
the test follows the single source of truth.

### tests/test_convert.py  (cmd_program/screen_action.py::_convert_if_percentage)
- int input passes through unchanged (e.g. 1230 -> 1230).
- float 0-100 is treated as a percentage (50.0 with max 2460 -> 1230).
- float > 100 is cast to int, NOT treated as a percentage (e.g. 1500.0 -> 1500).
- Boundaries 0.0 and 100.0.
Do NOT "fix" the int-vs-float ambiguity — it is deliberately out of scope. Test it as it is.

### tests/test_device.py  (cmd_program/screen_action.py device resolution)
Use monkeypatch on `cmd_program.screen_action.get_adb_devices` (simplest) or on
`subprocess.run`. Reset `sa._device_id = None` between cases.
- No devices -> `resolve_device()` returns None.
- One device -> returns it, and the result is CACHED (a second call with
  `get_adb_devices` now raising or returning [] still returns the cached serial).
- `WOS_ADB_SERIAL` set AND present in the device list -> that serial wins over devices[0].
- `WOS_ADB_SERIAL` set but NOT in the list -> falls back to devices[0] (a stale env var
  must not block a working device).
- `invalidate_device()` clears the cache so the next call re-probes.
- `resolve_device(force=True)` re-probes even when cached.

### tests/test_input.py  (cmd_program/screen_action.py::input_text)
The bug being locked down: `input_text` used to call `clear_input(count=..., device_id=...)`
while `clear_input` has no `device_id` parameter, so EVERY call raised TypeError. Its only
live caller is `usecases/gather.py:112` -> `input_text("8")`.
- Monkeypatch `run_adb_command` to record calls, and force a resolved device.
- `input_text("8")` must NOT raise TypeError.
- The recorded adb calls must include the text input and the trailing keyevent 66.
- `input_text` must have signature `(text, backspace=6)` — no `device_id` parameter.

## Constraints

- DELETE the root-level `test_coords.py` (the assertion-free one). `git rm` it.
- Do NOT modify any file under `core/`, `cmd_program/`, `usecases/` or `Main/`. If a test
  cannot pass without a source change, STOP and report it — do not change the source.
- Leave the existing `test/` directory (singular, with manual scripts) alone. Your new
  tests go in `tests/` (plural).
- Every test must pass with NO emulator, NO adb binary, and NO network.
- No `time.sleep` in tests. No test that depends on wall-clock or ordering.

## Verification you must run

    cd /Users/melsawah1/Developer/wos-bot
    uv run pytest tests/ -v

All tests must pass. Paste the complete output into your report. Then confirm the
lockfile was not mangled:

    grep -m1 revision uv.lock
    git diff --stat uv.lock

Then commit. One commit, message starting `T9: `.
