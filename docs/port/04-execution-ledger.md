# SDD ledger — plan: /Users/melsawah1/.claude/plans/glowing-napping-lampson.md

Repo: /Users/melsawah1/Developer/wos-bot @ c7951f19 (upstream pin), branch mac-port
Spec: the plan is its own spec; upstream brief ~/Downloads/wos-mac-port-brief.md is
      superseded where the plan's "Corrections to the brief" section contradicts it.

## Already done before this skill started
- Task 1: complete (clone + pin to c7951f19 + branch mac-port; verified rev-parse)
- Task 10: complete (commit 8da9b6d, .gitignore for db/account.json + db/players/*.json;
  verified with git check-ignore)
- Task 12: complete (NO-OP — verification only, no code change needed).
  Traced the None chain: _post_json_with_replay (core/core.py:97-127) -> req_ocr
  (:145-146 `if not data: return None`) -> req_temp_match (:169-170 same) ->
  tap_on_template (`if not results: return None`) -> req_text (`if res is None:
  print("OCR failed"); return None`). Upstream handles it correctly end to end.

## Pre-flight conflict scan

Environment finding (not in plan): /Users/melsawah1/Developer is a case-INSENSITIVE
APFS volume and /Users/melsawah1/Developer/WOS already exists (WOS-discord-manager).
`git clone ... wos` would have collided. Ruling: cloned to `wos-bot` instead.
Cost if wrong: none, cosmetic path difference from the plan text.

| Pair | Shared surface | Producer -> consumer | Finding |
|---|---|---|---|
| T4 x T5 | cmd_program/screen_action.py | T4 renames SCREEN_* -> BASE_* at :9-10; T5 edits tap/swipe/long_press/take_screenshot which READ those names | CONFLICT — same functions, must be ordered |
| T4 x T6 | cmd_program/screen_action.py | T4 :9-10 constants; T6 :150-157 input_text | Low — disjoint regions, same file |
| T5 x T6 | input_text device handling | T5 routes all call sites through the lazy resolver; T6 deletes input_text's device_id param | DIRECT CONFLICT — both rewrite the same signature |
| T5 x T11 | run_adb_command error path | T5 requires "failed command invalidates cache"; T11 rewrites that exact except block :51-56 | DIRECT DEPENDENCY — one change, not two |
| T4 x T7 | core/ocr.py | T4 :86,:152-160,:678-679; T7 :223-234 | Clean — disjoint regions |
| T7 x T9 | pyproject.toml | T7 adds psutil; T9 adds pytest dev-dep | Low — sequential edits, no semantic overlap |
| T9 x T4,T5,T6 | tests exercise their output | T9 asserts on code A/B produce | ORDERING — T9 must run last |
| T8 x all | run.sh (new file) | exports WOS_ADB_SERIAL (T5 reads), OCR_RAM_CAP_GB (T7 reads), OCR_CAPTURE_TOOL (T9 conftest mirrors) | Interface only, no file conflict |

Per-task self-consistency: T4 keeps STREAM_* for start_screen_stream(:212) while
routing normalize through BASE_* — internally consistent. T5's $WOS_ADB_SERIAL matches
T8's export. T9's conftest OCR_CAPTURE_TOOL matches plan correction #1. No task
contradicts itself.

Ruling: batch T5+T6+T11 into ONE dispatch. They are three descriptions of one
rewrite of screen_action.py's adb layer (device resolution, its error path, and the
one caller whose signature depends on both). Dispatching them separately guarantees
three-way edit conflicts and rework.
Cost if wrong: a larger single review surface than three small ones.

Ruling: execution order A(T4) -> B(T5+T6+T11) -> C(T7) -> D(T8) -> E(T9).
A precedes B because B's functions read the constants A renames.
Cost if wrong: rework on screen_action.py if the order is actually irrelevant.

Ruling: T3 (Phase 2.5 ROI baseline) and Phase 5 (first runs) are NOT executable in
this session — both require MuMuPlayer Pro installed via GUI, the game installed, and
a manual account login. Marked BLOCKED, not skipped. The plan's own gate ("do not
install MuMu until the smoke test passes") is respected; the human does the install.
Cost if wrong: none — this is a capability limit, not a judgment call.

## Execution
- Task 2: complete (NO COMMIT — verification gate only).
  T2 GATE PASSED. paddleocr 2.10.0 + paddlepaddle 3.2.0, CPython 3.12.11, arm64:
  constructor accepted all real args (det_limit_side_len=1024, cpu_threads=4,
  ir_optim=True, layout=False, table=False, formula=False); ocr.ocr(img, cls=False)
  returned [None] on a blank image; exit 0. Models cached to ~/.paddleocr/whl/.
  Ruling: the WebSearch claim that PaddleOCR 2.x is incompatible with PaddlePaddle
  3.x is FALSE for this pairing. The committed uv.lock was the stronger evidence.
  Cost if wrong: none — this is a passing runtime observation, not an inference.
- Task 4 (Batch A): complete (commits 8da9b6d..e1631c9, review clean — spec 8/8, quality approved)
  Verified independently: zero surviving SCREEN_WIDTH/SCREEN_HEIGHT refs outside .venv
  and core/backup (dead upstream copies); all importers pull function names only.
  Reviewer's one ⚠️ was self-resolved by its own repo-wide grep — not a gap.
- Task 4: minor (deferred): ocr.py historical-bug comment cites "ocr.py:678", a line
  that no longer exists. Stale self-reference. Triage at final review.
- Task 4: minor (deferred): implementer stubbed `adb` on PATH to run its verification
  (adb genuinely not installed yet — Phase 2). Sandbox-only, no repo change.
- Task 5+6+11 (Batch B): Ruling: implementer added `except OSError` around the internal
  resolve_device() calls, which the brief did not specify. ACCEPTED. get_adb_devices()
  shells out to `adb devices` unguarded, so with adb absent its OSError would escape a
  function whose entire job is graceful device resolution. The catch wraps exactly one
  call; CalledProcessError and FileNotFoundError remain on the real adb invocation
  (:88,:95,:178,:185). Narrower than the alternative of letting it propagate.
  Cost if wrong: OSError is broader than FileNotFoundError, so a genuinely unexpected
  OS-level fault during device probing would be reported as "no device" instead of
  surfacing. Low: the only syscall in that path is spawning adb.
- Task 5+6+11: Ruling: implementer could not observe true FileNotFoundError because this
  sandbox raises PermissionError for any missing binary. ACCEPTED as an environment
  artifact — both are OSError subclasses and the handler covers both. Re-verify the adb
  missing-binary message once adb is actually installed in Phase 2.
  Cost if wrong: the "adb not installed" message may not fire on the exact path intended;
  worst case is a less specific error string, not a functional failure.
- Task 5+6+11 (Batch B): complete (commits e1631c9..17cda1b, review clean — spec 13/13,
  quality approved). Import no longer probes adb; _device_id None at import; input_text
  no longer raises TypeError; no bare except Exception remains.
  ⚠️ resolved by controller: "device-drop recovery untested against live adb" is the same
  hardware blocker as T3/Phase 5, not a code gap. Logic verified by inspection; re-verify
  on real hardware in Phase 2.
- Task 5+6+11: minor (deferred): six new `raise RuntimeError(...)` sites drop `from e`,
  losing the traceback chain (str(e) is still embedded). Triage at final review.
- Task 5+6+11: minor (deferred): "no device resolved" message reports the WOS_ADB_SERIAL
  env value rather than an attempted serial. Wording only.
- Task 7+8 (Batch C+D): commits 15be5bf (T7), cd70e27 (T8). Verified by controller:
  uv.lock revision=3 preserved, psutil>=7.2.2 in pyproject, lock diff only +30 lines,
  run.sh created and executable.
- OPERATIONAL FINDING (affects all future work in this repo): PATH resolves `uv` to
  /Users/melsawah1/.local/bin/uv version 0.6.16 (2025-04-22), which is OLDER than the
  repo's lockfile format. A bare `uv add` / `uv lock` with it silently DOWNGRADES
  uv.lock revision 3 -> 2 and rewrites ~1838 lines. Homebrew's uv at
  /opt/homebrew/bin/uv is current (0.12.7). `uv run` is unaffected.
  Use /opt/homebrew/bin/uv explicitly for any lockfile-mutating command.
- SYSTEM CHANGE MADE WITHOUT ASKING (surface to the human): the Batch C+D implementer
  ran `brew upgrade uv`, taking Homebrew's uv from 0.7.3 to 0.12.7. This is a machine-
  level dev-toolchain change outside the worktree. Not destructive and it was in service
  of not corrupting uv.lock, but it was not authorised. Flagging rather than reverting —
  reverting a version bump is riskier than leaving it.
- Task 7+8 (Batch C+D): complete (commits 17cda1b..cd70e27, review clean — spec all ✅,
  quality approved, zero findings).
- Task 8: minor (deferred): run.sh readiness loop does not hard-fail on total timeout —
  after 4 min it proceeds and main.py hits connection-refused. Degrades gracefully via
  _post_json_with_replay -> None -> "OCR failed", but a hard fail would be better.
  This came from the brief verbatim, not implementer deviation. Triage at final review.
- CONTROLLER VERIFICATION (functional, not inspection): with OCR_CAPTURE_TOOL=adb,
  `import core.ocr` succeeds in 3.1s and prints "✅ Using Capture Tool from Env: ADB".
  This proves plan correction #1 (the env hatch bypasses BOTH the interactive prompt at
  ocr.py:848 and the Linux v4l2loopback path). Batch A's fix also proven functionally:
  _normalize_frame_resolution(1080x2460 frame) returns the SAME OBJECT (no resize);
  an off-height frame resizes to (2460,1080). The coordinate bug is fixed, not just edited.
- Task 9 (Batch E): commit faedea2. CONTROLLER-VERIFIED: `uv run pytest tests/ -q` ->
  29 passed, 1 warning, 2.75s. uv.lock revision=3 intact. Root assertion-free
  test_coords.py deleted. Zero source files touched (only tests/, pyproject, uv.lock).
- Task 9: Ruling: implementer added `sys.path.insert` for the repo root in
  tests/conftest.py, a deviation from the brief. ACCEPTED. pytest's default import mode
  does not put the repo root on sys.path without tests/__init__.py, so `import core...`
  would fail. It is test-scaffolding only and touches no source.
  Cost if wrong: none functionally; a tests/__init__.py or a pyproject pytest config
  would be marginally more idiomatic.
- Task 9 (Batch E): complete (commits cd70e27..4fc3e11, review clean — spec all ✅,
  quality approved). Reviewer specifically confirmed non-tautology: "Reverting either
  historical bug (coordinate drift or the clear_input TypeError) would fail this suite."
  ⚠️ resolved by controller: adb-absence representativeness is moot — the tests
  monkeypatch get_adb_devices/run_adb_command, so they pass with or without adb present.
- Task 9: minor (deferred): tests/test_input.py:14,22,31 patch sa._device_id then also
  fully replace run_adb_command, making the _device_id patch dead. Cosmetic.

## Status of remaining plan tasks
- Task 3 (Phase 2.5 ROI overlay baseline): BLOCKED — needs MuMuPlayer Pro installed via
  GUI + the game installed + a manual login. Not executable in this session.
- Phase 5 (first runs: mail, gather, cooldown re-run): BLOCKED — same, plus it needs an
  account decision the human has deferred and prepared in-game state.

## Final whole-branch review (opus) + fix wave
- Final review found 1 CRITICAL the per-task reviews structurally could not:
  `uv run core/ocr.py` died with a circular ImportError. Running the file AS A SCRIPT puts
  <repo>/core on sys.path[0], so the `core.coord_utils` import that Task 4 added to
  screen_action.py resolved `core` -> core/core.py instead of the package. My own
  functional check had imported with the repo root already on sys.path — the TEST
  configuration, not the PRODUCTION launch. Controller-verified both ways before acting.
- Fix wave: commit b69e4d5, all 5 findings fixed in one dispatch.
- Scoped re-review: all 5 ADDRESSED, no new breakage, "ship it".
- CONTROLLER-VERIFIED after fixes: 30 tests pass; `python -m core.ocr` reaches
  "Uvicorn running on http://127.0.0.1:8000"; run.sh:18 + README 145/227/445 module form;
  core/ocr.py:85 default 16.0; run.sh:27 fatal readiness check.
- Task final: complete (commits 4fc3e11..b69e4d5, re-review clean, 1 parked)
- PARKED: `ocr_endpoint()` (core/ocr.py:806) special-cases only MemoryError, so other
  exceptions reach the HTTP client as an opaque 500 rather than a structured error.
  Ruling: park as fast-follow, not a blocker. It predates this branch for every non-
  MemoryError exception, was never in the finding's scope, and the fix still improved
  matters (a correctly-typed exception carrying the real message, visible in the server's
  own traceback, replacing a misleading UnboundLocalError).
  Cost if wrong: when the OCR server fails mid-run, the bot logs "500 Server Error"
  instead of the real cause, making a live failure slower to diagnose.

## Workspace retention
Ruling: NOT deleting this workspace, contrary to the skill's default. The plan is not
complete — Task 3 (ROI baseline) and Phase 5 (first runs) are blocked on hardware the
human must install by hand. This ledger is the handoff document for resuming them.
Cost if wrong: a scratch directory persists in a gitignored path.

## 2026-08-29 — Emulator bring-up, Phase 2.5, first live runs (Phase 5)

Environment established (all verified over adb, not from config):
- MuMuPlayer Pro instance 0: 1080x2460 @ 420dpi, Pixel 8 profile (GC3VE), adb port
  pinned to 16384 via `customAdbPort` (was auto/26624). Homebrew adb 37.0.1 on PATH.
- `dynamicFpsEnable` OFF (bot samples stills; a 15fps idle throttle mid-transition
  frame is an OCR hazard), `maxFpsLimit` 30 (frees cores for Paddle).
- vm.json stores landscape-native `framebufferWidth:2460, framebufferHeight:1080` +
  `deviceOrientation:1`. Looks transposed; is not. Trust `screencap`, never the config.

### Phase 2.5 finding — the ROIs assume a ~120px top safe-area inset
The shipped `references/TextArea/*.json` were captured on a device whose game viewport
started ~120px down (notch/safe-area). On a cutout-less emulator every top-anchored ROI
missed low by that amount while bottom-anchored ROIs matched within 5px — a safe-area
shift, NOT a uniform offset and NOT a scaled viewport (both models tested and falsified
against ChiefProfile anchors spanning the full height). dx was within ±2px everywhere.
- Fix: `adb shell cmd overlay enable com.android.internal.display.cutout.emulation.tall`
  (AOSP cutout emulation, 126px inset at 420dpi). Survives emulator reboot. MuMu's own
  displayCutout setting yields only 72px on every shape — not enough.
- Result: Home.Mail tabs went 0/9 → 5/9 exact + clipped-partial reads that the
  expand-retry ladder (core.py try_match expand_px) recovers. Home bottom bar unaffected.
- The 2456-tall reference frames in frames/ are artifacts of the historical squash bug.

### Live-run bugs found and fixed (this commit)
1. run.sh launched `Main/main.py` by path → `sys.path[0]=Main/` →
   `ModuleNotFoundError: cmd_program`. Same class as the final review's CRITICAL
   (core/ocr.py as script); the fix wave converted only core.ocr. Now `-m Main.main`.
2. adb drains stdin. `start_game()`'s `subprocess.run` inherited the pipe and ate the
   task-selector input → EOFError. `stdin=DEVNULL` there; `</dev/null` on run.sh's adb
   lines. Diagnosed by elimination: uv/curl proven innocent, adb guilty.
3. `start_game()` used bare `adb` with no `-s` — fails "more than one device" whenever
   MuMu registers its emulator-5554 alias next to 127.0.0.1:16384. Now honors
   WOS_ADB_SERIAL, consistent with the resolver's loud-fail design.
4. PYTHONUNBUFFERED=1 in run.sh: block-buffered stdout delayed progress lines minutes
   when piped, which nearly defeated the change_account watchdog (below).

### Phase 5 status (burner account, lord846646676)
- Mail: collected for real — the mailbox badge (2 unread) cleared; completion_log.txt
  gained `846646676|<ts>`. Selector driven with `printf 'mail\n' | ./run.sh`.
- Cooldown re-run: PASSED — "Skipping lord846646676 … completed recently". This is the
  v1 acceptance criterion. Correction to the plan: the cooldown store is
  db/completion_log.txt (id|epoch|iso lines); no code writes db/players/*.json
  `last_visit` — that claim in the plan was stale.
- Gather: in progress at time of writing; result recorded below.

### Operational hazard — change_account on a guest account
`run_bot` unconditionally calls `change_account()` after the last player, even when all
players were skipped by cooldown. On a guest (unlinked) account that flow taps
Settings → Account → Change Account → **Sign in with Google** before it can discover the
target email is absent. On this burner that risks binding it to the Play-Store Google
account or losing the guest session. Runs are therefore wrapped in a marker watchdog
(kill main.py on "Marked completed|Skipping|Progressing to the next email") until a real
single-account mode exists. One run reached the Change Account dialog before the
watchdog matured; it was killed with the dialog open and nothing tapped.

### Gather: done (2026-08-29 19:08)
Three failures, three distinct causes, all fixed and committed:
1. First-visit world-map onboarding popup (fresh-account state) — cleared by hand once.
2. World/City toggle drops taps during the zoom animation — tap-then-assume raced;
   fixed with verified entry (read, tap, settle, re-read). The search template scores
   0.97 once the map actually shows; both "Seach Icon not found" exits were this.
3. Hardcoded node level 8: a young account has no level-8 nodes, and the
   'No suitable resources' toast is gone before the Gather wait finishes (39 full-frame
   OCR checks never caught it). Reliable signal, from the operator watching live: a
   successful search JUMPS THE CAMERA; a failed one leaves the coordinate bar
   ("#4653 X:1019 Y:308", ROI [25,85.2,70,89.0]) unchanged. gather() now compares
   coords before/after and steps the level down on no-movement.
Verified live: 8→7→6, then Gather → Equalize → Deploy; world map shows "Marching 1/1"
with the march line, camera moved to X:912 Y:292, completion_log updated, and
db/players/846646676.json persisted gather.node_level=6 — the per-player profile
(example.json schema, previously dead storage) now evolves with the account.

**v1 acceptance (D12) is met**: mail collected + gather deployed + immediate re-run
skips via cooldown. Alliance tasks and the other 15 modules remain unproven (burner
limits + out of scope). Fast-follows parked: single-account mode so run_bot cannot
reach change_account on a guest; ocr_endpoint opaque-500.

## 2026-08-29 — Single-account mode: done

Resolves the guest-account hazard recorded above ("Operational hazard —
change_account on a guest account") and closes the first fast-follow parked under
the v1 acceptance note.

- `run_bot` now guards the account-switch tail: when `len(email_list) == 1` it
  prints `Single account configured (<email>) - pass complete, exiting.` and
  returns instead of calling `change_account()`. The guard sits after the inner
  per-character loop, so it covers both the tasks-ran and all-skipped-by-cooldown
  paths — the exact hazard path. Auto-detected, no env flag: switching to the same
  email is always pointless and risky, so this is a correctness fix, not a mode,
  and the safety must not depend on remembering a flag.
- Clean exit (code 0) retires the external marker watchdog. Note for anyone still
  running it: "Progressing to the next email" no longer prints on 1-email configs.
- `start_game()` / `init_database()` moved from module scope into Main/main.py's
  `__main__` block — runtime order for `python -m Main.main` unchanged, but
  `import Main.main` is now side-effect-free, which enabled unit tests.
- 3 tests added (tests/test_run_bot.py): single email runs tasks then exits with
  change_account never called; single email all-on-cooldown still exits without
  change_account; two emails still progress with the existing loud-fail on a
  failed switch. Suite: 37 → 40 passed, fully offline.
