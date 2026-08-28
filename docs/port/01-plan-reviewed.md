# WOS Bot on Apple Silicon — Option A (Python) Mac Port

## Context

Mahmoud wants a Whiteout Survival daily-task bot running on his Apple Silicon Mac. The handoff brief (`~/Downloads/wos-mac-port-brief.md`) laid out two paths; **Option A (`AminulIslamSifat/wos`, Python, MIT) is chosen**. Account selection is deferred — Phases 1–4 run unattached; Phase 5 blocks on it.

**v1 done means:** mail and gather each complete end to end, then an immediate re-run is correctly skipped by the cooldown store. That is the cheapest thing that proves the *loop* property rather than just two working tasks. Not a full 19-task sweep.

Every file:line below was verified against live source at the pinned SHA, not taken from the brief. Several brief claims are wrong; the corrections *simplify* the work.

**Pinned revision: `c7951f19e8cdb7fadcdf947a0bc0c6e74b6b951f`** (2026-05-02, tagged 0.8.0). `main` is mutable and the review's line numbers are only valid at this SHA — clone and check out this commit, do not track `main`.

---

## Corrections to the brief (verified against source)

**1. The v4l2loopback patch is unnecessary — an env-var escape hatch already exists.**
`_capture_frame()` at `core/ocr.py:301-308` returns early when `_preferred_screen_capture_tool == "adb"` and **never reaches `_try_start_stream()`** (line 310). The tool is settable non-interactively via `OCR_CAPTURE_TOOL` at `core/ocr.py:118-122`.
→ `OCR_CAPTURE_TOOL=adb` bypasses the entire modprobe/sudo/120s-cooldown path with **zero code changes**, and skips the interactive capture-tool prompt that fires at import (`core/ocr.py:848`).

**2. Coordinates are percentage-based, not hardcoded pixels.** The brief says "hardcoded to 1080x2460." Not so:
- `references/TextArea/*.json` store boxes as percentages (`Home.json`: `"box": [39.07, 5.41, 48.89, 7.15]`).
- `core/coord_utils.py:7-9` declares the canonical base: `BASE_WIDTH = 1080`, `BASE_HEIGHT = 2460`.
- `cmd_program/screen_action.py:13-17` (`_convert_if_percentage`) treats floats 0–100 as percentages.

**3. The 4px bug points the other way — taps are fine, vision is distorted.**
`core/ocr.py:86` sets `STREAM_HEIGHT = 2456`. `_normalize_frame_resolution()` (`core/ocr.py:152-160`) resizes *every* frame to 2456, including the adb path (`core/ocr.py:304`). `core/ocr.py:678-679` then applies `y1 = y1 - 5`, commented *"a slight adjustment so that it could take scrcpy image to with a res of 1080x2456."*
Taps (`SCREEN_HEIGHT = 2460`, `screen_action.py:10`) were always correct. The OCR path squashes the frame 0.16% and band-aids the drift.

**4. A recalibration routine does exist.** No *resolution* auto-calibration — the brief is right. But `core/recalibrate.py` (93 lines) is a real **navigation-state** recovery routine, batch-tapping `Global.Back` / `Global.Close` / `FirstPurchase.Close` until it detects Home. Reuse it.

**5. `input_text()` is broken, and gathering is its only live caller.** `usecases/gather.py:112` calls `input_text("8")`, hitting two stacked bugs in `cmd_program/screen_action.py`:
- `:154` calls `clear_input(count=backspace, device_id=device_id)` but `:142` defines `def clear_input(count=6)` — no such parameter. `TypeError` immediately.
- `:150` defaults `device_id="131393852O003802"`, a typo'd serial (distinct from `:44`'s `"13139385O0003802"`) shadowing the module device, so `:156` fires adb at a nonexistent device.

15 of 17 usecase modules import `input_text`; only `gather.py:112` calls it.

**6. The RAM guard is inert on macOS.** `_get_process_rss_bytes()` (`core/ocr.py:223-234`) reads `/proc/self/status`, absent on macOS; the exception is swallowed and it returns `0`, so `_enforce_ram_cap()` (`core/ocr.py:246-250`) always early-returns. Called at four hot points — `core/ocr.py:647`, `:776`, `:813`, `:822` — wrapping every OCR run and template match.

