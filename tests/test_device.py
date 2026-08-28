"""Tests for the lazy adb device resolution in cmd_program/screen_action.py:
resolve_device(), invalidate_device(), and the WOS_ADB_SERIAL override.

No real adb binary or emulator is touched: get_adb_devices() (the only
function that shells out to `adb devices`) is monkeypatched in every test.
"""
import pytest

import cmd_program.screen_action as sa


@pytest.fixture(autouse=True)
def _reset_device_cache(monkeypatch):
    """Reset the module-level device cache and WOS_ADB_SERIAL around each test."""
    sa._device_id = None
    monkeypatch.delenv("WOS_ADB_SERIAL", raising=False)
    yield
    sa._device_id = None


def test_no_devices_returns_none(monkeypatch):
    monkeypatch.setattr(sa, "get_adb_devices", lambda: [])
    assert sa.resolve_device() is None


def test_one_device_is_returned_and_cached(monkeypatch):
    monkeypatch.setattr(sa, "get_adb_devices", lambda: ["emulator-5554"])
    assert sa.resolve_device() == "emulator-5554"

    def _raises():
        raise AssertionError("get_adb_devices should not be called again -- cache should be used")

    monkeypatch.setattr(sa, "get_adb_devices", _raises)
    # Cached value is returned without re-probing.
    assert sa.resolve_device() == "emulator-5554"


def test_one_device_cache_survives_empty_reprobe(monkeypatch):
    monkeypatch.setattr(sa, "get_adb_devices", lambda: ["emulator-5554"])
    assert sa.resolve_device() == "emulator-5554"

    monkeypatch.setattr(sa, "get_adb_devices", lambda: [])
    assert sa.resolve_device() == "emulator-5554"


def test_wos_adb_serial_set_and_present_wins_over_first_device(monkeypatch):
    monkeypatch.setenv("WOS_ADB_SERIAL", "serial-b")
    monkeypatch.setattr(sa, "get_adb_devices", lambda: ["serial-a", "serial-b"])
    assert sa.resolve_device() == "serial-b"


def test_wos_adb_serial_set_but_absent_raises_loudly(monkeypatch):
    # A stale/wrong env var must NOT silently substitute a different device --
    # that lets taps land on the wrong device with no error at all. Fail loudly
    # instead, naming both the requested serial and what was actually found.
    monkeypatch.setenv("WOS_ADB_SERIAL", "stale-serial")
    monkeypatch.setattr(sa, "get_adb_devices", lambda: ["serial-a", "serial-b"])
    with pytest.raises(RuntimeError, match="stale-serial"):
        sa.resolve_device()


def test_wos_adb_serial_unset_falls_back_to_first_device(monkeypatch):
    # An unset WOS_ADB_SERIAL still falls back to devices[0] as before.
    monkeypatch.delenv("WOS_ADB_SERIAL", raising=False)
    monkeypatch.setattr(sa, "get_adb_devices", lambda: ["serial-a", "serial-b"])
    assert sa.resolve_device() == "serial-a"


def test_invalidate_device_clears_cache_and_forces_reprobe(monkeypatch):
    monkeypatch.setattr(sa, "get_adb_devices", lambda: ["serial-a"])
    assert sa.resolve_device() == "serial-a"

    sa.invalidate_device()
    assert sa._device_id is None

    monkeypatch.setattr(sa, "get_adb_devices", lambda: ["serial-b"])
    assert sa.resolve_device() == "serial-b"


def test_force_true_reprobes_even_when_cached(monkeypatch):
    monkeypatch.setattr(sa, "get_adb_devices", lambda: ["serial-a"])
    assert sa.resolve_device() == "serial-a"

    monkeypatch.setattr(sa, "get_adb_devices", lambda: ["serial-b"])
    assert sa.resolve_device(force=True) == "serial-b"
