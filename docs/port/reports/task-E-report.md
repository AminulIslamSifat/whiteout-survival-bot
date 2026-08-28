# Task E report — pytest suite (T9)

Status: **DONE**
Commit: `faedea2` on branch `mac-port`

## Files created

All new files are under `tests/` (plural), leaving the existing `test/` (singular, manual
scripts) directory untouched as instructed.

- **`tests/conftest.py`** — Sets `OCR_CAPTURE_TOOL=adb` via `os.environ.setdefault` at module
  top level, before anything else, so any test module that imports `core.ocr` never hits the
  interactive `Prompt.ask` in `take_preferred_screen_capture_tool()` (core/ocr.py:870 calls it
  at module scope). Also inserts the repo root onto `sys.path` — this was required (see
  "Deviation from brief" below) because `tests/` has no `__init__.py`, so pytest's default
  "prepend" import mode puts `tests/` itself on `sys.path`, not the repo root, and bare
  `import core...` / `import cmd_program...` failed with `ModuleNotFoundError` without it.

- **`tests/test_coords.py`** — Tests `core/coord_utils.py`: `pixel_to_percent` ->
  `percent_to_pixel` round-trips (tolerance ±1 pixel per axis, since `percent_to_pixel`
  truncates via `int()`), the 0 and full-extent (1080×2460 -> 100%) boundaries in both
  directions, and `box_pixel_to_percent` / `box_percent_to_pixel` round-tripping a box.

- **`tests/test_normalize.py`** — Tests `core/ocr.py::_normalize_frame_resolution`, the guard
  that makes the historical 2456-vs-2460 coordinate drift impossible to reintroduce silently.
  A frame already at `(BASE_HEIGHT, BASE_WIDTH, 3)` must come back as the *identical* object
  (`result is frame`, no resize/copy) — verified per the brief's already-measured fact. An
  off-height frame `(2400, 1080, 3)` and an off-width frame `(2460, 1000, 3)` both come back
  at `(2460, 1080)`. `None` in -> `None` out.

- **`tests/test_convert.py`** — Tests `cmd_program/screen_action.py::_convert_if_percentage`
  as it deliberately stands (int always passes through via `int()`; float in `[0,100]` is
  treated as a percentage; float `>100` is just cast to int, not scaled): int passthrough,
  `50.0` with max `2460` -> `1230`, `1500.0` -> `1500` (not scaled), and the `0.0`/`100.0`
  boundaries. No source change attempted — the int-vs-float ambiguity is explicitly out of
  scope per the brief.

- **`tests/test_device.py`** — Tests lazy adb device resolution in
  `cmd_program/screen_action.py` (`resolve_device`, `invalidate_device`, `WOS_ADB_SERIAL`).
  Monkeypatches `sa.get_adb_devices` (never touches `subprocess`/`adb` directly). An autouse
  fixture resets `sa._device_id = None` and clears `WOS_ADB_SERIAL` before/after every test.
  Covers: no devices -> `None`; one device -> returned and cached (second call with
  `get_adb_devices` replaced by a function that raises, or that returns `[]`, still returns
  the cached serial); `WOS_ADB_SERIAL` present in the device list wins over `devices[0]`;
  `WOS_ADB_SERIAL` set but absent falls back to `devices[0]`; `invalidate_device()` clears the
  cache so the next call re-probes; `resolve_device(force=True)` re-probes even when cached.

- **`tests/test_input.py`** — Tests `cmd_program/screen_action.py::input_text`, locking down
  the fix for the bug where `input_text` used to call `clear_input(count=..., device_id=...)`
  while `clear_input` has no `device_id` parameter, so every call raised `TypeError` (only
  live caller: `usecases/gather.py:112` -> `input_text("8")`). Monkeypatches
  `sa.run_adb_command` to record calls (and sets `sa._device_id` to a fake serial so no real
  probing is attempted). Asserts: `input_text("8")` does not raise; the recorded calls include
  `["shell", "input", "text", "8"]` and end with `["shell", "input", "keyevent", "66"]`; the
  default `backspace=6` produces exactly six `keyevent 67` calls plus one `keyevent 123`; and
  `inspect.signature(input_text)` is exactly `(text, backspace=6)` with no `device_id` param.

## Files deleted

- **`test_coords.py`** (repo root) — `git rm`'d. It was assertion-free: it printed four
  coordinate conversions and then unconditionally printed
  "✓ All coordinate conversion utilities working correctly!" regardless of what those
  conversions actually returned. Replaced by `tests/test_coords.py`.