**7. `device_id` binds once at import and never rebinds.** `screen_action.py:40` runs `get_adb_devices()` at module level; `:41-47` bind once. `core/ocr.py:36` imports that module, so **starting the OCR server also triggers the import-time adb probe**. Without adb connected at import, `screen_action.py:125` builds `["adb", "-s", "None", ...]` for the session; reconnecting later does not help.

---

## Coordinate data flow

```text
MuMu instance @ 1080x2460
  |  adb -s 127.0.0.1:$PORT exec-out screencap -p
  v
take_screenshot()                  screen_action.py:124   frame @ 1080x2460
  |
  v
_normalize_frame_resolution()      ocr.py:152
  |  BEFORE: resize 2460 -> 2456   (0.16% vertical squash)
  |  AFTER : dimensions match base -> early return, no resize
  v
ROI percentages                    references/TextArea/*.json
  |  clamp_roi(roi, w, h)          ocr.py:672
  |  BEFORE: y1 -= 5               ocr.py:678   (band-aid for the squash)
  |  AFTER : removed
  v
PaddleOCR  ->  text + coordinates
  |
  v
tap_screen(x%, y%)                 screen_action.py:60
  |  _convert_if_percentage(y, BASE_HEIGHT=2460)   :74
  v
adb shell input tap  ->  MuMu instance @ 1080x2460
```

The bug in one line: **the vision leg ran at 2456 while the tap leg ran at 2460.** A trimmed copy of this diagram goes in `core/ocr.py` above `_normalize_frame_resolution`.

---

## Plan

### Phase 1 — Environment and OCR smoke test (~25 min, before any emulator work)

The riskiest dependency is validated first, because it needs no emulator.

`paddleocr==2.10.0` is pinned alongside `paddlepaddle==3.2.0`. PyPI shows paddleocr 2.10.0 declares **no** `paddlepaddle` dependency, so `uv sync` always succeeds and any incompatibility is a runtime failure. The code is unambiguously 2.x-flavoured: `core/ocr.py:277-287` and `core/ocr.py:345` (`ocr.ocr(image, cls=False)`) use arguments removed or renamed in 3.x. The committed `uv.lock` is evidence the pair works; PaddleOCR's docs calling 2.x→3.x breaking is evidence it might not.

```bash
git clone https://github.com/AminulIslamSifat/wos && cd wos
git checkout c7951f19e8cdb7fadcdf947a0bc0c6e74b6b951f
git switch -c mac-port          # patches go on a branch, one commit each

# Upstream committed a real player ID (db/players/578380047.json). Do not repeat
# that with yours on a repo tied to a bannable activity.
printf 'db/account.json\ndb/players/\ncache/\ntest/debug/\n' >> .gitignore

uv venv --python 3.12 && uv sync
```

**Commit each patch separately.** T4–T9 map 1:1 to commits. Uncommitted, your changes
are indistinguishable from upstream, individually unrevertable, and one stray
`git checkout` erases them.

The smoke test must use **the project's real constructor arguments**, not a simplified call — `det_limit_side_len`, `ir_optim`, `layout`, `table`, `formula` are exactly the ones most likely to break on 3.x, so a simplified call can pass while `core/ocr.py` fails:

```bash
uv run python -c "
import paddleocr, paddle, numpy as np
from paddleocr import PaddleOCR
print(paddleocr.__version__, paddle.__version__)
paddle.set_device('cpu')
o = PaddleOCR(use_angle_cls=False, lang='en', use_gpu=False,
              det_limit_side_len=1024, cpu_threads=4, ir_optim=True,
              layout=False, table=False, formula=False)
print(o.ocr(np.zeros((200,600,3),'uint8'), cls=False))"
```

`paddlepaddle 3.2.0` ships `cp312-cp312-macosx_11_0_arm64` (confirmed on PyPI; cp39–cp313 present). CPU-only on macOS. **Do not install MuMu until this passes.**

Then `cp db/account.json.example db/account.json` — placeholder values.

### Phase 2 — Emulator (~25 min, mostly downloads)

Neither tool is installed (verified: `adb not found`, no `/Applications/MuMu*`).

1. `brew install --cask android-platform-tools`
2. Install **MuMuPlayer Pro for Mac** (Apple Silicon native, 7-day trial). Needs **v1.5.4+** for ADB.
3. Set instance display to exactly **1080x2460**. If presets lack it, use developer config key `resolutionWidthHeight`.
4. **Tools → Open ADB**, note the port (main instance default `16384`; docs also cite `26624`).
5. Install Whiteout Survival and log in manually once.

