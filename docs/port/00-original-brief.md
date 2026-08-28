# WOS Bot on Apple Silicon Mac — Handoff Brief for Claude Code

Context: Mahmoud wants a Whiteout Survival (WOS) daily-task automation bot running on his Apple Silicon Mac. This brief captures everything verified in research (Aug 2026): the device layer, two candidate codebases, exact patches, known bugs, and risks. All file paths, line numbers, and claims below were verified against live repos, PyPI metadata, and vendor docs, not recalled from memory.

## Decision gate (resolve first)

Two viable paths. **Pick one before writing code. Do not start both.**

- **Option A — AminulIslamSifat/wos (Python):** working dailies this week. Effort: one evening.
- **Option B — Frostguard / Shederator/wosbot (Java, AGPL):** proper small project, most feature-complete open codebase in the ecosystem. Effort: 1-2 weekends.

If the human hasn't stated a choice, ask before starting.

## Device layer: MuMuPlayer Pro for Mac (applies to both options)

- Apple Silicon native. 7-day free trial, then subscription. Trial covers the experiment phase.
- ADB is supported but it is **network ADB, not USB**: menu bar Tools > "Open ADB (device port number)". Connect with `adb connect 127.0.0.1:<port>` (main instance default port 16384; docs also show 26624). Developer config exposes `customAdbPort`.
- Requires MuMu version 1.5.4+ for developer/ADB functions.
- Resolution is set via the developer config key `resolutionWidthHeight` (JSON) if the UI presets don't offer the needed value.
- **Startup assertion for any bot:** run `adb shell wm size` and hard-fail if it doesn't match the expected resolution. Resolution mismatch is the #1 silent failure mode in this ecosystem: it produces mis-taps, not errors.
- Neither candidate bot runs `adb connect` itself. Either document it as a manual pre-step or add it to bot startup.

---

## Option A: AminulIslamSifat/wos

Repo: `github.com/AminulIslamSifat/wos` — Python, MIT, 27 commits, ~4 stars. Small and readable; you are the QA team.

