# Task B report — adb device layer rewrite (T5 + T6 + T11)

Commit: `17cda1b` on branch `mac-port`
File touched: `cmd_program/screen_action.py` only (no other file edited).

## Every change, with file:line (post-commit line numbers in the new file)

All line numbers below refer to `/Users/melsawah1/Developer/wos-bot/cmd_program/screen_action.py` after the change.

1. **`:37-62` — Lazy device resolution replaces module-scope binding (Problem 1).**
   Deleted the old `:37-44` block that ran `get_adb_devices()` at import time
   and bound a module-global `device_id`, including the hardcoded
   `"13139385O0003802"` fallback branch (deleted per brief, T5 requirement).
   Replaced with the brief's verbatim required shape:
   - `_device_id = None` (`:37`) — private cache variable.
   - `resolve_device(force=False)` (`:40-56`) — public, matches the brief's
     required code exactly, with one addition: the "no devices found" print
     (`:54`) now fires only inside the `else` branch when resolution
     genuinely fails, never at import.
   - `invalidate_device()` (`:59-62`) — public, drops the cache.
   `WOS_ADB_SERIAL` is honoured only when it's in the currently-connected
   `devices` list (`:49`); otherwise falls back to `devices[0]` (`:51-52`) per
   your explicit decision.

2. **`:66-96` — `run_adb_command(cmd, device_id=None)` rewritten (Problems 2 & 3).**
   - Signature changed from `(cmd, device_id)` to `(cmd, device_id=None)` —
     required shape.
   - `:68-75` — when `device_id` is `None`, resolves via `resolve_device()`.
     This call is wrapped in `except OSError` (see "Deviation from literal
     brief text" below for why).
   - `:76-80` — raises a clear `RuntimeError` naming `WOS_ADB_SERIAL`'s value
     when no device can be resolved.
   - `:81-87` — the actual `adb -s <serial> <cmd>` call now runs with
     `stderr=subprocess.PIPE, text=True` so failures carry real stderr.
   - `:88-94` — catches `subprocess.CalledProcessError` specifically: calls
     `invalidate_device()` (Problem 2's recovery mechanism), then raises
     `RuntimeError` with serial, command, exit code, and stderr.
   - `:95-96` — catches `FileNotFoundError` specifically, says the adb binary
     isn't installed.
   - No bare `except Exception` anywhere (verified via `grep -n "except Exception"` → no match).

3. **`:100-158` — `tap_screen`, `swipe_screen`, `long_press` internal call sites updated.**
   Each of the 3 internal call sites (`:117`, `:138`, `:158` — brief's old
   `:74, 95, 115`) now calls `run_adb_command(adb_command)` with no
   `device_id` arg, letting `run_adb_command` resolve internally. Function
   **signatures unchanged** (still `tap_screen(*args)`,
   `swipe_screen(*args, duration=300)`, `long_press(*args, duration=300)`),
   satisfying the "do not change signatures" constraint.

4. **`:164-199` — `take_screenshot(save=False)` rewritten (Problems 2 & 3).**
   Signature unchanged (`save=False` only, per constraint).
   - `:165-168` — resolves device via `resolve_device()`, wrapped in
     `except OSError` for the same reason as in `run_adb_command`.
   - `:169-173` — raises `RuntimeError` naming `WOS_ADB_SERIAL` if no device
     resolves.
   - `:175` — uses the resolved serial in the command (brief's old `:122`).
   - `:176-186` — wraps `subprocess.check_output` in
     `except CalledProcessError` (invalidates cache — Problem 2 — and raises
     `RuntimeError` with serial/exit code/stderr) and `except
     FileNotFoundError` (adb missing).
   - `:191-193` — the decode-failure `RuntimeError` (brief's old `:128-129`,
     previously the bare string `"Failed to decode the image"`) now includes
     the serial and `len(raw)` (bytes actually received).
   - `save=False` behaviour and the `cache/` write (`:195-197`) are byte-for-byte
     unchanged.

5. **`:204-208` — `clear_input(count=6)` (Problem 4, part 2).**
   Signature unchanged. Both internal `run_adb_command` calls (`:205`, `:208`
   — brief's old `:140, 143`) drop the `device_id` positional arg entirely,
   so device resolution happens inside `run_adb_command`.

6. **`:212-219` — `input_text(text, backspace=6)` (Problem 4, part 1).**
   - Signature is exactly the brief's required
     `def input_text(text, backspace=6):` — the `device_id` parameter
     (previously defaulting to the typo'd `"131393852O003802"`, which is
     different from the also-wrong `"13139385O0003802"` deleted in change 1)
     is gone entirely.
   - `:216` fixes the `TypeError`-causing bug: `clear_input(count=backspace,
     device_id=device_id)` → `clear_input(count=backspace)` (`clear_input`
     never had a `device_id` parameter).
   - `:213` keeps `text.replace(" ", "%s")`; `:218` keeps the trailing
     `keyevent 66` (Enter). `save=False` / cache-write logic is untouched
     (not part of this function).

7. **Untouched, as instructed:** `:10-14` (`_convert_if_percentage`), `:7`
   (`from core.coord_utils import BASE_WIDTH, BASE_HEIGHT`), and
   `get_adb_devices()` itself (`:19-32`) — same body as before, no try/except
   added inside it.

## Deviation from the brief's literal text (and why)

The brief's "Required for `run_adb_command`" section describes catching
`FileNotFoundError`/`CalledProcessError` around the **`adb -s <serial>
<cmd>`** dispatch specifically. It says nothing about the earlier
`resolve_device()` call inside `run_adb_command` (device *probing*, which
calls `get_adb_devices()` → its own unguarded `subprocess.run(["adb",
"devices"], ...)`).

Testing against the brief's own verification script surfaced a real problem
with a literal reading: `get_adb_devices()` has no exception handling (per
"`get_adb_devices()` itself stays as-is"), so on a machine where `adb` is
genuinely absent, `resolve_device()` propagates a raw `FileNotFoundError`
(or, in this sandboxed session — see below — `PermissionError`) straight out
of `run_adb_command`, `clear_input`, and up through `input_text`. That
directly contradicts the brief's own verification script, whose second
`try/except` block only expects `input_text('8')` to end in `RuntimeError`
or `TypeError` — not an unhandled `OSError` subtype crashing the process.

Fix: `run_adb_command` (`:69-75`) and `take_screenshot` (`:165-168`) each
wrap their `resolve_device()` call in `except OSError as e:` → clear
`RuntimeError`. `OSError` is the real base class of both `FileNotFoundError`
and `PermissionError`, so this is a **specific** catch (not a bare `except
Exception`, honoring the constraint) that converts *any* failure to even
probe for a device — binary missing, binary present but not executable,
exec denied by a sandbox — into the same clear `RuntimeError` the rest of
Problem 3 promises. `resolve_device()` itself is left exactly as the brief's
verbatim required code shows, with no try/except added inside it — the
brief's own top-level test script (`except Exception as e:` around the bare
`sa.resolve_device()` call) confirms that's the intended, tolerated
behaviour when `resolve_device()` is called directly rather than through
`run_adb_command`.

## Sandbox artifact discovered during verification (informational, not a code concern)

This machine's `adb` absence is real (confirmed via `shutil.which("adb")` →
`None`, a manual scan of every `$PATH` directory finding no `adb` entry by
any measure including broken symlinks, `/usr/bin/env adb` → "No such file or
directory", and direct zsh invocation → "command not found", exit 127).

However, `subprocess.run(["adb", ...])` called from **any** Python
interpreter in this Bash-tool session (both `uv run python` and the system
`/usr/bin/python3`, and both with and without
`dangerouslyDisableSandbox: true`) raises `PermissionError: [Errno 13]
Permission denied: 'adb'`, not `FileNotFoundError`. I confirmed this isn't
adb-specific: a deliberately-nonexistent binary name
(`totally-nonexistent-binary-xyz123`) produces the identical
`PermissionError`, while `ls`/`echo` run fine. This points to some sandbox
layer around this agent session's Python subprocess spawning that denies
exec of non-allowlisted binaries with EACCES rather than the OS's normal
ENOENT — a property of *this verification environment*, not of the target
Mac or of the code. Since `FileNotFoundError`/`PermissionError` share the
`OSError` base and are handled identically by the code above, this had no
effect on correctness — only on which concrete exception class showed up in
the verification transcript below. Worth knowing if a later batch's tests
assume `FileNotFoundError` specifically will be raised in *this* sandboxed
CI-like environment — it won't be; `PermissionError` will, and both are
`OSError`.

## Verification command run (exact, from the brief) and its complete, unedited output

```
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
```

Output:

```
IMPORT OK — no adb probe at import
cached serial at import: None (must be None)
input_text sig: (text, backspace=6)
run_adb_command sig: (cmd, device_id=None)
resolve_device raised: PermissionError [Errno 13] Permission denied: 'adb'
input_text -> RuntimeError (correct, no device): adb command failed - could not probe for adb devices: [Errno 13] Permission denied: 'adb'
```

Required outcomes, checked against this output:
- Import succeeds and prints `IMPORT OK` — yes.
- `_device_id` is `None` at import — yes.
- `input_text` does **not** raise `TypeError` — confirmed; it raises
  `RuntimeError` (the `except RuntimeError` branch fired, not `except
  TypeError`).
- `run_adb_command` accepts a single positional arg — confirmed by
  `inspect.signature` output `(cmd, device_id=None)` and by every internal
  call site in the file now calling it with just `cmd`.

Additional checks run:

```
uv run python -m py_compile cmd_program/screen_action.py
```
→ exits 0, no output (compiles clean).

```
grep -n "except Exception" cmd_program/screen_action.py
```
→ no match (grep exit code 1) — confirms no bare `except Exception` anywhere
in the file.

```
grep -rn "input_text\|clear_input\|run_adb_command\|device_id" --include="*.py" .
```
→ (run before editing, to re-verify the brief's blast-radius claim before
touching anything) confirmed `device_id`/`run_adb_command`/`get_adb_devices`
are referenced only inside `cmd_program/screen_action.py`; `input_text` is
imported (unused re-export style `import` lines) by 14 `usecases/*.py`
files but actually **called** only at `usecases/gather.py:112` with the
single positional arg `"8"` — compatible with the new
`input_text(text, backspace=6)` signature.

## Anything noticed but deliberately not touched

- `.gitignore` has an unstaged, uncommitted modification in the working tree
  (pre-existing, unrelated to this task — confirmed via `git status` before
  I touched anything). I left it alone and did not stage or commit it; only
  `cmd_program/screen_action.py` is in commit `17cda1b`.
- Minor incidental whitespace cleanup: because I had to rewrite the bodies
  of `tap_screen`, `swipe_screen`, and `long_press` to drop the `device_id`
  arg from their `run_adb_command` calls, several trailing-whitespace-only
  lines inside those functions (e.g. `    ` after `raise ValueError`) were
  incidentally trimmed by the rewrite. This is a harmless side effect, not a
  deliberate cleanup pass, and doesn't touch `_convert_if_percentage` or the
  `BASE_WIDTH`/`BASE_HEIGHT` import as instructed.
- The file previously had no trailing newline (`\\ No newline at end of
  file` in the pre-change diff); the rewritten file ends with a normal
  newline. Not called out in the brief either way; flagging in case it
  matters to a later diff-sensitive tool.
- `run_adb_command`'s "no device could be resolved" message
  (`:76-80`) reports the value of `WOS_ADB_SERIAL` (which may be unset →
  `None`) rather than literally embedding the (necessarily `None`)
  `device_id` at that point, since showing `device_id=None` would be
  uninformative — this is my reading of the brief's "naming the serial"
  requirement (Problem 3, "Required for run_adb_command", bullet 2), which
  doesn't specify exact wording.

## Concerns

- The `except OSError` addition around `resolve_device()` calls in
  `run_adb_command` and `take_screenshot` is not literally spelled out in
  the brief (see "Deviation from the brief's literal text" above). I'm
  confident it's the correct call — it's what makes the brief's own
  verification script pass without a crash, it's a specific exception class
  (not a bare `except Exception`), and it doesn't touch any of the verbatim
  code blocks the brief gives for `resolve_device()`/`invalidate_device()`.
  Flagging for the reviewer in case they read "get_adb_devices() itself
  stays as-is" more strictly as "and callers must not add exception handling
  around it either."
- I could not observe real `FileNotFoundError` behavior in this session due
  to the sandbox artifact described above (got `PermissionError` instead,
  same `OSError` family, handled identically by the code). If a later
  batch's offline tests assert on the exact exception message text
  containing "not found" specifically, worth a quick check that my message
  wording ("adb binary not found", "could not probe for adb devices") is
  what's expected — I did not add any tests myself per the brief's
  constraint.
