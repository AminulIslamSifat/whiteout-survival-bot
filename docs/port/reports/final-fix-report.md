# Final whole-branch review — fix report

FIX_BASE = 4fc3e11. Branch `mac-port`. All five findings fixed in one pass.

## 1. CRITICAL — the launcher cannot start the OCR server

**Fixed in:**
- `run.sh:18` — `uv run core/ocr.py &` -> `uv run python -m core.ocr &`
- `README.md:145` — `uv run core/ocr.py` -> `uv run python -m core.ocr` (Terminal section)
- `README.md:227` — same, PowerShell section
- `README.md:445` — same, troubleshooting section

No sys.path manipulation added. Pure module-form invocation, as instructed.

## 2. IMPORTANT — UnboundLocalError masks every new device error

**Fixed in:** `core/ocr.py`, `run_ocr()`, around line 680-687.

- Added `img = None` immediately before the `try:` block, so the later
  `if img is None:` check can no longer raise `UnboundLocalError` when
  `_capture_frame()` raises before assigning `img`.
- Added `raise RuntimeError(f"OCR capture failed: {e}") from e` in the
  `except Exception as e:` handler, so the original clear device error
  (e.g. `"no adb device available (WOS_ADB_SERIAL=...)"`) propagates out of
  `run_ocr()` instead of being silently swallowed into an empty-result
  return. Previously, once `img = None` fixed the crash, the exception
  handler's `print()`-and-fall-through would have turned every capture
  failure into a silent `200 OK` with zero results — this re-raise keeps
  the failure visible to the caller.

Diff:
```python
     img = None
     try:
         capture_start = time.perf_counter()
         img = _capture_frame(img_path, save_frame=save_frame)
         capture_time_s = time.perf_counter() - capture_start
     except Exception as e:
         print(f"Error - {e}")
+        raise RuntimeError(f"OCR capture failed: {e}") from e

     if img is None:
         return []
```

## 3. IMPORTANT — WOS_ADB_SERIAL silently substitutes a different device

**Fixed in:** `cmd_program/screen_action.py:47-60`, `resolve_device()`.

Reversed the earlier decision: when `WOS_ADB_SERIAL` is set but the serial is
NOT present in `adb devices`, `resolve_device()` now raises a `RuntimeError`
naming the requested serial and listing what was actually found, instead of
silently falling back to `devices[0]`. An unset `WOS_ADB_SERIAL` still falls
back to `devices[0]` unchanged.

```python
    if preferred and preferred in devices:
        _device_id = preferred
    elif preferred:
        # Silently substituting a different device here would let taps land on
        # the wrong screen with no error at all -- fail loudly instead.
        raise RuntimeError(
            f"WOS_ADB_SERIAL={preferred!r} not found in adb devices; "
            f"found: {devices!r}"
        )
    elif devices:
        _device_id = devices[0]
```

**Test updated:** `tests/test_device.py`
- Renamed `test_wos_adb_serial_set_but_absent_falls_back_to_first_device` ->
  `test_wos_adb_serial_set_but_absent_raises_loudly` (line ~52). It now
  asserts `pytest.raises(RuntimeError, match="stale-serial")` instead of the
  old fallback-to-`devices[0]` assertion. This intentionally reverses the
  previous test's expectation — the reviewer's call, confirmed by the
  requester.
- Added a new, separate test
  `test_wos_adb_serial_unset_falls_back_to_first_device` (line ~62) that
  proves an unset `WOS_ADB_SERIAL` with multiple devices present still
  chooses `devices[0]`, so that behavior stays explicitly covered even
  though the loud-failure test no longer covers it as a side effect.

No real `adb` binary is touched by any test — `get_adb_devices()` stays
monkeypatched throughout, per the existing test file's own docstring
contract.

## 4. IMPORTANT — dormancy lives only in run.sh

**Fixed in:** `core/ocr.py:85` and the comment above `_get_process_rss_bytes()`
(around line 250-254).

- `RAM_CAP_GB = float(os.getenv("OCR_RAM_CAP_GB", "3.0"))` ->
  `RAM_CAP_GB = float(os.getenv("OCR_RAM_CAP_GB", "16.0"))`. The
  `OCR_RAM_CAP_GB` env override is unchanged; only the in-code default moved
  from 3.0 to 16.0, so anyone launching `core/ocr.py` (or `python -m
  core.ocr`) directly, bypassing `run.sh`, still gets the dormant actuator
  by default.
- Updated the comment immediately above so it states that the in-code
  default itself (16.0) is now the dormancy mechanism, that
  `OCR_RAM_CAP_GB` still overrides it explicitly, and that the in-code
  default should be lowered to 3 once the daily loop is stable.

`run.sh:6` (`export OCR_RAM_CAP_GB="${OCR_RAM_CAP_GB:-16}"`) is unchanged —
it already exported 16 and continues to do so; it's now merely redundant
with the new in-code default rather than being the only thing keeping the
actuator dormant.

## 5. IMPORTANT — readiness loop does not fail

**Fixed in:** `run.sh`, immediately after the readiness-wait loop (was
lines ~22-26, now ~22-27).

Added a hard check after the loop that fails the script if the OCR server
never became ready:

```bash
for i in $(seq 1 120); do
  curl -sf localhost:8000/docs >/dev/null && break
  sleep 2
done
curl -sf localhost:8000/docs >/dev/null || { echo "FATAL: OCR server never came up"; exit 1; }

uv run python Main/main.py
```

