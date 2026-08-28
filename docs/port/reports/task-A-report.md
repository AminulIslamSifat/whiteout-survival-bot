# Task A Report — Unify coordinate space on core/coord_utils

Commit: `e1631c9` on branch `mac-port` ("T4: unify coordinate space on core.coord_utils BASE_WIDTH/BASE_HEIGHT")

## What changed and where

### 1. cmd_program/screen_action.py

- **Lines 4-10 (original)** → replaced the block
  ```
  # Screen dimensions for percentage calculations
  SCREEN_WIDTH = 1080
  SCREEN_HEIGHT = 2460
  ```
  with
  ```python
  from core.coord_utils import BASE_WIDTH, BASE_HEIGHT
  ```
  (new file: import now at line 7).

- **tap_screen** (was :73-74, now :70-71): `_convert_if_percentage(x, SCREEN_WIDTH)` /
  `(y, SCREEN_HEIGHT)` → `BASE_WIDTH` / `BASE_HEIGHT`.
- **swipe_screen** (was :90-93, now :87-90): all four `_convert_if_percentage` calls
  (`x1, y1, x2, y2`) switched from `SCREEN_WIDTH`/`SCREEN_HEIGHT` to `BASE_WIDTH`/`BASE_HEIGHT`.
- **long_press** (was :112-113, now :109-110): same substitution as tap_screen.

Did not touch device binding (:40-47), `run_adb_command` (:51-56), `take_screenshot`
(:124-137), or `input_text` (:150-157) — verified by re-reading the file after edits;
those regions are byte-identical to the pre-edit version except for the natural line-number
shift caused by removing 3 lines at the top of the file.

I initially let two blank lines (inside `tap_screen` and `long_press`, immediately after the
`_convert_if_percentage` calls) lose their trailing 4-space whitespace as an incidental
side effect of the Edit tool rewriting those blocks. Caught it in the diff review and
restored the trailing whitespace with `sed` so the only diff hunks are the semantic
`SCREEN_*` → `BASE_*` / import changes — no incidental reformatting.

### 2. core/ocr.py

- **Import block (~line 36-39)**: added `from core.coord_utils import BASE_WIDTH, BASE_HEIGHT`
  after the `cmd_program.screen_stream` imports, before `import paddleocr`.
- **STREAM_WIDTH / STREAM_HEIGHT (was :85-86, now :90-91)**: left the values (1080/2456)
  untouched exactly as instructed. Added a 4-line comment directly above them explaining
  they still feed `start_screen_stream()`'s Linux-only scrcpy path (call site now at
  :237-238, was :210-213) and are deliberately not unified with BASE_*, since 2456 may be
  scrcpy's genuine output height on Linux and that can't be verified from this Mac.
- **_normalize_frame_resolution (was :152-160, now :180-186)**: added the full coordinate-space
  diagram comment (verbatim from the brief) directly above the function definition, and
  changed the comparison (`w == STREAM_WIDTH and h == STREAM_HEIGHT`) and the resize target
  (`cv2.resize(frame, (STREAM_WIDTH, STREAM_HEIGHT), ...)`) to `BASE_WIDTH`/`BASE_HEIGHT`.
  A 1080x2460 frame now early-returns instead of being resized to 1080x2456.
- **run_ocr fudge (was :678-679, now deleted)**: removed
  ```python
  #a slight adjustment so that it could take scrcpy image to with a res of 1080x2456
  y1 = y1 - 5
  y2 = y2
  ```
  in full, including the comment and the no-op `y2 = y2` line. The `x1, y1, x2, y2 = roi`
  unpacking line and the following `# Only pad if the crop actually has dimensions` comment
  are unchanged and now sit adjacent to each other.

Confirmed via `grep -n "STREAM_WIDTH\|STREAM_HEIGHT\|BASE_WIDTH\|BASE_HEIGHT" core/ocr.py`
that the only remaining `STREAM_WIDTH`/`STREAM_HEIGHT` usages are the definition (with new
comment) and the `start_screen_stream(...)` call — i.e. exactly the scrcpy path the brief
said to leave alone. `_normalize_frame_resolution` uses only `BASE_*` now.

## Verification run

Per the brief, importing `core.ocr` hangs (module-scope `take_preferred_screen_capture_tool()`
at :848, now shifted but still present and unchanged) and it wasn't imported — verified by
reading the file back and running `python -m py_compile` instead of importing.

Ran exactly the command specified in the brief:

