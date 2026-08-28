# Mac port — full decision record

Everything about porting this bot to Apple Silicon: the origin brief, the reviews that
challenged it, the decisions made, and the execution ledger. Consolidated here on
2026-08-28 so the record lives with the code instead of scattered across
`~/.claude`, `~/.gstack` and `~/Downloads`.

**Upstream pin:** `c7951f19e8cdb7fadcdf947a0bc0c6e74b6b951f` (2026-05-02, tagged 0.8.0).
Work branch: `mac-port`. Upstream `main` has not moved since May 2026.

## Read in this order

| File | What it is |
|---|---|
| `00-original-brief.md` | The handoff brief that started this. Research on the WOS bot ecosystem, two candidate codebases, rejected alternatives, risks. **Three of its technical claims are wrong** — see below. |
| `01-plan-reviewed.md` | The implementation plan, after an engineering review, a Codex outside voice, and a CEO review. Ends with the GSTACK REVIEW REPORT. |
| `02-ceo-review.md` | Scope and premise challenge. The uncomfortable finding about account risk is here. |
| `03-test-plan.md` | What to test and where, including the parts that need a live emulator. |
| `04-execution-ledger.md` | Task-by-task execution record with every ruling made and what each costs if wrong. |
| `05-final-review-findings.md` | The five findings from the final whole-branch review, with root causes. |
| `briefs/` | The exact requirements handed to each implementer. |
| `reports/` | What each implementer did, with verification output. |
| `decisions/` | gstack decisions + learnings as JSONL. |

## What the brief got wrong

Verified against source at the pinned SHA, not assumed:

1. **The v4l2loopback/sudo patch it prescribes is unnecessary.** `core/ocr.py:301-308`
   returns early on the adb path and never reaches the loopback bootstrap. Setting
   `OCR_CAPTURE_TOOL=adb` (`core/ocr.py:118-122`) bypasses it with zero code changes.
   Confirmed at runtime: the server prints `✅ Using Capture Tool from Env: ADB`.
2. **The repo is not hardcoded to pixels.** ROIs in `references/TextArea/*.json` are
   percentages, and `core/coord_utils.py` declares the canonical 1080x2460 base.
3. **The 4px bug pointed the other way.** Taps were always correct; the OCR path squashed
   frames 0.16% and carried a `y1 -= 5` fudge to compensate.

It also missed two live bugs: `input_text()` raised `TypeError` on every call (breaking
the gathering task), and the RAM guard was completely inert on macOS.

## What was decided, and why

- **Option A (Python port), not Frostguard.** Faster to a working daily loop.
- **Account choice is an explicit up-front decision, not deferred.** The CEO review found
  the plan's own mitigation ("run on an account you accept losing") cancels its purpose:
  the chores worth automating only matter on an alliance main. Read `02-ceo-review.md`.
- **RAM sensor repaired, actuator held dormant.** `OCR_RAM_CAP_GB` defaults to 16 so the
  guard reports honest memory without arming an engine-recycle path that has never run on
  macOS. Lower it to 3 once the daily loop is stable.
- **`STREAM_WIDTH`/`STREAM_HEIGHT` deliberately left at 2456.** They still feed a
  Linux-only scrcpy path that cannot be tested from a Mac. Not an oversight.
- **`WOS_ADB_SERIAL` fails loudly when set but absent.** An earlier decision to fall back
  silently was reversed — silent substitution would tap a different device with rescaled
  frames and no error.

## State as of 2026-08-28

Done and verified:

- `uv run pytest tests/ -q` → **30 passed**, no emulator, no adb, no network.
- `OCR_CAPTURE_TOOL=adb uv run python -m core.ocr` → Uvicorn on `:8000`.
- `paddleocr 2.10.0` + `paddlepaddle 3.2.0` confirmed working together on arm64 —
  the plan's single unverified assumption, now retired.
- `_normalize_frame_resolution` returns the *same object* for a 1080x2460 frame; the
  spurious resize is genuinely gone.

Blocked on hardware you must set up by hand:

- **Phase 2.5** — ROI overlay baseline against an unpatched screenshot.
- **Phase 5** — first runs (mail, gather, then a re-run proving cooldowns skip them).
  Needs MuMuPlayer Pro, the game installed, an account, and prepared in-game state.

Next step: `brew install --cask android-platform-tools`, then MuMuPlayer Pro with the
instance display set to exactly 1080x2460.

## Operational gotcha

`which uv` resolves to `~/.local/bin/uv` **0.6.16**, which silently downgrades
`uv.lock` from revision 3 to 2 on any `uv add`. Use `/opt/homebrew/bin/uv` for
lockfile-mutating commands. `uv run` is unaffected.