`set -euo pipefail` is already active at the top of `run.sh` (line 2), so
this `exit 1` stops the script before `Main/main.py` ever launches into a
connection-refused OCR client.

## Scope

Only the five findings above were touched. Nothing else in the branch was
modified, per the reviewer's explicit note that the rest of the branch was
cleared.

## Verification — full unedited output

### `uv run pytest tests/ -q`

```
..............................                                           [100%]
=============================== warnings summary ===============================
.venv/lib/python3.12/site-packages/paddle/utils/cpp_extension/extension_utils.py:718
  /Users/melsawah1/Developer/wos-bot/.venv/lib/python3.12/site-packages/paddle/utils/cpp_extension/extension_utils.py:718: UserWarning: No ccache found. Please be aware that recompiling all source files may be required. You can download and install ccache from: https://github.com/ccache/ccache/blob/master/doc/INSTALL.md
    warnings.warn(warning_message)

-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
30 passed, 1 warning in 2.33s
```

### `bash -n run.sh && echo "run.sh syntax OK"`

```
run.sh syntax OK
```

### `grep -n "core.ocr\|core/ocr.py" run.sh README.md`

```
run.sh:18:uv run python -m core.ocr &
README.md:145:uv run python -m core.ocr
README.md:227:uv run python -m core.ocr
README.md:445:uv run python -m core.ocr
```

### `grep -n "OCR_RAM_CAP_GB" core/ocr.py run.sh`

```
run.sh:6:export OCR_RAM_CAP_GB="${OCR_RAM_CAP_GB:-16}"
core/ocr.py:85:RAM_CAP_GB = float(os.getenv("OCR_RAM_CAP_GB", "16.0"))
core/ocr.py:254:# on macOS. OCR_RAM_CAP_GB still overrides it if a caller sets it explicitly.
```

### `OCR_CAPTURE_TOOL=adb timeout 25 uv run python -m core.ocr 2>&1 | head -20`

```
/Users/melsawah1/Developer/wos-bot/.venv/lib/python3.12/site-packages/paddle/utils/cpp_extension/extension_utils.py:718: UserWarning: No ccache found. Please be aware that recompiling all source files may be required. You can download and install ccache from: https://github.com/ccache/ccache/blob/master/doc/INSTALL.md
  warnings.warn(warning_message)
PaddleOCR Version: 2.10.0
PaddlePaddle Version: 3.2.0
✅ Using Capture Tool from Env: ADB
/Users/melsawah1/Developer/wos-bot/references/icon
INFO:     Started server process [56548]
INFO:     Waiting for application startup.
INFO:     Application startup complete.
INFO:     Uvicorn running on http://127.0.0.1:8000 (Press CTRL+C to quit)
INFO:     Shutting down
INFO:     Waiting for application shutdown.
INFO:     Application shutdown complete.
INFO:     Finished server process [56548]
```

No `ImportError` and no "partially initialized module" anywhere in the
output — confirms finding 1 is fixed.

Note on what this run actually proves vs. the findings file's prediction:
the findings file expected this command to "eventually fail on the missing
adb device." In practice the server starts and serves successfully for the
full 25s `timeout` window without touching `adb` at all — `resolve_device()`
in `cmd_program/screen_action.py` is invoked lazily, only when an actual
`/ocr` or `/template` request comes in that needs to capture a frame, not at
import or server-startup time. So `timeout` killed the process cleanly
(`Shutting down` / graceful uvicorn exit), rather than the server crashing
on a missing device. This is a stronger result than what was asked for: it
proves the import path is clean AND that server startup has no hidden
dependency on `adb` being present, which is the only thing the verification
step needed to establish either way.

## Concerns

1. **Finding 2's fix changes externally-visible behavior slightly beyond
   pure bug-fixing.** Before this branch's device-error work (and even in
   the current buggy state), a capture failure inside `run_ocr()` was
   effectively swallowed into `return []` (a "clean" empty result) once the
   `UnboundLocalError` crash was worked around naively. My fix instead
   re-raises, so `/ocr` requests during a capture failure now raise a
   `RuntimeError` out of `run_ocr()` instead of returning an empty list.
   `ocr_endpoint()` (core/ocr.py:803-820) only special-cases `MemoryError`;
   any other exception — including this new `RuntimeError` — is currently
   uncaught there and will surface as FastAPI's default 500 response
   (`{"detail":"Internal Server Error"}`, no message body, since
   `FastAPI()` is constructed with default `debug=False` at core/ocr.py:103).
   This is not a regression introduced by my change and I did not touch
   `ocr_endpoint()` — it's out of scope per the "do not touch anything else"
   constraint, and finding 2 only asked for the `img = None` fix "so the
   real error message propagates" out of `run_ocr()` itself, which it now
   does (as a Python exception, visible in server logs via the existing
   `print(f"Error - {e}")` and as a proper exception type instead of an
   unrelated crash). Getting the message all the way into the raw HTTP
   response body would require adding an exception handler to
   `ocr_endpoint()`, which was not requested and would be scope creep.
2. No other concerns. All three programmatic verification commands and the
   manual import-path check reproduce cleanly; `adb` was never invoked by
   any test (confirmed via `grep -rn "WOS_ADB_SERIAL\|resolve_device"`
   across the repo — the only files touching it are
   `cmd_program/screen_action.py` and `tests/test_device.py`, and the test
   file monkeypatches `get_adb_devices()` in every test).
