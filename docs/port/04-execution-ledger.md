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