```
cd /Users/melsawah1/Developer/wos-bot
uv run python -c "
import numpy as np
from core.coord_utils import BASE_WIDTH, BASE_HEIGHT
print('base', BASE_WIDTH, BASE_HEIGHT)
from cmd_program import screen_action as sa
print('pct->px', sa._convert_if_percentage(50.0, BASE_HEIGHT), 'expect 1230')
print('int passthrough', sa._convert_if_percentage(1230, BASE_HEIGHT), 'expect 1230')
"
```

**First attempt failed** — not due to my changes. `cmd_program/screen_action.py` runs
`get_adb_devices()` at module scope (line 40 in the original file, an untouched region I'm
explicitly forbidden from editing — "device binding"), which shells out to `adb devices`.
This sandbox has no `adb` binary on `PATH` at all (`which adb` → not found), and
`subprocess.run(["adb", "devices"], ...)` raised `PermissionError: [Errno 13] Permission
denied: 'adb'` instead of the more usual `FileNotFoundError` — apparently this execution
sandbox denies exec of unknown/absent binaries named `adb` with EACCES rather than ENOENT.

I confirmed this is 100% pre-existing and unrelated to my edits: `git stash`'d my changes
and reproduced the identical `PermissionError` on the original, unmodified file importing
at the same line. Restored my changes with `git stash pop` afterward (confirmed via
`git status`).

To actually execute the brief's literal verification command, I added a no-op `adb` stub
script (`echo "List of devices attached"`) to a scratch directory and prepended it to
`PATH` for that one command only — no repository file was touched to work around this;
it only unblocks the pre-existing module-level `adb devices` probe so the import can
complete. This mirrors what would happen on a real Mac with `adb` installed but no phone
attached (the existing "No ADB devices found" message is expected, pre-existing UX, not
something this task owns).

**Full output (with the PATH-only workaround) — matches every expected value in the brief:**

```
base 1080 2460
❌ No ADB devices found. Please connect your phone, babe. 💋
pct->px 1230 expect 1230
int passthrough 1230 expect 1230
```

Additionally ran, to confirm both edited files are syntactically valid without importing
`core.ocr` (which would hang/crash on module-scope side effects unrelated to this task):

```
uv run python -m py_compile core/ocr.py cmd_program/screen_action.py core/coord_utils.py
```
→ `SYNTAX OK` (no output from py_compile itself, exit 0).

Also re-confirmed the brief's "no import cycle" claim directly rather than trusting it
blindly: `core/coord_utils.py` has zero import statements, both `core/__init__.py` and
`cmd_program/__init__.py` are empty (0 bytes), and `core/core.py:12,14` already imports from
both `cmd_program.screen_action` and `core.coord_utils` in the pre-existing, unmodified code.

## Things noticed but deliberately not touched

- `.gitignore` had a pre-existing uncommitted change (`+.superpowers/`) present in the
  working tree before I started (confirmed via `git status --short` as my very first
  action). Not part of this task; left unstaged and out of my commit.
- `grep -rn "SCREEN_WIDTH\|SCREEN_HEIGHT"` across the whole repo returns nothing after my
  edit — no other file referenced the old constants, so there was nothing else to update.
- The historical-bug comment I added above `_normalize_frame_resolution` says
  "ocr.py:678 carried a `y1 -= 5` fudge" — this is a narrative/historical reference to
  where the bug used to live before this same commit deletes it; it is not a live pointer
  and I used the brief's text verbatim as instructed.
- Did not touch `cmd_program/screen_action.py:40-47` (device resolution), `:51-56`
  (run_adb_command), `:124-137` (take_screenshot), `:150-157` (input_text) — confirmed
  by diff review, only line-number drift from the 3-line reduction at the top of the file.
- Did not add any tests or test framework.
- Did not reformat, reorder imports, or touch anything outside the exact lines specified,
  other than fixing the trailing-whitespace incident described above (self-corrected before
  committing).

## Concerns

- None regarding the actual code change — diff is surgical, matches the brief exactly,
  values verified.
- Environment-only concern: this sandbox lacks a real `adb` binary, so anyone re-running the
  brief's verification command here verbatim (without a PATH stub) will hit the same
  pre-existing `PermissionError` at module-import time, unrelated to this task's diff. Worth
  flagging to whoever owns the "device binding" batch (lines 40-47) since it means this
  module cannot be imported in this particular sandbox at all without an `adb` shim on PATH,
  though it's out of scope for this task to fix.
