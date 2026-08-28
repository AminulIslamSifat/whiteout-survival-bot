"""Shared pytest setup for the wos-bot test suite.

Must run before any test module imports core.ocr: core/ocr.py:870 calls
take_preferred_screen_capture_tool() at module scope, which prompts
interactively unless OCR_CAPTURE_TOOL is already set in the environment.
pytest imports conftest.py before collecting test modules, so setting the
env var here (module top level) is sufficient to keep the whole suite
non-interactive.
"""
import os
import sys

# tests/ has no __init__.py, so pytest's default "prepend" import mode puts
# tests/ itself on sys.path, not the repo root. Add the repo root explicitly
# so `import core...` / `import cmd_program...` resolve the same way they do
# for the app's own entry points.
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

os.environ.setdefault("OCR_CAPTURE_TOOL", "adb")
