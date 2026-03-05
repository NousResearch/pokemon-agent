"""Tests for pokemon_agent.state.builder module."""

import pytest
from unittest.mock import MagicMock

from pokemon_agent.state.builder import build_game_state, build_state_summary


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_mock_reader(**overrides):
    """Create a mock GameMemoryReader with configurable return values."""
    reader = MagicMock()
    reader.game_name = "Pokemon Red/Blue (USA)"

    defaults = {
        "read_player": {
            "name": "RED",
            "rival_name": "BLUE",
            "money": 3000,
            "badges": ["Boulder", "Cascade"],
            "badge_count": 2,
            "position": {"y": 5, "x": 3},
            "facing": "down",
            "play_time": "10:30:15",
        },
        "read_party": [
            {
                "species_id": 25,
                "species": "Pikachu",
                "nickname": "PIKACHU",
                "level": 20,
                "hp": 50,
                "max_hp": 55,
                "status": "OK",
                "types": ["Electric", "Electric"],
                "moves": [
                    {"id": 85, "name": "Thunderbolt", "pp": 15, "pp_up": 0},
                    {"id": 98, "name": "Quick Attack", "pp": 30, "pp_up": 0},
                ],
                "stats": {"attack": 40, "defense": 30, "speed": 60, "special": 45},
                "ot_id": 12345,
                "experience": 8000,
            }
        ],
        "read_bag": [
            {"id": 4, "item": "Poke Ball", "quantity": 10},
            {"id": 20, "item": "Potion", "quantity": 5},
        ],
        "read_battle": {"in_battle": False, "type": "none"},
        "read_dialog": {"active": False, "text_box_id": 0},
        "read_map_info": {"map_id": 0, "map_name": "Pallet Town"},
        "read_flags": {
            "has_pokedex": True,
            "has_oaks_parcel": True,
            "pokedex_owned": 10,
            "pokedex_seen": 25,
            "badges": ["Boulder", "Cascade"],
            "badge_count": 2,
        },
    }

    for method, value in defaults.items():
        if method in overrides:
            getattr(reader, method).return_value = overrides[method]
        else:
            getattr(reader, method).return_value = value

    return reader


# ---------------------------------------------------------------------------
# build_game_state
# ---------------------------------------------------------------------------

class TestBuildGameState:
    def test_contains_all_sections(self):
        reader = _make_mock_reader()
        state = build_game_state(reader, frame_count=1000)

        assert "metadata" in state
        assert "player" in state
        assert "party" in state
        assert "bag" in state
        assert "battle" in state
        assert "dialog" in state
        assert "map" in state
        assert "flags" in state

    def test_metadata(self):
        reader = _make_mock_reader()
        state = build_game_state(reader, frame_count=42)

        assert state["metadata"]["game"] == "Pokemon Red/Blue (USA)"
        assert state["metadata"]["frame_count"] == 42
        assert "timestamp" in state["metadata"]

    def test_metadata_no_frame_count(self):
        reader = _make_mock_reader()
        state = build_game_state(reader)
        assert state["metadata"]["frame_count"] is None

    def test_player_data(self):
        reader = _make_mock_reader()
        state = build_game_state(reader)

        assert state["player"]["name"] == "RED"
        assert state["player"]["money"] == 3000

    def test_party_data(self):
        reader = _make_mock_reader()
        state = build_game_state(reader)

        assert len(state["party"]) == 1
        assert state["party"][0]["species"] == "Pikachu"

    def test_section_error_handling(self):
        reader = _make_mock_reader()
        reader.read_party.side_effect = RuntimeError("RAM read failed")

        state = build_game_state(reader)

        assert state["party"] is None
        assert "party_error" in state
        assert "RuntimeError" in state["party_error"]

    def test_not_implemented_error(self):
        reader = _make_mock_reader()
        reader.read_flags.side_effect = NotImplementedError("flags not supported")

        state = build_game_state(reader)

        assert state["flags"] is None
        assert "flags_error" in state
        assert "flags not supported" in state["flags_error"]

    def test_partial_failure(self):
        """One section failing shouldn't affect others."""
        reader = _make_mock_reader()
        reader.read_bag.side_effect = ValueError("corrupt data")

        state = build_game_state(reader)

        # bag failed
        assert state["bag"] is None
        assert "bag_error" in state
        # others still work
        assert state["player"]["name"] == "RED"
        assert state["party"][0]["species"] == "Pikachu"
        assert state["map"]["map_name"] == "Pallet Town"


# ---------------------------------------------------------------------------
# build_state_summary
# ---------------------------------------------------------------------------

class TestBuildStateSummary:
    def test_contains_game_name(self):
        reader = _make_mock_reader()
        state = build_game_state(reader)
        summary = build_state_summary(state)

        assert "Pokemon Red/Blue (USA)" in summary

    def test_contains_player_info(self):
        reader = _make_mock_reader()
        state = build_game_state(reader)
        summary = build_state_summary(state)

        assert "RED" in summary
        assert "BLUE" in summary
        assert "3,000" in summary or "3000" in summary

    def test_contains_party_info(self):
        reader = _make_mock_reader()
        state = build_game_state(reader)
        summary = build_state_summary(state)

        assert "Pikachu" in summary
        assert "Lv20" in summary

    def test_contains_location(self):
        reader = _make_mock_reader()
        state = build_game_state(reader)
        summary = build_state_summary(state)

        assert "Pallet Town" in summary

    def test_contains_bag_items(self):
        reader = _make_mock_reader()
        state = build_game_state(reader)
        summary = build_state_summary(state)

        assert "Poke Ball" in summary
        assert "Potion" in summary

    def test_battle_not_shown_when_not_in_battle(self):
        reader = _make_mock_reader()
        state = build_game_state(reader)
        summary = build_state_summary(state)

        assert "Not in battle" in summary

    def test_battle_shown_when_in_battle(self):
        reader = _make_mock_reader(
            read_battle={
                "in_battle": True,
                "type": "wild",
                "enemy": {
                    "species": "Rattata",
                    "level": 5,
                    "hp": 15,
                    "max_hp": 15,
                    "status": "OK",
                    "moves": ["Tackle", "Tail Whip"],
                },
            }
        )
        state = build_game_state(reader)
        summary = build_state_summary(state)

        assert "BATTLE" in summary
        assert "Rattata" in summary
        assert "wild" in summary

    def test_dialog_shown_when_active(self):
        reader = _make_mock_reader(
            read_dialog={"active": True, "text_box_id": 1}
        )
        state = build_game_state(reader)
        summary = build_state_summary(state)

        assert "DIALOG" in summary

    def test_error_section_shown(self):
        reader = _make_mock_reader()
        reader.read_party.side_effect = RuntimeError("corrupt")
        state = build_game_state(reader)
        summary = build_state_summary(state)

        assert "error" in summary.lower()

    def test_flags_section(self):
        reader = _make_mock_reader()
        state = build_game_state(reader)
        summary = build_state_summary(state)

        assert "FLAGS" in summary
        assert "Pokedex" in summary

    def test_returns_string(self):
        reader = _make_mock_reader()
        state = build_game_state(reader)
        summary = build_state_summary(state)
        assert isinstance(summary, str)
        assert len(summary) > 0

    def test_empty_state_doesnt_crash(self):
        summary = build_state_summary({"metadata": {}})
        assert isinstance(summary, str)
