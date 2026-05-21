from pathlib import Path

from pokemon_agent.cli import _detect_game_type
from pokemon_agent.emulator import PyGBAEmulator
from pokemon_agent.memory.emerald import (
    ADDR_SAVEBLOCK1_PTR,
    ITEM_NAMES,
    OFF_PARTY_COUNT,
    OFF_PARTY_DATA,
    PARTY_MON_SIZE,
    SPECIES_NAMES,
    PokemonEmeraldReader,
)
from pokemon_agent.memory.firered import FireRedMemoryReader, PokemonFireRedReader


class FakeEmulator:
    def __init__(self):
        self.mem = {}

    def set_u8(self, addr, value):
        self.mem[addr] = value & 0xFF

    def set_u16(self, addr, value):
        self.set_bytes(addr, value.to_bytes(2, "little"))

    def set_u32(self, addr, value):
        self.set_bytes(addr, value.to_bytes(4, "little"))

    def set_bytes(self, addr, data):
        for i, byte in enumerate(data):
            self.set_u8(addr + i, byte)

    def read_u8(self, addr):
        return self.mem.get(addr, 0)

    def read_u16(self, addr):
        return self.read_u8(addr) | (self.read_u8(addr + 1) << 8)

    def read_u32(self, addr):
        return int.from_bytes(self.read_range(addr, 4), "little")

    def read_range(self, addr, size):
        return bytes(self.read_u8(addr + i) for i in range(size))


def _encrypt_block(block, key):
    out = bytearray()
    for i in range(0, len(block), 4):
        word = int.from_bytes(block[i : i + 4], "little") ^ key
        out.extend(word.to_bytes(4, "little"))
    return bytes(out)


def test_emerald_party_decrypts_gen3_pokemon():
    emu = FakeEmulator()
    sb1 = 0x02024000
    emu.set_u32(ADDR_SAVEBLOCK1_PTR, sb1)
    emu.set_u8(sb1 + OFF_PARTY_COUNT, 1)

    personality = 0
    ot_id = 0xAABBCCDD
    key = personality ^ ot_id

    growth = bytearray(12)
    growth[0:2] = (283).to_bytes(2, "little")  # SPECIES_MUDKIP in Emerald
    growth[2:4] = (0).to_bytes(2, "little")
    growth[4:8] = (1250).to_bytes(4, "little")

    attacks = bytearray(12)
    attacks[0:2] = (33).to_bytes(2, "little")
    attacks[2:4] = (45).to_bytes(2, "little")
    attacks[8] = 35
    attacks[9] = 40

    evs = bytes(12)
    misc = bytearray(12)
    misc[4:8] = (31).to_bytes(4, "little")
    secure = bytes(growth + attacks + evs + misc)

    raw = bytearray(PARTY_MON_SIZE)
    raw[0:4] = personality.to_bytes(4, "little")
    raw[4:8] = ot_id.to_bytes(4, "little")
    raw[8:15] = bytes([0xC7, 0xCF, 0xBE, 0xC5, 0xC3, 0xCA, 0xFF])  # MUDKIP
    raw[32:80] = _encrypt_block(secure, key)
    raw[84] = 5
    raw[86:88] = (20).to_bytes(2, "little")
    raw[88:90] = (20).to_bytes(2, "little")
    emu.set_bytes(sb1 + OFF_PARTY_DATA, raw)

    party = PokemonEmeraldReader(emu).read_party()

    assert party[0]["species"] == "Mudkip"
    assert party[0]["nickname"] == "MUDKIP"
    assert party[0]["level"] == 5
    assert [move["name"] for move in party[0]["moves"]] == ["Tackle", "Growl"]


def test_emerald_species_names_cover_gen1_to_gen3_internal_ids():
    assert SPECIES_NAMES[1] == "Bulbasaur"
    assert SPECIES_NAMES[151] == "Mew"
    assert SPECIES_NAMES[251] == "Celebi"
    assert SPECIES_NAMES[277] == "Treecko"
    assert SPECIES_NAMES[283] == "Mudkip"
    assert SPECIES_NAMES[410] == "Deoxys"
    assert SPECIES_NAMES[411] == "Chimecho"


def test_emerald_item_names_use_emerald_hm_ids():
    assert ITEM_NAMES[339] == "HM01"
    assert ITEM_NAMES[340] == "HM02"
    assert ITEM_NAMES[341] == "HM03"
    assert ITEM_NAMES[342] == "HM04"
    assert ITEM_NAMES[343] == "HM05"
    assert ITEM_NAMES[344] == "HM06"
    assert ITEM_NAMES[345] == "HM07"
    assert ITEM_NAMES[346] == "HM08"


def test_gba_rom_header_detects_emerald(tmp_path: Path):
    rom = tmp_path / "emerald.gba"
    data = bytearray(0x200)
    data[0xA0 : 0xA0 + 12] = b"POKEMON EMER"
    rom.write_bytes(data)

    assert _detect_game_type(str(rom)) == "emerald"


def test_firered_alias_is_exported():
    assert PokemonFireRedReader is FireRedMemoryReader


def test_pygba_savestate_uses_raw_core_api(tmp_path: Path):
    class Core:
        def __init__(self):
            self.loaded = None

        def save_raw_state(self):
            return b"raw-state"

        def load_raw_state(self, state):
            self.loaded = state
            return True

    emu = PyGBAEmulator()
    emu._gba = type("GBA", (), {"core": Core()})()
    path = tmp_path / "test.state"

    emu.save_state(str(path))
    emu.load_state(str(path))

    assert path.read_bytes() == b"raw-state"
    assert emu._gba.core.loaded == b"raw-state"