### Architecture
- `Main/main.py` — entry point, account loop, interactive task selector (19 daily tasks: VIP, mail, gathering, alliance, arena, labyrinth, healing, etc.)
- `core/core.py` — vision client (OpenCV template matching + OCR requests)
- `core/ocr.py` — FastAPI OCR server on `localhost:8000` (PaddleOCR)
- `cmd_program/screen_action.py` — ADB taps/swipes/screenshots
- `cmd_program/screen_stream.py` — Linux-only fast capture (scrcpy → v4l2loopback), imported ONLY by `core/ocr.py`
- `db/account.json` — email + player ID + chief name per account. No passwords (README calls it "credentials"; it isn't). Character rotation within a logged-in account, not true multi-account login.
- `references/` — icon templates and TextArea ROI JSONs

### Verified dependency facts
- `pyproject.toml`: `requires-python = ">=3.12"`. The README's "Python 3.10+" is wrong. `.python-version` = 3.12.
- `paddlepaddle==3.2.0` ships `cp312 macosx_11_0_arm64` wheel on PyPI. Installs clean on Apple Silicon. CPU-only on macOS (PaddlePaddle dropped x86_64 mac; arm64 only).
- `adbnativeblitz` is a pure-Python `py3-none-any` wheel (deps: PyAV). Author only tested Windows; nothing platform-locked. It captures via `adb exec-out screenrecord` H.264 decoded in-process.
- `paddleocr==2.10.0`, `opencv-python`, `fastapi==0.135.3`, `rapidfuzz`, `rich`.

### Mac patches required
1. **`core/ocr.py` ~line 174:** the loopback bootstrap does `Path("/dev/video10").exists()` → false on macOS → shells `sudo modprobe v4l2loopback` → fails (no modprobe on macOS) → 120s cooldown → falls back to `take_screenshot()` at lines ~303/326 → retries sudo forever. It works unpatched but is noisy. Patch: short-circuit the loopback attempt when `sys.platform == "darwin"` (~3 lines). `STREAM_VIDEO_DEVICE` is env-configurable (`OCR_STREAM_DEVICE`) but there is no disable flag; consider adding `OCR_DISABLE_STREAM`.
2. **Run both processes from repo root.** `screen_stream.py` opens `cmd_program/scrcpy_config.json` with a relative path and silently sets `config = None` from any other cwd.
3. **ADB connect pre-step** (see device layer above). `screen_action.py` only calls `adb devices` and picks `devices[0]`. It also contains the author's hardcoded phone serial `13139385O0003802` in the device picker; falls through harmlessly, but clean it up.

### Known bugs (all platforms) — fix these
- **Resolution constants disagree:** `screen_action.py` has `SCREEN_WIDTH/HEIGHT = 1080/2460`; `scrcpy_config.json` and `ocr.py` use `STREAM_HEIGHT = 2456`. 4px vertical offset between the tap path and the OCR path when percentages are converted. Unify on one value.
- Whole repo is hardcoded to **1080x2460**. Set the MuMu instance display to exactly that. The promised "Auto-Calibration Suite" does not exist.

### Setup sequence
```
brew install uv android-platform-tools
git clone https://github.com/AminulIslamSifat/wos && cd wos
uv venv --python 3.12 && uv sync
cp db/account.json.example db/account.json   # fill email/player id/name
# MuMu: set display 1080x2460, Tools > Open ADB, note port
adb connect 127.0.0.1:<port> && adb shell wm size   # must print 1080x2460
# terminal 1 (repo root):
uv run core/ocr.py
# terminal 2 (repo root):
python Main/main.py
```

---

## Option B: Frostguard (Shederator/wosbot, Java, AGPL v3)

### CRITICAL FIRST STEP — mirror the repo today
`main` was wiped to a README amid a DMCA dispute (README taunts the takedown, points to Discord binaries). **The full source survives only in non-main branches and 100+ PR refs**: `chore/agpl-dco`, `feat/rotating-menu-navigation-245`, `fix/custom-task-portability`, `fix/windows-authenticode-launchers`. This code exists nowhere else on GitHub and can vanish the same way main did.

```
git clone --mirror https://github.com/Shederator/wosbot.git
```

Branch inspected for everything below: `feat/rotating-menu-navigation-245`.

### What it is
Multi-module Maven project (`./mvnw` wrapper): `modules/desktop` (JavaFX UI: profile manager, task builder, scheduler with Gantt overview, gift-code automation, Telegram panel), `modules/automation` (engine), `modules/vision` (OpenCV pattern matching), `modules/update`, `discord-bot`, `packaging`, `tools`. License: AGPL v3 with DCO. By far the most feature-complete open codebase in this space.

### Mac port plan
1. **Emulator layer = one new class.** `modules/automation/.../emulator/EmulatorInstance` is the base; existing impls (`MuMuEmulatorInstance` → `MuMuManager.exe`, `MEmuEmulatorInstance` → `memuc`, `LDPlayerEmulatorInstance` → `ldconsole`) are all Windows console tools but only manage instance lifecycle (launch/stop/list). Write a `GenericAdbInstance` for v1: assume MuMu Mac is already running, do `adb connect 127.0.0.1:<port>`, skip lifecycle management.
2. **Capture and input are already portable.** Real capture path is `EmulatorInstance.captureScreenshot()` (~line 246): ddmlib `executeShellCommand("screencap")` plus a frame-reuse optimization (`selectFrame`). Input is `adb input tap/swipe`.
3. **Ignore the "high-speed streaming" classes.** `ScrcpyStreamCapture` (35 lines) and `ScreenRecordStreamCapture` (20 lines) are self-described stubs; `grabFrame()` returns null. Nothing uses them. The only Windows-ism there (`lib/ffmpeg/ffmpeg.exe` lookup) is irrelevant. If a fast path is ever measurably needed: `adb exec-out screenrecord --output-format=h264 -` decoded in-process via JavaCV/FFmpeg (~1 day). Don't build it preemptively; OCR and decision rate are the bottleneck, screencap at 100-300ms/frame is fine for daily chores.
4. **Neutralize Windows bootstrap:** `WindowsWindowManager`, `DarkTitleBar`, `ApplicationLifecycle` are already `os.name`-guarded and should no-op on macOS; verify. Authenticode launcher packaging: ignore, run via `./mvnw` / `java -jar`.
5. **Native libs:** verify the pom resolves JavaFX and OpenCV natives for `macosx-aarch64`. `modules/vision/.../OpenCvPatternLocator.java` does OS-specific native loading (~line 1868 and ~1921); check its macOS branch.
6. **Privacy:** `modules/automation/.../service/AnalyticsService.java` phones home (os, os_arch, version props). Disable before first run.
7. **Smoke test:** `./mvnw package` on the Mac; catalogue failures. That one command decides whether this is a weekend or a month.

### Legal note
AGPL means the fork's code basis (and yours) is defensible for private use even though upstream (camoloqlo) went commercial. There is an active DMCA dispute. Private use: fine. **Do not publicly publish/redistribute a Mac fork without the human deciding to enter that fight.** Never use the Discord-distributed binaries (unsigned, takedown-contested).

---

## Rejected candidates (context, don't revisit)

- **batazor/whiteout-survival-autopilot** (Go+Python, 39★): read-only reference. Default branch dead since Aug 2025 (recent push dates are dependabot branch noise). Its own `note.md` roadmap shows the core orchestration (task TTL, profile switching, global analyzer) unbuilt. Requires Redis + Label Studio + Prometheus. Docs in Russian. Hardcoded 1080x2400. Worth mining for ideas only: FSM navigation graph, `references/fsmState.yaml`, ADRs in `docs/ADR`.
- **austxio/WOS-Bot** (Python, 3★): fallback if Option A stalls. Browser drag-and-drop task builder, OpenCV template matching, YAML task files. ADB mode works on Mac; its Google Play Games window-capture mode is Windows-only.
- **camoloqlo/wosbot** (113★): the original; now closed source and sold commercially. Repo is an SEO shell.
- **Discord/alliance tier** (different project, not gameplay automation): `whiteout-project/bot` (90★, most maintained repo in the ecosystem), `justncodes/wos-giftcode`. These survive because they only touch `/api/gift_code`, the one endpoint Century Games left alive; `/api/player` and `/api/captcha` are dead 404s (verified in a prior session).
- **zenpaiang/wos-database** (10★): dump of game icons/JSON. Useful source of template images if any vision work is needed.

## Global risks

- Automation violates WOS ToS. Century Games is actively anti-automation (API kills, DMCA pressure on bots). Account ban is a real outcome; run on an account the human accepts losing, or at least accept the risk explicitly.
- Every bot in this ecosystem is resolution-locked and fails silently on mismatch. Assert `adb shell wm size` at startup, always.
- Any adopted dependency can vanish via takedown. Mirror what matters.

## Scope guard

Get **one account running one daily loop end to end** before touching multi-instance, bot-farm, scheduling frameworks, or fast capture. Multi-instance is a known rabbit hole for this human; hold the line.
