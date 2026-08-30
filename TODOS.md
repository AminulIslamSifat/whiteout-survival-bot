# TODOS

Deferred work with context. Each entry carries enough reasoning to pick up cold.

## OCR lock removal (post-burn-in)
- **What:** Drop the global `_ocr_lock` for vision-path reads (Vision is
  thread-safe; the lock exists for Paddle).
- **Why:** Multi-ROI requests currently serialize; parallel vision reads are a
  free ~2x on batch reads.
- **Context:** Deliberately kept in v1 (decision 1A, 2026-08-29 eng review) so
  the engine swap and a concurrency change never share a diff. Do it only
  after the burn-in exit criteria pass (`scripts/burnin_report.py`).
- **Where to start:** `core/ocr.py` `_ocr_lock` usage in `run_ocr`; keep the
  lock for paddle-active sessions.
- **Effort:** S (CC ~15min). **Priority:** P3.

## Template-digit fallback -> full Paddle removal
- **What:** Replace the lazy-Paddle zero-item fallback with a small digit
  template matcher, then drop `paddleocr`/`paddlepaddle` from dependencies.
- **Why:** ~1GB lighter install and one engine total.
- **Context:** Rejected for v1 (D4.3): the Paddle fallback is proven and the
  only known zero-item case is isolated badge digits. REOPEN TRIGGER: burn-in
  FAILS its fallback-rate criterion (>=1% of decisions), or a clean burn-in
  exit reopens the broader Paddle-removal decision with data.
- **Where to start:** `_recognize_crop_unlocked` in `core/ocr.py`;
  `tests/test_fixture_crops.py` FurnaceLevel case is the acceptance test.
- **Effort:** M (CC ~1h). **Priority:** P3.

## Linux capture path removal
- **What:** Delete the scrcpy/v4l2loopback capture path (`_try_start_stream`,
  `cmd_program/screen_stream.py` usage) that macOS bypasses via
  `OCR_CAPTURE_TOOL=adb`.
- **Why:** Dead weight on this fork; the fork is macOS-only in practice.
- **Context:** Deferred twice (CEO review item 5): aesthetics-only on
  upstream-diverged code; nothing breaks by keeping it.
- **Effort:** S (CC ~15min). **Priority:** P3.

## 2x render probe (post-burn-in, in plan)
- **What:** Bounded probe of MuMu at 2160x4920 @ 840dpi (same dp layout as the
  1080x2460 base, so ROIs/taps/templates survive the uniform 0.5x normalize).
- **Why:** Vision reads sharper input; may fix badge digits natively.
- **Context:** ACCEPTED scope, sequenced post-burn-in with explicit
  adopt/reject criteria — see docs/designs/vision-ocr-swap.md. Ships with a
  `WOS_FRAMEBUFFER` parameterization of the run.sh gate (default stays strict).
- **Effort:** M. **Priority:** P2 (after burn-in exit).

## Fresh ID-free fixture captures
- **What:** Capture Home/World screens at the restored 1080x2460 config, mask
  any chat/name surfaces, freeze expected text, add to
  tests/fixtures/crop_manifest.json (committed) and tests/fixtures/local/
  (gitignored, ID-bearing screens).
- **Context:** E-3A oracle; emulator was offline at implementation time, so
  v1 ships with the committed legacy frame as the oracle. Do on next bot run.
- **Effort:** S (CC ~30min with emulator up). **Priority:** P2.
