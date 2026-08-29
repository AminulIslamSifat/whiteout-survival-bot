"""Per-player profile persistence.

Reuses the schema that already ships in db/players/example.json: a profile is
that dict, seeded from the example on first sight of a player id and updated
as the account evolves (levels, unlocks, working gather node level). Nothing
here invents a parallel format.
"""
import json
import os

PLAYERS_DIR = os.path.join("db", "players")
EXAMPLE_PATH = os.path.join(PLAYERS_DIR, "example.json")

DEFAULT_GATHER_NODE_LEVEL = 8


def _profile_path(player_id):
    return os.path.join(PLAYERS_DIR, f"{player_id}.json")


def load_profile(player_id):
    """Load db/players/<id>.json, seeding a new profile from example.json
    when the player has none yet or the file is corrupt (upstream even shipped
    a zero-byte one). A missing example.json still raises: that is repo
    damage, and failing loud beats running with an empty profile."""
    path = _profile_path(player_id)
    if os.path.exists(path):
        try:
            with open(path, "r") as f:
                return json.load(f)
        except (json.JSONDecodeError, ValueError):
            print(f"⚠️ Corrupt profile {path}, reseeding from example.json")

    with open(EXAMPLE_PATH, "r") as f:
        profile = json.load(f)
    profile["id"] = str(player_id)
    profile["name"] = None
    return profile


def save_profile(profile):
    """Write the profile back to db/players/<id>.json."""
    path = _profile_path(profile["id"])
    os.makedirs(PLAYERS_DIR, exist_ok=True)
    tmp = f"{path}.tmp"
    with open(tmp, "w") as f:
        json.dump(profile, f, indent=4)
    os.replace(tmp, path)


def get_gather_node_level(profile):
    """The gather node level this account is known to sustain."""
    level = profile.get("gather", {}).get("node_level", DEFAULT_GATHER_NODE_LEVEL)
    try:
        return max(1, min(8, int(level)))
    except (TypeError, ValueError):
        return DEFAULT_GATHER_NODE_LEVEL


def set_gather_node_level(profile, level):
    """Record the node level that actually worked, so the next run starts there."""
    profile.setdefault("gather", {})["node_level"] = max(1, min(8, int(level)))
    save_profile(profile)
