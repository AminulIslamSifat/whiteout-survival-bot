# Batch B — Rewrite the adb device layer in cmd_program/screen_action.py

Combines three plan tasks that all rewrite the same layer: T5 (lazy device resolution),
T6 (input_text fix), T11 (error hardening). They are one change, not three.

## Blast radius (already verified — do not re-check)

`device_id`, `run_adb_command` and `get_adb_devices` are used ONLY inside
`cmd_program/screen_action.py`. No other module imports them. Other modules import only
the public action functions: `tap_screen`, `swipe_screen`, `long_press`,
`take_screenshot`. Their signatures MUST NOT change.

Current internal call sites of the module-global `device_id`: lines 74, 95, 115, 122,
140, 143, 152, 153.

## Problem 1 — device_id binds once at import and never rebinds

`screen_action.py:37-44` runs `get_adb_devices()` at MODULE SCOPE and binds `device_id`
once. Consequences:
- `core/ocr.py:36` imports this module, so merely starting the OCR server fires an
  `adb devices` probe.
- If adb was not connected at import, `device_id` is None for the process lifetime and
  `:122` builds `["adb", "-s", "None", "exec-out", "screencap", "-p"]` forever.
  Reconnecting adb later does NOT help. Only a restart does.
- A device that drops mid-run is never re-detected.

### Required

Replace the module-scope binding with lazy resolution. After this change, importing
`cmd_program.screen_action` MUST NOT run any adb command. That property is required by a
later batch that adds offline tests.

    _device_id = None

    def resolve_device(force=False):
        """Resolve the adb serial lazily. Re-probes when the cache is empty or forced."""
        global _device_id
        if force:
            _device_id = None
        if _device_id is not None:
            return _device_id
        preferred = os.getenv("WOS_ADB_SERIAL")
        devices = get_adb_devices()
        if preferred and preferred in devices:
            _device_id = preferred
        elif devices:
            _device_id = devices[0]
        else:
            _device_id = None
        return _device_id

    def invalidate_device():
        """Drop the cached serial so the next call re-probes."""
        global _device_id
        _device_id = None

Rules:
- `WOS_ADB_SERIAL` is exported by `run.sh` (a later batch) as `127.0.0.1:<port>`.
  Honour it when it is present AND currently connected; otherwise fall back to
  `devices[0]`.
- DELETE the hardcoded serial branch at `:41-42` (`"13139385O0003802"`). It is the
  original author's phone and never matches here.
- Keep the "no devices" message, but only print it when a resolution actually fails —
  not at import.
- `get_adb_devices()` itself stays as-is.

## Problem 2 — a cached serial cannot detect a dropped device

Required: when an adb command FAILS, invalidate the cache so the next call re-probes.
Wire `invalidate_device()` into `run_adb_command`'s failure path and
`take_screenshot`'s failure path. This is the mechanism that makes a mid-run MuMu sleep
recoverable instead of terminal.

## Problem 3 — error handling flattens every adb failure (T11)

`run_adb_command` at `:48-53` catches bare `Exception` and re-raises one generic
`RuntimeError(f"adb command failed - {e}")`. "Emulator asleep", "device unauthorised"
and "bad command syntax" become indistinguishable.

### Required for run_adb_command

    def run_adb_command(cmd, device_id=None):

- Resolve the serial via `resolve_device()` when `device_id` is None.
- Raise a clear `RuntimeError` naming the serial when no device can be resolved.
- Catch `subprocess.CalledProcessError` SPECIFICALLY. On it: call `invalidate_device()`,
  then raise `RuntimeError` including the serial, the command that failed, the exit
  code, and stderr if captured.
- Catch `FileNotFoundError` separately — that means the `adb` binary is not installed,
  which is a different problem with a different fix. Say so in the message.
- Do NOT keep a bare `except Exception`.

### Required for take_screenshot (`:121-134`)

- Resolve the serial the same way; use it in the command at `:122`.
- Wrap `subprocess.check_output` at `:123`: catch `CalledProcessError` (invalidate the
  cache, raise with serial + exit code + stderr) and `FileNotFoundError` (adb missing).
- The decode failure at `:128-129` currently raises the bare string
  `"Failed to decode the image"`. Give it real context: the serial and the number of
  bytes actually received. A truncated screencap and a missing device look identical
  today.
- Keep the `save=False` behaviour and the `cache/` write exactly as they are.

## Problem 4 — input_text is broken on every call (T6)

`:147-154`. Two stacked bugs:
1. `:151` calls `clear_input(count=backspace, device_id=device_id)` but `clear_input` is
   defined at `:139` as `def clear_input(count=6)` — it has NO `device_id` parameter.
   Every call raises `TypeError`.
2. `:147` defaults `device_id="131393852O003802"` — a second, differently typo'd serial
   (note it differs from the one at `:41`) that shadows the module global.

Its only live caller is `usecases/gather.py:112`, which calls `input_text("8")`.

### Required

    def input_text(text, backspace=6):

- Drop the `device_id` parameter entirely. Resolve internally.
- Fix the `clear_input` call to `clear_input(count=backspace)`.
- Keep the `text.replace(" ", "%s")` behaviour and the trailing keyevent 66 (Enter).
- `clear_input(count=6)` keeps its signature; it should resolve the device internally too.

## Constraints

- Do NOT change the signatures of `tap_screen`, `swipe_screen`, `long_press`, or
  `take_screenshot`. Other modules call them positionally.
- Do NOT touch `_convert_if_percentage` (`:10-14`) or the `BASE_WIDTH`/`BASE_HEIGHT`
  import at `:7`. A previous batch owns those and they are already correct.
- Do NOT add tests or a test framework — a later batch owns that.
- Do NOT edit any file other than `cmd_program/screen_action.py`.
- No bare `except Exception` anywhere in your diff.

## Verification you must run

`adb` is NOT installed on this machine yet. That is expected and is exactly what makes
the import-time property testable:

    cd /Users/melsawah1/Developer/wos-bot
    uv run python -c "
    import cmd_program.screen_action as sa
    print('IMPORT OK — no adb probe at import')
    print('cached serial at import:', sa._device_id, '(must be None)')
    import inspect
    print('input_text sig:', inspect.signature(sa.input_text))
    print('run_adb_command sig:', inspect.signature(sa.run_adb_command))
    try:
        sa.resolve_device()
        print('resolve_device returned:', sa._device_id)
    except Exception as e:
        print('resolve_device raised:', type(e).__name__, e)
    try:
        sa.input_text('8')
    except RuntimeError as e:
        print('input_text -> RuntimeError (correct, no device):', e)
    except TypeError as e:
        print('FAIL: input_text still raises TypeError:', e)
    "

Required outcomes: the import succeeds and prints `IMPORT OK`; `_device_id` is None at
import; `input_text` does NOT raise TypeError; `run_adb_command` accepts a single
positional arg.

Then commit. One commit, message starting `T5+T6+T11: `.