### Phase 2.5 — Coordinate baseline, BEFORE patching (~15 min)

The `y1 -= 5` fudge is *believed* to compensate only the 2460→2456 squash. That is an inference from source, and the fudge could also be absorbing a viewport offset or status-bar crop — invisible in code, visible only on a real screen. Measure before changing.

Against **unpatched** code:

```bash
adb -s 127.0.0.1:$PORT exec-out screencap -p > baseline.png
python3 -c "from PIL import Image; print(Image.open('baseline.png').size)"   # must be (1080, 2460)
```

Then overlay the `references/TextArea/Home.json` ROI percentage boxes on `baseline.png` (throwaway script, ~15 lines using `core/coord_utils.box_percent_to_pixel`). Confirm the boxes land on the intended UI elements. Repeat after Phase 3 and diff. If the post-patch overlay is *worse*, the fudge was doing more than the squash and 3.1 needs rethinking.

### Phase 3 — Patches (~1h)

**3.1 — One coordinate authority.**
`core/coord_utils.py` imports nothing, so it is a safe leaf. `core/core.py:12,14` already imports from *both* `cmd_program.screen_action` and `core.coord_utils`, and all three `__init__.py` files are empty — the new edge creates no cycle. (`test_coords.py`'s "circular import issue is RESOLVED" note refers to an earlier arrangement; extracting `coord_utils` as a pure leaf is what resolved it.)

- `cmd_program/screen_action.py:9-10` — import `BASE_WIDTH`/`BASE_HEIGHT` from `core.coord_utils` instead of redeclaring `SCREEN_WIDTH`/`SCREEN_HEIGHT`.
- `core/ocr.py` — `_normalize_frame_resolution` uses `BASE_WIDTH`/`BASE_HEIGHT`.
- **Leave `STREAM_WIDTH`/`STREAM_HEIGHT` alone** for `start_screen_stream()` at `core/ocr.py:212`. On Linux 2456 may genuinely be scrcpy's output height; repurposing it changes upstream behaviour we cannot verify from a Mac.
- `core/ocr.py:678-679` — delete the `y1 = y1 - 5` fudge and its comment.
- Add the trimmed coordinate diagram above `_normalize_frame_resolution`.

Side benefit: `_normalize_frame_resolution` early-returns at `core/ocr.py:157` instead of resizing every frame.

**3.2 — Lazy device resolution.** Replace the module-level binding at `screen_action.py:40-47` with a cached accessor that re-probes when the cached value is `None` **or when an adb command fails** — a cached serial cannot detect a dropped device on its own, so failed commands must invalidate the cache. ~6 call sites reference the global (`tap_screen`, `swipe_screen`, `long_press`, `take_screenshot`, `clear_input`, `input_text`). Prefer the serial in `$WOS_ADB_SERIAL` when set, so a second emulator or a plugged-in phone cannot make `devices[0]` a coin flip. Drop the dead hardcoded serial at `:44-45` in the same edit.

**3.3 — Fix `input_text()`** at `screen_action.py:150-157`: remove the bogus `device_id` parameter (use the resolved device) and change `:154` to `clear_input(count=backspace)`. Fixes both stacked bugs.

**3.4 — Repair the RAM *sensor*, leave the actuator dormant.** Add `psutil` and rewrite `_get_process_rss_bytes()` (`core/ocr.py:223-234`):

```python
import psutil
def _get_process_rss_bytes():
    try:
        return psutil.Process().memory_info().rss
    except Exception:
        return 0
```

Not `resource.getrusage` — `ru_maxrss` is a *peak* that never decreases, so the guard would latch on permanently once tripped.

Then run the port with **`OCR_RAM_CAP_GB=16`** (`core/ocr.py:83` already reads it). This gives honest RSS numbers from run one without arming `_reinitialize_ocr_engine()` (`core/ocr.py:263`) — a teardown/rebuild path that has never executed on macOS — during the highest-risk week. Lower the cap to 3 once the loop is stable. Note this reasoning in a comment; it is a config value doing the work of a scope decision.

**3.5 — `run.sh` at repo root.** Both processes need adb connected *before* import, and both must run from the repo root (`cmd_program/screen_stream.py:13` opens `cmd_program/scrcpy_config.json` relatively; `cache/` and `test/debug/` writes are relative too).

```sh
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
python3 -c "
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
```

The dimension gate is non-negotiable — resolution mismatch is the ecosystem's #1 silent failure mode and it produces mis-taps, not errors.

**3.6 — Harden the two adb error paths** (from the CEO review's error/rescue map).

- `screen_action.py:54-56` — `run_adb_command` catches bare `Exception` and flattens
  every adb failure into one `RuntimeError("adb command failed - ...")`. "Emulator
  asleep" and "typo in command" become indistinguishable. Catch `CalledProcessError`
  specifically and include the device serial and the command that failed.
- `screen_action.py:126` — `take_screenshot` calls `subprocess.check_output` with no
  handler; a device that vanished mid-run produces a raw traceback. Catch
  `CalledProcessError`, and give the `:131` decode failure real context (serial, byte
  count) instead of the bare `"Failed to decode the image"`.

**Also verify during implementation:** `_post_json_with_replay` (`core/core.py:97-127`)
returns `None` after its 35s budget expires. That retry loop is well built — 8s HTTP
timeout, exponential backoff capped at 2.5s, bounded wall clock, all env-tunable — but
I did not verify that callers check for `None`. If they do not, a downed OCR server
surfaces as an `AttributeError` far from the cause. One grep settles it.

### Phase 4 — Tests (~30 min)

`pyproject.toml` declares no test framework. `test_coords.py` has **no assertions** — it prints "All coordinate conversion utilities working correctly!" unconditionally and would print that if every conversion returned zero. Replace it.

**Import-time side effects must be neutralised first.** `core/ocr.py:848` calls `take_preferred_screen_capture_tool()` at module scope, which **prompts interactively**, and `core/ocr.py:376` builds an OCR engine at import. Importing `core.ocr` in pytest would hang. `conftest.py` must set `OCR_CAPTURE_TOOL=adb` (satisfies the `:118-122` env branch, skipping the prompt) before any import, and the engine build at `:376` must be monkeypatched or the function under test imported without executing module scope. Settle this first; the rest of Phase 4 depends on it.

`uv add --dev pytest`, then:

| Test | Asserts |
| --- | --- |
| `tests/conftest.py` | sets `OCR_CAPTURE_TOOL` pre-import; stubs the import-time engine build |
| `tests/test_coords.py` | `pixel_to_percent` → `percent_to_pixel` round-trips; boundaries at 0, 100, 1080, 2460 |
| `tests/test_normalize.py` | frame at base height returns **unresized**; off-height frame returns at base height |
| `tests/test_convert.py` | `_convert_if_percentage`: int passthrough, float 0–100 as percent, float >100 as int cast |
| `tests/test_device.py` | mock `subprocess.run`: none → `None` + re-probe; present → cached; **failed command → cache invalidated** |
| `tests/test_input.py` | mock `run_adb_command`: `input_text` raises no `TypeError`, targets the resolved device |

`test_normalize.py` matters most — it makes the 2456/2460 drift impossible to reintroduce silently.

### Phase 5 — First runs (BLOCKED on account, ~1h)

**Prerequisite:** a real account you accept losing, *plus prepared in-game state* — unclaimed mail to collect, and troops plus a reachable resource node to gather with. An empty mailbox produces a task that "passes" by doing nothing.

```bash
./run.sh
```

First PaddleOCR run downloads models — expect minutes of apparent hang. (`core/ocr.py:7` sets `PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK`, which skips source *probing*, not the download.)

`Main/main.py` (396 lines) presents an interactive task selector backed by `usecases/*`. Three runs:

1. **`collect_mail_rewards`** — simple, idempotent, no text input. Proves the pipeline is alive.
2. **`gather`** — the only live caller of `input_text` (`usecases/gather.py:112`). Must be separate; a clean mail run proves nothing about that path.
3. **Immediate re-run of both** — the scheduler must *skip* them as already-done. This is what makes it a loop rather than two one-shot tasks.

Per-player state lives in `db/players/<id>.json` (cooldowns, `last_visit`, per-task `priority`) — the existing scheduling store; do not build a new one.

---

## Verification

1. Phase 1 smoke test prints both versions and returns an OCR result without raising, **using the project's real constructor arguments**. Gate — no MuMu until this passes.
2. `pytest` — all Phase 4 tests green, no interactive hang. Paste the output.
3. `adb devices` lists `127.0.0.1:<port>` as `device`.
4. `adb -s <serial> exec-out screencap -p` → PNG is **exactly 1080x2460**. This is the real gate, not `wm size`.
5. OCR server logs `✅ Using Capture Tool from Env: ADB` — proves correction #1.
6. **Coordinate correctness at three heights.** OCR one landmark near the top, one mid-screen, one near the bottom, and confirm each matches the screen. A 0.16% error is 0.4px at y=5% and ~4px at y=90% — testing only `Home.Power` (y≈5.4%) cannot detect the bug being fixed.
7. Phase 2.5 ROI overlay re-run post-patch is no worse than the baseline.
8. `collect_mail_rewards` collects a real reward; `db/players/<id>.json` `last_visit` updates.
9. `gather` completes and **actually enters text** — confirm the march size field shows `8`, not merely that no `TypeError` was raised.
10. Immediate re-run skips both tasks via cooldown. **This is the v1 acceptance criterion.**
11. Record RSS across the full run (`ps -o rss= -p <ocr_pid>`) to decide whether to lower `OCR_RAM_CAP_GB` from 16 to 3.

---

## What already exists (reuse, do not rebuild)

| Need | Existing | Reused? |
| --- | --- | --- |
| Canonical coordinate space | `core/coord_utils.py:7-9` | Yes — promoted to single source (3.1) |
| Bypass v4l2loopback/sudo | `OCR_CAPTURE_TOOL`, `core/ocr.py:118-122` | Yes — zero code changes |
| Navigation recovery | `core/recalibrate.py` | Yes — not rebuilt |
| Task scheduling / cooldowns | `db/players/<id>.json` | Yes — not rebuilt; now actually tested |
| Import from any cwd | `sys.path.append`, `core/ocr.py:4` | Yes — no path shims added |
| RAM cap configuration | `OCR_RAM_CAP_GB`, `core/ocr.py:83` | Yes — used to keep recycling dormant (3.4) |
| Engine recycling | `_reinitialize_ocr_engine`, `core/ocr.py:263` | Wiring correct; sensor repaired, actuator deliberately dormant |
| Percent↔pixel box conversion | `core/coord_utils.box_percent_to_pixel` | Yes — powers the Phase 2.5 overlay |

## NOT in scope

- **Multi-instance / bot farm** — the brief names it a known rabbit hole. Held.
- **Fast capture** (`screenrecord` H.264, adbnativeblitz) — `screencap` at 100–300ms/frame is not the bottleneck; OCR is.
- **Process supervision / auto-restart** — if the OCR server dies, `Main/main.py` gets connection errors to localhost:8000 and does not recover. `run.sh` now cleans up on exit but does not supervise. Real gap, deferred past one loop.
- **Full 19-task sweep** — v1 bar is two tasks plus a cooldown-verified re-run (D12). The remaining 17 task modules stay unproven.
- **The int-vs-float coordinate convention** — `_convert_if_percentage` (`screen_action.py:13-17`) reads `50` as 50px but `50.0` as 50%. Genuinely unsafe, but pre-existing upstream design touching every call site. Flagged, not fixed.
- **Resilience to sleep / lock / game updates / popups / emulator restart / network loss** — acceptable for v1, incompatible with true unattended daily operation. Revisit after the loop is stable.
- **MuMu paid licence** — the 7-day trial covers the experiment, not an ongoing daily bot. A purchasing decision, not an engineering one.
- **Upstreaming these fixes** — several are platform-neutral bugs the author would likely take, but that is a separate conversation.
- **Option B (Frostguard)** — not chosen.
- **Distribution/packaging** — personal tool; `run.sh` is the delivery mechanism.

**TODOS.md:** not created. The repo is not cloned yet and this list already carries the rationale for each deferral. Seed `TODOS.md` from this section during implementation if you want it tracked in-repo.

## One-line insurance (independent of this plan)

Frostguard's source survives only in non-`main` branches and PR refs after its `main` was wiped in a DMCA dispute:

```bash
git clone --mirror https://github.com/Shederator/wosbot.git
```

Worth doing regardless. AGPL and fine to hold privately — but do not publish a Mac fork without deciding to enter that dispute, and never use the Discord-distributed binaries.

## Risk accepted

Automation violates WOS ToS and Century Games actively bans for it. Account choice deferred; `db/account.json` stays placeholder until picked. Phase 5 cannot start without it.

---

## Implementation Tasks

Synthesized from this review's findings. Each derives from a specific finding above.

- [ ] **T1 (P1, human: ~15min / CC: ~3min)** — repo — Clone and pin to `c7951f19`
  - Surfaced by: Outside voice — "`main` is mutable, all verified lines can drift"
  - Files: n/a
  - Verify: `git rev-parse HEAD` matches the pinned SHA
- [ ] **T2 (P1, human: ~20min / CC: ~5min)** — env — OCR smoke test with the project's real constructor args
  - Surfaced by: Architecture #1 + outside voice — install always succeeds, incompatibility is runtime-only
  - Files: n/a (one-liner)
  - Verify: prints both versions, returns an OCR result, no exception
- [ ] **T3 (P2, human: ~40min / CC: ~10min)** — vision — Phase 2.5 ROI overlay baseline on unpatched code
  - Surfaced by: Cross-model tension D10 — the -5 fudge may absorb more than the squash
  - Files: throwaway script using `core/coord_utils.box_percent_to_pixel`
  - Verify: boxes land on intended UI elements; re-run post-patch is no worse
- [ ] **T4 (P1, human: ~45min / CC: ~10min)** — vision — Unify coordinate space on `coord_utils`
  - Surfaced by: Code Quality #5 — three declarations of the base, one drifted to 2456
  - Files: `core/ocr.py:86,152-160,678-679`, `cmd_program/screen_action.py:9-10`
  - Verify: `tests/test_normalize.py` asserts base-height frames come back unresized
- [ ] **T5 (P1, human: ~45min / CC: ~10min)** — adb — Lazy device resolution with failure-invalidated cache
  - Surfaced by: Architecture #2 + outside voice — binds at import, never rebinds, cache cannot self-detect a drop
  - Files: `cmd_program/screen_action.py:40-47` and ~6 call sites
  - Verify: `tests/test_device.py` covers none / present / dropped / failed-command
- [ ] **T6 (P1, human: ~15min / CC: ~3min)** — adb — Fix `input_text()` (TypeError + typo'd serial)
  - Surfaced by: Code Quality #4 — `gather.py:112` is the only live caller
  - Files: `cmd_program/screen_action.py:150-157`
  - Verify: `tests/test_input.py`; live gather run actually types `8`
- [ ] **T7 (P2, human: ~30min / CC: ~5min)** — ocr — Repair RSS sensor, keep recycling dormant
  - Surfaced by: Performance #7, revised by cross-model tension D9
  - Files: `core/ocr.py:223-234`, `pyproject.toml` (psutil)
  - Verify: RSS logged accurately; `OCR_RAM_CAP_GB=16` so recycling does not arm
- [ ] **T8 (P1, human: ~45min / CC: ~10min)** — tooling — `run.sh` with dimension gate, readiness wait, trap
  - Surfaced by: Architecture #2 + outside voice — startup race, orphaned process, weak `wm size` gate
  - Files: `run.sh` (new)
  - Verify: launches cleanly; Ctrl-C leaves no orphan; wrong resolution hard-fails
- [ ] **T9 (P1, human: ~2h / CC: ~20min)** — tests — pytest suite with import-side-effect isolation
  - Surfaced by: Test review #6 + outside voice — `core/ocr.py:848` prompts at import
  - Files: `tests/conftest.py` + 5 test modules; replaces assertion-free `test_coords.py`
  - Verify: `pytest` green with no interactive hang
- [ ] **T10 (P1, human: ~15min / CC: ~3min)** — repo — Branch + gitignore before any commit
  - Surfaced by: CEO review S1/A1 and S3 — unrevertable patches; upstream leaked a real player ID
  - Files: `.gitignore`, branch `mac-port`
  - Verify: `git status` shows no `db/account.json` or `db/players/`; each patch is its own commit
- [ ] **T11 (P2, human: ~30min / CC: ~6min)** — adb — Harden the two adb error paths
  - Surfaced by: CEO review S2 — bare `except Exception` at `screen_action.py:55`; unhandled `check_output` at `:126`
  - Files: `cmd_program/screen_action.py:51-56,124-137`
  - Verify: killing the emulator mid-run produces a named error with the serial, not a bare traceback
- [ ] **T12 (P2, human: ~10min / CC: ~2min)** — ocr — Confirm callers handle `None` from the OCR replay loop
  - Surfaced by: CEO review S2 — `_post_json_with_replay` returns `None` after 35s; caller behavior unverified
  - Files: `core/core.py:97-127` and its call sites
  - Verify: OCR server stopped mid-run yields a clear message, not an `AttributeError`

---

## Time estimate

| Phase | Estimate |
| --- | --- |
| 1 — env + OCR smoke test | ~25 min |
| 2 — emulator | ~25 min (downloads) |
| 2.5 — coordinate baseline | ~15 min |
| 3 — patches | ~1h |
| 4 — tests | ~30 min |
| 5 — first runs (blocked on account) | ~1h |

**~3.5–4 hours of working time, realistically spread over two sessions.** The earlier 2.5h figure assumed every untested integration worked first time. Emulator setup, game install, account preparation, PaddleOCR compatibility and live navigation are each capable of eating an hour on their own — one evening is the optimistic case, not the expected one.

---

## GSTACK REVIEW REPORT

| Review | Trigger | Why | Runs | Status | Findings |
| --- | --- | --- | --- | --- | --- |
| CEO Review | `/plan-ceo-review` | Scope & strategy | 1 | CLEAR | 8 proposals, 5 accepted, 4 deferred |
| Codex Review | `/codex review` | Independent 2nd opinion | 1 | issues_found | 21 findings; 2 tensions resolved, 7 defects folded |
| Eng Review | `/plan-eng-review` | Architecture & tests (required) | 1 | CLEAR | 7 issues, 0 critical gaps |
| Design Review | `/plan-design-review` | UI/UX gaps | 0 | — | — |
| DX Review | `/plan-devex-review` | Developer experience gaps | 0 | — | — |

**CODEX:** Ran as the outside voice (gpt-5.6-sol, high reasoning). Found seven real defects the eng review missed — unpinned mutable `main`, a `run.sh` startup race against PaddleOCR model download, an orphaned background process on Ctrl-C, missing explicit adb serial, a `wm size` gate weaker than claimed, a smoke test omitting the project's actual constructor arguments, and an interactive prompt at `core/ocr.py:848` that would hang the entire proposed pytest suite. All seven folded in (D11). Also caught that verifying only `Home.Power` at y≈5.4% cannot detect a 0.16% vertical scale error — verification now samples three screen heights. Not re-run for the CEO pass: per the one-outside-voice-per-diff rule, the plan delta since that pass is additive and small.

**CROSS-MODEL:** Two substantive disagreements, both resolved by splitting rather than picking a side. On the RAM guard, the review said repair it, codex said it arms untested engine-recycling during the riskiest week — settled by repairing the sensor while holding the actuator dormant via `OCR_RAM_CAP_GB=16` (D9). On patch ordering, the review argued the source evidence was conclusive, codex argued the `-5` fudge might absorb a viewport offset invisible in code — settled by adding a Phase 2.5 ROI-overlay baseline before patching, keeping the fix (D10). Both models independently judged the original two-task finish line insufficient to test the loop property; the bar is now two tasks plus a cooldown-verified re-run (D12).

**CEO:** Mode SELECTIVE EXPANSION. The premise challenge found that the plan's own risk mitigation cancels its purpose — "run on an account you accept losing" against chores that only matter on an alliance main. Deferring the account choice to Phase 5 is what hid it; it is now an explicit up-front decision. The pre-review audit also surfaced `ace-discord-manager/WOS_INTEGRATION_PLAN.md` (2026-08-25), whose G1/G2 gates set a markedly stricter posture than this plan takes; flagged as a deliberate choice rather than an accident. Accepted: git branch + commit-per-patch, `.gitignore` for player data (upstream committed a real player ID), hardening of two adb error paths, and a caller check on the OCR replay loop's `None` return. Deferred: ACE attendance-OCR harvest, run-log observability, launchd scheduling, int-vs-float coordinate convention. Section 11 skipped — no UI scope. Reversibility 5/5.

**VERDICT:** CEO + ENG CLEARED — ready to implement.

NO UNRESOLVED DECISIONS
