# ❄️ Whiteout Survival Autopilot — Mac Port (WOS-Bot)

![Python](https://img.shields.io/badge/Python-3.10%2B-blue?style=flat-square&logo=python)
![Platform](https://img.shields.io/badge/Platform-macOS%20(Apple%20Silicon)-blueviolet?style=flat-square)
![Status](https://img.shields.io/badge/Status-v1%20daily%20loop%20verified-green?style=flat-square)

Automation suite for Whiteout Survival, ported to Apple Silicon Macs running the game
in **MuMuPlayer Pro** over **adb**. Vision is PaddleOCR (text) + OpenCV template
matching (icons), with `rapidfuzz` absorbing OCR misreads.

This is a fork of the upstream Linux/Windows bot, pinned to upstream `c7951f19`
(tagged 0.8.0) on branch `mac-port`. The full port record — what the original brief
got wrong, every review, decision, and finding — lives in
[`docs/port/INDEX.md`](docs/port/INDEX.md). Read it before touching the code.

---

## Current state

- **v1 daily loop verified live**: mail collected, gather deployed with an adaptive
  per-player node level, and an immediate re-run correctly skips on cooldown.
- **Offline test suite**: `uv run pytest tests/ -q` → 40 passed. No emulator, no adb,
  no network needed.
- Linux-only paths (scrcpy/v4l2 streaming) are untouched but unused on macOS —
  the launcher forces `OCR_CAPTURE_TOOL=adb`.

---

## How it works

1. **Vision engine** — a local FastAPI OCR server (`core/ocr.py`, port 8000) reads text
   with PaddleOCR; `core/core.py` matches icons with OpenCV templates from
   `references/icon/`.
2. **Percentage-based ROIs** — screen regions in `references/TextArea/*.json` are
   percentages against the canonical 1080×2460 base declared in `core/coord_utils.py`.
   The bot is *not* pixel-hardcoded, but the emulator must present a 1080×2460
   framebuffer (see below).
3. **Task loop** — `Main/main.py` launches the game on the pinned adb device, reads
   the active player from the in-game Chief Profile, runs the selected tasks, then
   cycles through sibling characters on the same email before switching to the next
   account by priority. Completion is recorded per player in `db/completion_log.txt`
   with a 3-hour skip window.
4. **Per-player profile** — `db/players/<id>.json` (seeded from
   `db/players/example.json`, reseeded if corrupt) persists name, state, furnace
   level, and the gather node level. Each run probes one level above the last
   known-good level (capped at 8); the level is lowered only when a failed search is
   proven by the camera not jumping, and the level that actually worked is saved for
   next time.

---

## Requirements (macOS)

- Apple Silicon Mac
- [MuMuPlayer Pro](https://www.mumuplayer.com/mac/) with Whiteout Survival installed
- Homebrew `android-platform-tools` (adb) and `uv`
- Python 3.10+ (managed by `uv`)

```bash
brew install android-platform-tools uv
```

## Emulator setup (once)

1. Create a MuMuPlayer Pro instance with a **1080×2460 @ 420dpi** display
   (Pixel 8 profile). Enable adb; the first instance listens on `127.0.0.1:16384`.
2. The shipped ROIs assume a ~120px top safe-area inset. MuMu's own cutout setting
   maxes out at 72px, so enable the tall cutout overlay inside Android instead
   (126px @ 420dpi, survives reboot):

   ```bash
   adb connect 127.0.0.1:16384
   adb -s 127.0.0.1:16384 shell cmd overlay enable \
     com.android.internal.display.cutout.emulation.tall
   ```

## Quick start

```bash
git clone <this repo> wos-bot && cd wos-bot
uv sync

cp db/account.json.example db/account.json
# edit db/account.json with your account(s) — see Configuration below

./run.sh
```

`run.sh` does the rest, in order:

1. Pins adb to `127.0.0.1:${WOS_ADB_PORT:-16384}` and exports
   `OCR_CAPTURE_TOOL=adb` (no scrcpy/v4l2 needed on macOS).
2. **Gates on the real framebuffer**: takes a screencap and exits unless it is
   exactly 1080×2460 — `wm size` output is not trusted.
3. Starts the OCR server and waits for it to come up (PaddleOCR downloads models on
   first run; this can take a while once).
4. Launches the bot as `python -m Main.main` and opens the interactive task selector.

---

## Task selection

At startup, `Main/task_menu.py` shows a menu. Select tasks by number (`1,3,6`),
key (`vip,mail,heal`), or title; press **Enter** (or `all`/`default`/`*`) for the
full default list:

| # | Task | # | Task |
| :-- | :--- | :-- | :--- |
| 1 | VIP Rewards | 11 | Labyrinth |
| 2 | Exploration Idle Income | 12 | Alliance Auto Join |
| 3 | Continue Exploring | 13 | Alliance Chests |
| 4 | Mail Rewards | 14 | Alliance Tech |
| 5 | Life Essence | 15 | Alliance Help |
| 6 | Train Troops | 16 | Alliance Triumph |
| 7 | Arena | 17 | Heal |
| 8 | Chief Order | 18 | World Gather |
| 9 | Ally Treasure | 19 | Missions Reward |
| 10 | Pet Exploration | | |

Tasks run in order; players completed within the last 3 hours are skipped
automatically.

---

## Configuration

`db/account.json` (never committed — see Security):

```json
{
  "your_email@gmail.com": {
    "priority": 1,
    "player": [
      { "id": "12345678", "name": "Your Chief Name" }
    ]
  }
}
```

| Field | Description |
| :--- | :--- |
| `priority` | Processing order — lower runs first |
| `id` | Player ID from the in-game Chief Profile |
| `name` | Character name used for character/account switching |

Multiple characters under one email are supported — the bot switches between them
automatically and verifies after each switch that it is still on the expected email.

With exactly one configured email the bot never opens the account-switch (Google
sign-in) flow: it runs one pass over that email's characters, prints
`Single account configured (<email>) - pass complete, exiting.`, and exits 0.

Environment knobs (all optional, defaults set by `run.sh`):

| Variable | Default | Purpose |
| :--- | :--- | :--- |
| `WOS_ADB_PORT` | `16384` | MuMu instance adb port |
| `WOS_ADB_SERIAL` | `127.0.0.1:16384` | Fails loudly if set but the device is absent — no silent fallback |
| `OCR_CAPTURE_TOOL` | `adb` | Bypasses the Linux scrcpy/v4l2 path entirely |
| `OCR_RAM_CAP_GB` | `16` | RAM guard reports honestly; the engine-recycle actuator stays dormant on macOS |

---

## Project structure

```text
wos-bot/
├── run.sh                      # macOS launcher: adb pin, framebuffer gate, OCR server, bot
├── Main/
│   ├── main.py                 # Entry point, account loop, task execution
│   └── task_menu.py            # Interactive task selector and registry
├── core/
│   ├── ocr.py                  # FastAPI OCR server
│   ├── core.py                 # Vision engine (template matching, OCR)
│   ├── coord_utils.py          # Canonical 1080×2460 base, percent↔pixel conversion
│   ├── player_profile.py       # Per-player profile persistence (db/players/<id>.json)
│   └── change_player.py        # Account/character switching
├── cmd_program/
│   ├── screen_action.py        # ADB touch/swipe actions
│   └── screen_stream.py        # scrcpy streaming (Linux-only, unused on macOS)
├── usecases/                   # Feature modules (gather, alliance, arena, …)
├── db/
│   ├── account.json.example    # Safe template — the real account.json is gitignored
│   ├── completion_log.txt      # Per-player cooldown store (gitignored)
│   └── players/                # Per-player profiles (gitignored, except example.json)
├── references/
│   ├── icon/                   # PNG templates for icon matching
│   └── TextArea/               # Percentage-based ROI definitions per screen
├── tests/                      # Offline suite — no emulator/adb/network required
└── docs/port/                  # Full Mac-port decision record (start at INDEX.md)
```

---

## Security

`db/account.json`, `db/players/*.json`, and `db/completion_log.txt` contain account
credentials and real player IDs. All are gitignored (only the templates
`db/account.json.example` and `db/players/example.json` are tracked) — keep it that
way, and never share the real files.

---

## Known hazards & gotchas

- **uv version**: a `~/.local/bin/uv` at 0.6.16 silently downgrades `uv.lock` from
  revision 3 to 2 on any `uv add`. Use `/opt/homebrew/bin/uv` for lockfile-mutating
  commands; `uv run` is unaffected.
- **Wrong-resolution emulator**: `run.sh` refuses to start if the framebuffer isn't
  1080×2460. Fix the MuMu display settings rather than bypassing the gate.

## Troubleshooting

- **OCR server never comes up** — first run downloads PaddleOCR models; `run.sh`
  waits up to 4 minutes. If port 8000 is occupied: `lsof -i :8000`, kill the stale
  process, rerun.
- **adb device missing** — `adb kill-server && adb connect 127.0.0.1:16384`, and
  check the MuMu instance is running with adb enabled.
- **Taps land wrong / OCR misses** — verify the framebuffer
  (`adb exec-out screencap -p | file -`) and the cutout overlay from Emulator setup.

## Testing

```bash
uv run pytest tests/ -q    # 40 passed — fully offline
```

---

## Linux / Windows

This branch targets macOS. For the original Linux (scrcpy + v4l2) and Windows
instructions, see the upstream project at the pinned commit `c7951f19`.

---

## License & Disclaimer

This is a personal fork of an upstream project that ships no LICENSE file; it is not
intended for public distribution.

**Use at your own risk.** Automation may violate Whiteout Survival's Terms of
Service and can cost you the account it runs on — the account-risk analysis in
[`docs/port/02-ceo-review.md`](docs/port/02-ceo-review.md) is required reading
before running this on an account you care about. The authors are not responsible
for suspensions, bans, or loss of progress.
