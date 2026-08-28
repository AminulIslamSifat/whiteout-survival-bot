"""Tests for cmd_program/screen_action.py::input_text.

Locks down the fix for a real bug: input_text used to call
clear_input(count=..., device_id=...), but clear_input has no device_id
parameter, so every call raised TypeError. Its only live caller is
usecases/gather.py:112 -> input_text("8").
"""
import inspect

import cmd_program.screen_action as sa


def test_input_text_signature_has_no_device_id_param():
    sig = inspect.signature(sa.input_text)
    params = sig.parameters
    assert "device_id" not in params
    assert list(params) == ["text", "backspace"]
    assert params["backspace"].default == 6


def test_input_text_does_not_raise(monkeypatch):
    monkeypatch.setattr(sa, "_device_id", "emulator-5554")
    calls = []
    monkeypatch.setattr(sa, "run_adb_command", lambda cmd, device_id=None: calls.append(cmd))

    sa.input_text("8")  # must not raise TypeError

    assert calls  # something was recorded


def test_input_text_sends_text_and_trailing_keyevent_66(monkeypatch):
    monkeypatch.setattr(sa, "_device_id", "emulator-5554")
    calls = []
    monkeypatch.setattr(sa, "run_adb_command", lambda cmd, device_id=None: calls.append(cmd))

    sa.input_text("8")

    assert ["shell", "input", "text", "8"] in calls
    assert calls[-1] == ["shell", "input", "keyevent", "66"]


def test_input_text_backspace_default_clears_six_times(monkeypatch):
    monkeypatch.setattr(sa, "_device_id", "emulator-5554")
    calls = []
    monkeypatch.setattr(sa, "run_adb_command", lambda cmd, device_id=None: calls.append(cmd))

    sa.input_text("8")

    keyevent_67_count = sum(1 for c in calls if c == ["shell", "input", "keyevent", "67"])
    assert keyevent_67_count == 6
    assert ["shell", "input", "keyevent", "123"] in calls
