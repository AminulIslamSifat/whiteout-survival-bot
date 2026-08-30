import json
import os

import pytest

from core import player_profile as pp


@pytest.fixture
def players_dir(tmp_path, monkeypatch):
    d = tmp_path / "players"
    d.mkdir()
    example = {
        "id": "00000000",
        "name": "example",
        "state": 3429,
        "gather": {"current_march": 0, "possible_march": 4, "priority": None},
    }
    (d / "example.json").write_text(json.dumps(example))
    monkeypatch.setattr(pp, "PLAYERS_DIR", str(d))
    monkeypatch.setattr(pp, "EXAMPLE_PATH", str(d / "example.json"))
    return d


def test_load_missing_profile_seeds_from_example(players_dir):
    profile = pp.load_profile("555000111")
    assert profile["id"] == "555000111"
    assert profile["name"] is None
    assert profile["gather"]["possible_march"] == 4


def test_save_and_reload_roundtrip(players_dir):
    profile = pp.load_profile("555000111")
    profile["name"] = "lord555000111"
    pp.save_profile(profile)
    again = pp.load_profile("555000111")
    assert again["name"] == "lord555000111"
    assert os.path.exists(players_dir / "555000111.json")


def test_existing_profile_is_reused_not_reseeded(players_dir):
    (players_dir / "555000111.json").write_text(
        json.dumps({"id": "555000111", "name": "kept", "gather": {"node_level": 3}})
    )
    profile = pp.load_profile("555000111")
    assert profile["name"] == "kept"
    assert pp.get_gather_node_level(profile) == 3


def test_node_level_defaults_to_8(players_dir):
    profile = pp.load_profile("555000111")
    assert pp.get_gather_node_level(profile) == 8


def test_node_level_set_persists_and_clamps(players_dir):
    profile = pp.load_profile("555000111")
    pp.set_gather_node_level(profile, 0)
    assert pp.get_gather_node_level(pp.load_profile("555000111")) == 1
    pp.set_gather_node_level(profile, 99)
    assert pp.get_gather_node_level(pp.load_profile("555000111")) == 8
    pp.set_gather_node_level(profile, 5)
    assert pp.get_gather_node_level(pp.load_profile("555000111")) == 5


def test_node_level_garbage_falls_back_to_default(players_dir):
    profile = {"id": "x", "gather": {"node_level": "not-a-number"}}
    assert pp.get_gather_node_level(profile) == 8


def test_corrupt_profile_reseeds_instead_of_crashing(players_dir):
    (players_dir / "555000111.json").write_text("")  # upstream shipped a zero-byte file
    profile = pp.load_profile("555000111")
    assert profile["id"] == "555000111"
    assert profile["gather"]["possible_march"] == 4

    (players_dir / "555000111.json").write_text("{not json")
    profile = pp.load_profile("555000111")
    assert profile["id"] == "555000111"
