# Changelog

All notable changes to the WOS Mac bot are documented here.
Format: [Keep a Changelog](https://keepachangelog.com/); versions follow
`MAJOR.MINOR.PATCH.MICRO` (the `VERSION` file is the source of truth).

## [0.9.0.0] - 2026-08-30

First versioned release of the macOS fork: the full Mac port plus a new
Apple Vision OCR engine, live-verified end to end.

### Added
- **Runs natively on Apple Silicon Macs** against MuMuPlayer Pro over adb —
  one command (`./run.sh`) pins the device, gates on the real framebuffer
  (1080×2460), boots the OCR service, and opens the task selector.
- **Apple Vision OCR engine**: text reads now run on the Neural Engine in
  ~17ms per region (vs ~63ms–2.7s under PaddleOCR), with the recognition
  revision pinned so macOS updates can't silently change behavior. Rollback
  is one variable: `OCR_ENGINE=paddle`.
- **Self-healing reads**: a broken Vision session falls back to PaddleOCR
  automatically (per-read for missing values, session-wide after repeated
  engine errors), and never downloads models mid-run.
- **Burn-in instrumentation**: every read is logged (engine, latency,
  fallback, RSS, digit cross-checks against Paddle) to `logs/ocr_burnin.jsonl`;
  `scripts/burnin_report.py` prints the go/no-go verdict for retiring Paddle.
- **Per-player profiles** with an adaptive gather node level: the bot
  remembers the highest resource level each account can find, probes one
  level up each run, and only lowers it on verifiable evidence.
- **Single-account mode**: with one configured account the bot never enters
  the account switcher.
- Fixture-based OCR merge gate: frozen expected-text oracle over committed
  screens, including digit-exact assertions, run by the test suite.

### Changed
- Search success on the world map is detected by the coordinate-bar camera
  jump instead of the transient toast — far more reliable.
- The OCR service listens on a dedicated port (default 8210, `OCR_PORT`) so
  a dev server on 8000 can never impersonate it; the launcher fails loudly
  on orphan servers and dead children instead of proceeding blind.
- Gather level changes persist only with UI-confirmed evidence, both on
  deploy and on level-down, so OCR flakes can't corrupt stored profiles.
- PaddleOCR loads lazily: vision-mode boots reach ready in seconds with no
  model download and a ~150MB baseline footprint.

### Fixed
- Stamina ground-truth region no longer clips three-digit values.
- Launcher hardened against stdin-draining adb calls, unpinned devices, and
  import-path breakage; RAM-guard now reads real RSS on macOS.
- Screenshot and adb failures surface loud, specific errors (device cache
  invalidated, stderr carried) instead of silent Nones.

### Tests
- 146 offline tests (from 0 at fork): engine dispatch/fallback/breaker,
  byte-identical Paddle parity vs the pre-swap baseline, gather state
  machine, burn-in verdict math, coordinate/device/profile units, and the
  frozen-text fixture crop suite.