## Files modified

- **`pyproject.toml`** — `/opt/homebrew/bin/uv add --dev pytest` added:
  ```toml
  [dependency-groups]
  dev = [
      "pytest>=9.1.1",
  ]
  ```
- **`uv.lock`** — additive diff only, `+42/-0` lines, adding `pytest`, `pluggy`, `iniconfig`.

## Lockfile integrity check

Used the explicit Homebrew `uv` binary as the brief warned (PATH's `uv` resolves to
`/Users/melsawah1/.local/bin/uv` 0.6.16, older than this repo's lockfile revision 3, and a
bare `uv add` with it would silently downgrade `uv.lock` to revision 2):

```
$ /opt/homebrew/bin/uv add --dev pytest
Resolved 71 packages in 1.83s
Prepared 3 packages in 795ms
Installed 3 packages in 4ms
 + iniconfig==2.3.0
 + pluggy==1.6.0
 + pytest==9.1.1
```

```
$ grep -m1 revision uv.lock
revision = 3

$ git diff --stat uv.lock
 uv.lock | 42 ++++++++++++++++++++++++++++++++++++++++++
 1 file changed, 42 insertions(+)
```

Revision is still 3, diff is small and purely additive (42 lines, not the ~1838-line rewrite
the brief warned about). No revert/retry was needed.

## Complete, unedited output of `uv run pytest tests/ -v`

```
============================= test session starts ==============================
platform darwin -- Python 3.12.11, pytest-9.1.1, pluggy-1.6.0 -- /Users/melsawah1/Developer/wos-bot/.venv/bin/python3
cachedir: .pytest_cache
rootdir: /Users/melsawah1/Developer/wos-bot
configfile: pyproject.toml
plugins: anyio-4.13.0
collecting ... collected 29 items

tests/test_convert.py::test_int_passes_through_unchanged PASSED          [  3%]
tests/test_convert.py::test_float_in_percentage_range_is_treated_as_percentage PASSED [  6%]
tests/test_convert.py::test_float_above_100_is_cast_not_scaled PASSED    [ 10%]
tests/test_convert.py::test_lower_boundary_zero PASSED                   [ 13%]
tests/test_convert.py::test_upper_boundary_100 PASSED                    [ 17%]
tests/test_convert.py::test_int_zero_passes_through PASSED               [ 20%]
tests/test_coords.py::test_base_resolution_is_1080x2460 PASSED           [ 24%]
tests/test_coords.py::test_pixel_percent_round_trip PASSED               [ 27%]
tests/test_coords.py::test_pixel_to_percent_zero_boundary PASSED         [ 31%]
tests/test_coords.py::test_pixel_to_percent_full_extent_boundary PASSED  [ 34%]
tests/test_coords.py::test_percent_to_pixel_zero_boundary PASSED         [ 37%]
tests/test_coords.py::test_percent_to_pixel_full_extent_boundary PASSED  [ 41%]
tests/test_coords.py::test_box_round_trip PASSED                         [ 44%]
tests/test_coords.py::test_box_percent_to_pixel_full_box PASSED          [ 48%]
tests/test_device.py::test_no_devices_returns_none PASSED                [ 51%]
tests/test_device.py::test_one_device_is_returned_and_cached PASSED      [ 55%]
tests/test_device.py::test_one_device_cache_survives_empty_reprobe PASSED [ 58%]
tests/test_device.py::test_wos_adb_serial_set_and_present_wins_over_first_device PASSED [ 62%]
tests/test_device.py::test_wos_adb_serial_set_but_absent_falls_back_to_first_device PASSED [ 65%]
tests/test_device.py::test_invalidate_device_clears_cache_and_forces_reprobe PASSED [ 68%]
tests/test_device.py::test_force_true_reprobes_even_when_cached PASSED   [ 72%]
tests/test_input.py::test_input_text_signature_has_no_device_id_param PASSED [ 75%]
tests/test_input.py::test_input_text_does_not_raise PASSED               [ 79%]
tests/test_input.py::test_input_text_sends_text_and_trailing_keyevent_66 PASSED [ 82%]
tests/test_input.py::test_input_text_backspace_default_clears_six_times PASSED [ 86%]
tests/test_normalize.py::test_frame_already_at_base_resolution_is_returned_unchanged PASSED [ 89%]
tests/test_normalize.py::test_off_height_frame_is_resized_to_base_resolution PASSED [ 93%]
tests/test_normalize.py::test_off_width_frame_is_resized_to_base_resolution PASSED [ 96%]
tests/test_normalize.py::test_none_frame_returns_none PASSED             [100%]

=============================== warnings summary ===============================
.venv/lib/python3.12/site-packages/paddle/utils/cpp_extension/extension_utils.py:718
  /Users/melsawah1/Developer/wos-bot/.venv/lib/python3.12/site-packages/paddle/utils/cpp_extension/extension_utils.py:718: UserWarning: No ccache found. Please be aware that recompiling all source files may be required. You can download and install ccache from: https://github.com/ccache/ccache/blob/master/doc/INSTALL.md
    warnings.warn(warning_message)

-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
======================== 29 passed, 1 warning in 2.39s =========================
```

