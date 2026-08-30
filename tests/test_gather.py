"""Gather node-level state machine tests (offline, scripted stubs).

Two prior review cycles (95a9220, 31f4baa) fixed bugs in exactly this logic —
evidence-gated decrement, the 3-strike indeterminate bound, level_confirmed
persistence, the +1 upward probe — and none of it was covered. A regression
here silently corrupts persisted per-player profiles over long live runs.

Every I/O touchpoint of gather() is a module attribute on usecases.gather and
monkeypatches cleanly; no emulator, OCR server, or profile files are touched.
"""
import pytest

import usecases.gather as g


class Script:
    """Scripted stand-ins for gather()'s I/O with call recording."""

    def __init__(self, *, coords=None, search_icon=None, gather_button=None,
                 item_level=None, march_queue="1/5"):
        self.persisted = []
        self.search_levels_set = []
        self.coords = list(coords) if coords else []        # _read_map_coords returns
        self.search_icon = list(search_icon) if search_icon else [True]
        self.gather_button = list(gather_button) if gather_button else [None]
        self.item_level = item_level                         # str, Exception, or None
        self.march_queue = march_queue
        self.wait_till_return_called = False

    def _pop(self, seq, default):
        return seq.pop(0) if seq else default

    def install(self, monkeypatch):
        monkeypatch.setattr(g, "enter_world_map", lambda **k: True)
        monkeypatch.setattr(g, "wait_till_return",
                            lambda **k: setattr(self, "wait_till_return_called", True))
        monkeypatch.setattr(g, "recalibrate", lambda: None)
        monkeypatch.setattr(g.time, "sleep", lambda s: None)
        monkeypatch.setattr(g, "tap_screen", lambda *a, **k: None)
        monkeypatch.setattr(g, "swipe_screen", lambda *a, **k: None)
        monkeypatch.setattr(g, "input_text",
                            lambda text: self.search_levels_set.append(text))
        monkeypatch.setattr(g, "set_gather_node_level",
                            lambda profile, lvl: self.persisted.append(lvl))
        monkeypatch.setattr(g, "_read_map_coords",
                            lambda: self._pop(self.coords, None))
        monkeypatch.setattr(g, "tap_on_template", self._tap_on_template)
        monkeypatch.setattr(g, "tap_on_text", self._tap_on_text)
        monkeypatch.setattr(g, "req_text", self._req_text)

    def _tap_on_template(self, name, **k):
        if name == "World.Search":
            return self._pop(self.search_icon, False)
        return True  # RemoveHero etc.

    def _tap_on_text(self, text, **k):
        if text == "World.City":
            return True
        if text == "World.Search.Gather":
            return self._pop(self.gather_button, None)
        return True  # node names, Search, Equalize, Deploy

    def _req_text(self, names=None, **k):
        if names == "World.MarchQueue":
            return [[self.march_queue, [0, 0, 1, 1]]]
        if names == "World.Search.ItemLevel":
            if isinstance(self.item_level, Exception):
                raise self.item_level
            return [[self.item_level, [0, 0, 1, 1]]]
        if names == "World.City":
            return [["city", [0, 0, 1, 1]]]
        return [["", [0, 0, 1, 1]]]


PROFILE = {"id": "test-profile"}


def test_camera_stayed_with_valid_coords_decrements_and_persists(monkeypatch):
    # Both coordinate reads valid and equal -> positive evidence the search
    # found nothing -> level steps down AND persists.
    s = Script(coords=["X:100 Y:200", "X:100 Y:200"],
               search_icon=[True, False],       # 2nd loop iteration exits
               gather_button=[None],
               item_level="5")
    s.install(monkeypatch)
    g.gather(node_level=5, profile=PROFILE)
    assert s.persisted == [4]


def test_flaky_coord_read_never_decrements_or_persists(monkeypatch):
    # A None coordinate read is an OCR flake, not proof the camera stayed:
    # no decrement, nothing persisted.
    s = Script(coords=[None, None],
               search_icon=[True, False],
               gather_button=[None],
               item_level="5")
    s.install(monkeypatch)
    g.gather(node_level=5, profile=PROFILE)
    assert s.persisted == []


def test_three_indeterminate_reads_lower_level_in_run_only(monkeypatch):
    # 3 consecutive no-evidence misses -> level drops for THIS RUN (visible in
    # the next iteration's level-set), but is never persisted.
    s = Script(coords=[None] * 8,
               search_icon=[True, True, True, True, False],  # 4 loops then exit
               gather_button=[None, None, None, None],
               item_level="9")                  # never matches -> set+recheck
    s.install(monkeypatch)
    g.gather(node_level=5, profile=PROFILE)
    assert s.persisted == []
    # After the 3rd indeterminate miss, the 4th iteration searches at level 4.
    assert "4" in s.search_levels_set


def test_unconfirmed_level_never_persists_on_deploy(monkeypatch):
    # ItemLevel read raises -> level_confirmed stays False -> a successful
    # deploy must NOT record the level.
    s = Script(coords=["X:1 Y:1"],
               search_icon=[True],
               gather_button=[True],
               item_level=RuntimeError("ocr flake"),
               march_queue="4/5")               # after deploy, re-read ends loop
    s.install(monkeypatch)
    g.gather(node_level=5, profile=PROFILE)
    assert s.persisted == []


def test_confirmed_level_persists_on_deploy(monkeypatch):
    s = Script(coords=["X:1 Y:1"],
               search_icon=[True],
               gather_button=[True],
               item_level="5",
               march_queue="4/5")
    s.install(monkeypatch)
    g.gather(node_level=5, profile=PROFILE)
    assert s.persisted == [5]


def test_upward_probe_starts_one_above_stored_level(monkeypatch):
    s = Script(coords=["X:1 Y:1"],
               search_icon=[True],
               gather_button=[True],
               item_level="6",                  # probe level = stored 5 + 1
               march_queue="4/5")
    s.install(monkeypatch)
    monkeypatch.setattr(g, "get_gather_node_level", lambda p: 5)
    g.gather(profile=PROFILE)
    assert s.persisted == [6]


def test_upward_probe_caps_at_eight(monkeypatch):
    s = Script(coords=["X:1 Y:1"],
               search_icon=[True],
               gather_button=[True],
               item_level="8",
               march_queue="4/5")
    s.install(monkeypatch)
    monkeypatch.setattr(g, "get_gather_node_level", lambda p: 8)
    g.gather(profile=PROFILE)
    assert s.persisted == [8]


def test_world_map_unreachable_exits_before_waiting(monkeypatch):
    s = Script()
    s.install(monkeypatch)
    monkeypatch.setattr(g, "enter_world_map", lambda **k: False)
    g.gather(node_level=5, profile=PROFILE)
    assert s.wait_till_return_called is False
    assert s.persisted == []


def test_camera_stayed_but_level_unconfirmed_does_not_persist(monkeypatch):
    # Level read raised -> the search may have run at a stale field value, so
    # the no-jump outcome cannot be attributed to node_level: decrement is
    # in-run only, never persisted.
    s = Script(coords=["X:100 Y:200", "X:100 Y:200"],
               search_icon=[True, False],
               gather_button=[None],
               item_level=RuntimeError("ocr flake"))
    s.install(monkeypatch)
    g.gather(node_level=5, profile=PROFILE)
    assert s.persisted == []
