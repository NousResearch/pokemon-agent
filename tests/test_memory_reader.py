"""Tests for pokemon_agent.memory.red (RedBlueMemoryReader).

Uses a mock Emulator so tests run without a ROM or PyBoy installed.
"""

import pytest
from unittest.mock import MagicMock

from pokemon_agent.memory.red import (
    RedBlueMemoryReader,
    GEN1_ENCODING,
    SPECIES_NAMES,
    MOVE_NAMES,
    ITEM_NAMES,
    MAP_NAMES,
    TYPE_NAMES,
    BADGE_NAMES,
    FACING_NAMES,
    ADDR_PLAYER_NAME,
    ADDR_RIVAL_NAME,
    ADDR_MONEY,
    ADDR_BADGES,
    ADDR_MAP_ID,
    ADDR_MAP_Y,
    ADDR_MAP_X,
    ADDR_FACING,
    ADDR_PARTY_COUNT,
    ADDR_PARTY_DATA,
    ADDR_PARTY_NICKS,
    ADDR_BAG_COUNT,
    ADDR_BAG_ITEMS,
    ADDR_BATTLE_TYPE,
    ADDR_TEXT_BOX_ID,
    ADDR_JOY_IGNORE,
    ADDR_DEX_OWNED,
    ADDR_DEX_SEEN,
    ADDR_OAK_PARCEL,
    ADDR_POKEDEX_FLAG,
    ADDR_PLAYTIME_H,
    ADDR_PLAYTIME_M,
    ADDR_PLAYTIME_S,
    PARTY_MON_SIZE,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_mock_emu():
    """Create a mock Emulator with read_u8, read_u16, read_range."""
    emu = MagicMock()
    emu._ram = bytearray(0x10000)  # 64KB RAM
    emu.read_u8 = lambda addr: emu._ram[addr]
    emu.read_u16 = lambda addr: emu._ram[addr] | (emu._ram[addr + 1] << 8)
    emu.read_range = lambda addr, n: bytes(emu._ram[addr:addr + n])
    return emu


def _encode_gen1_text(text: str) -> bytes:
    """Encode a string to Gen-1 format (terminated by 0x50)."""
    reverse = {v: k for k, v in GEN1_ENCODING.items() if v and k != 0x50}
    result = []
    for ch in text:
        if ch in reverse:
            result.append(reverse[ch])
        else:
            result.append(0x50)
            break
    result.append(0x50)
    return bytes(result)


def _write_gen1_text(ram: bytearray, addr: int, text: str):
    """Write a Gen-1 encoded string into RAM."""
    encoded = _encode_gen1_text(text)
    ram[addr:addr + len(encoded)] = encoded


def _write_bcd(ram: bytearray, addr: int, value: int, num_bytes: int):
    """Write a BCD-encoded integer into RAM."""
    digits = str(value).zfill(num_bytes * 2)
    for i in range(num_bytes):
        hi = int(digits[i * 2])
        lo = int(digits[i * 2 + 1])
        ram[addr + i] = (hi << 4) | lo


def _build_party_mon(
    species_id=25, level=20, hp=50, max_hp=55,
    status=0, type1=23, type2=23,
    moves=(84, 85, 86, 98),
    attack=40, defense=30, speed=60, special=45,
):
    """Build a 44-byte party Pokemon structure."""
    data = bytearray(PARTY_MON_SIZE)
    data[0] = species_id
    data[1] = (hp >> 8) & 0xFF
    data[2] = hp & 0xFF
    data[3] = level  # box level
    data[4] = status
    data[5] = type1
    data[6] = type2
    for i, mid in enumerate(moves[:4]):
        data[8 + i] = mid
        data[29 + i] = 25  # PP
    data[33] = level  # party level
    data[34] = (max_hp >> 8) & 0xFF
    data[35] = max_hp & 0xFF
    data[36] = (attack >> 8) & 0xFF
    data[37] = attack & 0xFF
    data[38] = (defense >> 8) & 0xFF
    data[39] = defense & 0xFF
    data[40] = (speed >> 8) & 0xFF
    data[41] = speed & 0xFF
    data[42] = (special >> 8) & 0xFF
    data[43] = special & 0xFF
    return bytes(data)


# ---------------------------------------------------------------------------
# Encoding table
# ---------------------------------------------------------------------------

class TestGen1Encoding:
    def test_uppercase_letters(self):
        for i, c in enumerate("ABCDEFGHIJKLMNOPQRSTUVWXYZ"):
            assert GEN1_ENCODING[0x80 + i] == c

    def test_lowercase_letters(self):
        for i, c in enumerate("abcdefghijklmnopqrstuvwxyz"):
            assert GEN1_ENCODING[0xA0 + i] == c

    def test_digits(self):
        for i, c in enumerate("0123456789"):
            assert GEN1_ENCODING[0xF6 + i] == c

    def test_space(self):
        assert GEN1_ENCODING[0x7F] == " "

    def test_terminator(self):
        assert GEN1_ENCODING[0x50] == ""


# ---------------------------------------------------------------------------
# Name tables completeness
# ---------------------------------------------------------------------------

class TestNameTables:
    def test_all_151_pokemon(self):
        for i in range(1, 152):
            assert i in SPECIES_NAMES, f"Species {i} missing"

    def test_pikachu_is_25(self):
        assert SPECIES_NAMES[25] == "Pikachu"

    def test_mew_is_151(self):
        assert SPECIES_NAMES[151] == "Mew"

    def test_common_moves(self):
        assert MOVE_NAMES[33] == "Tackle"
        assert MOVE_NAMES[85] == "Thunderbolt"
        assert MOVE_NAMES[57] == "Surf"

    def test_common_items(self):
        assert ITEM_NAMES[4] == "Poke Ball"
        assert ITEM_NAMES[40] == "Rare Candy"
        assert ITEM_NAMES[1] == "Master Ball"

    def test_pallet_town(self):
        assert MAP_NAMES[0] == "Pallet Town"

    def test_eight_badges(self):
        assert len(BADGE_NAMES) == 8
        assert BADGE_NAMES[0] == "Boulder"
        assert BADGE_NAMES[7] == "Earth"


# ---------------------------------------------------------------------------
# RedBlueMemoryReader with mock emulator
# ---------------------------------------------------------------------------

class TestRedBlueMemoryReader:
    @pytest.fixture
    def setup(self):
        emu = _make_mock_emu()
        reader = RedBlueMemoryReader(emu)
        return emu, reader

    # -- read_player --

    def test_read_player_name(self, setup):
        emu, reader = setup
        _write_gen1_text(emu._ram, ADDR_PLAYER_NAME, "RED")
        _write_gen1_text(emu._ram, ADDR_RIVAL_NAME, "BLUE")
        _write_bcd(emu._ram, ADDR_MONEY, 3000, 3)
        emu._ram[ADDR_BADGES] = 0b00000011  # Boulder + Cascade
        emu._ram[ADDR_MAP_Y] = 5
        emu._ram[ADDR_MAP_X] = 3
        emu._ram[ADDR_FACING] = 0x00  # down
        emu._ram[ADDR_PLAYTIME_H] = 10
        emu._ram[ADDR_PLAYTIME_H + 1] = 0
        emu._ram[ADDR_PLAYTIME_M] = 30
        emu._ram[ADDR_PLAYTIME_S] = 15

        player = reader.read_player()

        assert player["name"] == "RED"
        assert player["rival_name"] == "BLUE"
        assert player["money"] == 3000
        assert player["badges"] == ["Boulder", "Cascade"]
        assert player["badge_count"] == 2
        assert player["position"] == {"y": 5, "x": 3}
        assert player["facing"] == "down"

    def test_read_player_no_badges(self, setup):
        emu, reader = setup
        _write_gen1_text(emu._ram, ADDR_PLAYER_NAME, "ASH")
        _write_gen1_text(emu._ram, ADDR_RIVAL_NAME, "GARY")
        emu._ram[ADDR_BADGES] = 0

        player = reader.read_player()
        assert player["badges"] == []
        assert player["badge_count"] == 0

    def test_read_player_all_badges(self, setup):
        emu, reader = setup
        _write_gen1_text(emu._ram, ADDR_PLAYER_NAME, "RED")
        _write_gen1_text(emu._ram, ADDR_RIVAL_NAME, "BLUE")
        emu._ram[ADDR_BADGES] = 0xFF

        player = reader.read_player()
        assert player["badge_count"] == 8
        assert player["badges"] == list(BADGE_NAMES)

    # -- read_party --

    def test_read_party_one_pokemon(self, setup):
        emu, reader = setup
        emu._ram[ADDR_PARTY_COUNT] = 1

        mon_data = _build_party_mon(species_id=25, level=20, hp=50, max_hp=55)
        for i, b in enumerate(mon_data):
            emu._ram[ADDR_PARTY_DATA + i] = b

        _write_gen1_text(emu._ram, ADDR_PARTY_NICKS, "PIKACHU")

        party = reader.read_party()
        assert len(party) == 1
        assert party[0]["species"] == "Pikachu"
        assert party[0]["level"] == 20
        assert party[0]["hp"] == 50
        assert party[0]["max_hp"] == 55
        assert party[0]["nickname"] == "PIKACHU"
        assert party[0]["status"] == "OK"

    def test_read_party_capped_at_six(self, setup):
        emu, reader = setup
        emu._ram[ADDR_PARTY_COUNT] = 255  # corrupted value
        party = reader.read_party()
        assert len(party) <= 6

    def test_read_party_empty(self, setup):
        emu, reader = setup
        emu._ram[ADDR_PARTY_COUNT] = 0
        party = reader.read_party()
        assert party == []

    # -- read_bag --

    def test_read_bag_with_items(self, setup):
        emu, reader = setup
        emu._ram[ADDR_BAG_COUNT] = 2
        emu._ram[ADDR_BAG_ITEMS] = 4       # Poke Ball
        emu._ram[ADDR_BAG_ITEMS + 1] = 10  # qty
        emu._ram[ADDR_BAG_ITEMS + 2] = 20  # Potion
        emu._ram[ADDR_BAG_ITEMS + 3] = 5   # qty

        bag = reader.read_bag()
        assert len(bag) == 2
        assert bag[0]["item"] == "Poke Ball"
        assert bag[0]["quantity"] == 10
        assert bag[1]["item"] == "Potion"
        assert bag[1]["quantity"] == 5

    def test_read_bag_empty(self, setup):
        emu, reader = setup
        emu._ram[ADDR_BAG_COUNT] = 0
        bag = reader.read_bag()
        assert bag == []

    def test_read_bag_terminator(self, setup):
        emu, reader = setup
        emu._ram[ADDR_BAG_COUNT] = 5
        emu._ram[ADDR_BAG_ITEMS] = 4
        emu._ram[ADDR_BAG_ITEMS + 1] = 3
        emu._ram[ADDR_BAG_ITEMS + 2] = 0xFF  # terminator
        bag = reader.read_bag()
        assert len(bag) == 1

    # -- read_battle --

    def test_read_battle_not_in_battle(self, setup):
        emu, reader = setup
        emu._ram[ADDR_BATTLE_TYPE] = 0

        battle = reader.read_battle()
        assert battle["in_battle"] is False
        assert battle["type"] == "none"
        assert "enemy" not in battle

    def test_read_battle_wild(self, setup):
        emu, reader = setup
        emu._ram[ADDR_BATTLE_TYPE] = 1  # wild
        from pokemon_agent.memory.red import ADDR_ENEMY_SPECIES, ADDR_ENEMY_DATA
        emu._ram[ADDR_ENEMY_SPECIES] = 25  # Pikachu

        enemy_data = _build_party_mon(species_id=25, level=10, hp=30, max_hp=30)
        for i, b in enumerate(enemy_data):
            emu._ram[ADDR_ENEMY_DATA + i] = b

        battle = reader.read_battle()
        assert battle["in_battle"] is True
        assert battle["type"] == "wild"
        assert battle["enemy"]["species"] == "Pikachu"
        assert battle["enemy"]["level"] == 10

    # -- read_dialog --

    def test_read_dialog_inactive(self, setup):
        emu, reader = setup
        emu._ram[ADDR_TEXT_BOX_ID] = 0
        emu._ram[ADDR_JOY_IGNORE] = 0

        dialog = reader.read_dialog()
        assert dialog["active"] is False

    def test_read_dialog_active_textbox(self, setup):
        emu, reader = setup
        emu._ram[ADDR_TEXT_BOX_ID] = 1
        emu._ram[ADDR_JOY_IGNORE] = 0

        dialog = reader.read_dialog()
        assert dialog["active"] is True

    def test_read_dialog_active_joyignore(self, setup):
        emu, reader = setup
        emu._ram[ADDR_TEXT_BOX_ID] = 0
        emu._ram[ADDR_JOY_IGNORE] = 0x20  # bit 5

        dialog = reader.read_dialog()
        assert dialog["active"] is True

    # -- read_map_info --

    def test_read_map_pallet_town(self, setup):
        emu, reader = setup
        emu._ram[ADDR_MAP_ID] = 0

        map_info = reader.read_map_info()
        assert map_info["map_id"] == 0
        assert map_info["map_name"] == "Pallet Town"

    def test_read_map_unknown(self, setup):
        emu, reader = setup
        emu._ram[ADDR_MAP_ID] = 254  # not in table

        map_info = reader.read_map_info()
        assert "Unknown" in map_info["map_name"] or "254" in map_info["map_name"]

    # -- read_flags --

    def test_read_flags_has_pokedex(self, setup):
        emu, reader = setup
        emu._ram[ADDR_POKEDEX_FLAG] = 0x20  # bit 5
        emu._ram[ADDR_OAK_PARCEL] = 0x02    # bit 1

        flags = reader.read_flags()
        assert flags["has_pokedex"] is True
        assert flags["has_oaks_parcel"] is True

    def test_read_flags_no_pokedex(self, setup):
        emu, reader = setup
        emu._ram[ADDR_POKEDEX_FLAG] = 0
        emu._ram[ADDR_OAK_PARCEL] = 0

        flags = reader.read_flags()
        assert flags["has_pokedex"] is False
        assert flags["has_oaks_parcel"] is False

    # -- status decoding --

    def test_decode_status_ok(self, setup):
        _, reader = setup
        assert reader._decode_status(0) == "OK"

    def test_decode_status_poisoned(self, setup):
        _, reader = setup
        assert "PSN" in reader._decode_status(0x08)

    def test_decode_status_paralyzed(self, setup):
        _, reader = setup
        assert "PAR" in reader._decode_status(0x40)

    def test_decode_status_sleep(self, setup):
        _, reader = setup
        result = reader._decode_status(0x03)
        assert "SLP" in result

    def test_decode_status_multiple(self, setup):
        _, reader = setup
        # poison + burn
        result = reader._decode_status(0x08 | 0x10)
        assert "PSN" in result
        assert "BRN" in result

    # -- game_name --

    def test_game_name(self, setup):
        _, reader = setup
        assert reader.game_name == "Pokemon Red/Blue (USA)"