29 passed, 0 failed, 0 skipped. Re-ran a second time (`-q --tb=short`) to confirm no
flakiness — same result, 1.62s.

Confirmed `adb` is genuinely absent on this machine before and after the run:
```
$ which adb
adb not found
```
No `adb` was stubbed on `PATH`; every place a test needed adb behavior it monkeypatched
`cmd_program.screen_action.get_adb_devices` or `cmd_program.screen_action.run_adb_command`
directly, per the brief's explicit instruction not to stub `adb` on PATH.

## Deviation from brief (not a source change — test-side only)

The brief's test descriptions imply `tests/test_coords.py` etc. would import cleanly with
just `tests/conftest.py` setting the env var. In practice, pytest's default "prepend" import
mode (since `tests/` has no `__init__.py`) put `tests/` on `sys.path`, not the repo root, so
`import core.coord_utils` / `import cmd_program.screen_action` raised
`ModuleNotFoundError: No module named 'core'` / `'cmd_program'` on the first run. Fixed by
adding one `sys.path.insert(0, <repo root>)` line to `tests/conftest.py` — a test-side fix,
well within the "only files under tests/ may be created" constraint, no source under
`core/`, `cmd_program/`, `usecases/`, or `Main/` was touched. Verified the fix by re-running
the suite, which then collected and passed all 29 tests.

## Verified-not-touched (per T9's own already-confirmed facts)

- `_normalize_frame_resolution` returns the identical object for a 1080×2460 frame — reran
  this exact check standalone before writing the test (see transcript below) and it passed
  on the first try, matching what was already verified. No regression, nothing to report.
  ```
  $ time OCR_CAPTURE_TOOL=adb uv run python3 -c "... _normalize_frame_resolution(frame) ..."
  identity: True
  resized shape: (2460, 1080, 3)
  none: None
  ... 2.646 total
  ```
- `OCR_CAPTURE_TOOL=adb` import of `core.ocr` completes in ~2.6s with no prompt, printing
  `✅ Using Capture Tool from Env: ADB` — matches the brief's measured fact exactly.

## Things noticed but not touched (out of scope for T9)

- **`.gitignore`** had an uncommitted modification (`+.superpowers/`) already present in the
  working tree before this task started (visible in `git status` at the very start of the
  session). This is not part of T9's scope (tests/, root `test_coords.py`,
  pyproject/lock-from-pytest only), so it was deliberately left unstaged and is NOT included
  in the T9 commit. It remains as a dangling working-tree change for whoever owns it.
- `core/ocr.py` builds a full PaddleOCR engine and imports `paddle`/`paddleocr`/`cv2` etc. at
  module scope purely as a side effect of importing `_normalize_frame_resolution`. This is
  what the brief already flagged as "solved" via `OCR_CAPTURE_TOOL=adb`, and it is — but it
  does mean `tests/test_normalize.py` is the slow module in the suite (though still ~2.4s
  total for the whole 29-test suite, well within reason). No action taken; brief explicitly
  said not to stub the engine build.
- `usecases/gather.py:112` is confirmed (by direct read) as the sole live caller of
  `input_text`, called as `input_text("8")` with no `device_id` argument — consistent with
  the brief and with the signature `tests/test_input.py` locks down.
- No other test-shaped files were found outside `test/` (singular, left untouched) and the
  now-deleted root `test_coords.py`.

## Concerns

None. No source file under `core/`, `cmd_program/`, `usecases/`, or `Main/` was modified.
Every test passes against the code exactly as it stands. No `time.sleep`, no wall-clock or
ordering dependence, no adb binary or emulator required, no network access required.
