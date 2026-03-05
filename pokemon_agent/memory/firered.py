"""Pokemon FireRed (USA) memory reader — Phase 2 stub.

FireRed runs on the GBA and uses a very different memory layout from the
original Red/Blue.  Notably, party and box Pokemon data is **encrypted**:

  * Each Pokemon has a 100-byte data structure (48 bytes encrypted).
  * The 48-byte encrypted block is split into four 12-byte substructures
    (Growth, Attacks, EVs/Condition, Misc).
  * The substructure order is determined by ``personality_value % 24``.
  * Encryption key = ``personality_value XOR original_trainer_id``.
  * Each 4-byte word of the 48-byte block is XOR'd with the key.

Key EWRAM addresses (FireRed USA 1.0, SQUIRRELS offsets):

  * Save Block 1 pointer : 0x0300500C
  * Save Block 2 pointer : 0x03005010
  * Party data           : SaveBlock1 + 0x0234
  * Bag                  : SaveBlock1 + 0x0310
  * Money                : SaveBlock1 + 0x0290
  * Player name          : SaveBlock2 + 0x0000 (8 bytes, Gen 3 encoding)
  * Badges low           : SaveBlock2 + 0x00F8
  * Map group/number     : SaveBlock1 + 0x0004

This module defines the address constants and provides a skeleton reader
that will be fully implemented in Phase 2.
"""

from __future__ import annotations

from typing import Any, Dict, List

from pokemon_agent.emulator import Emulator
from pokemon_agent.memory.reader import GameMemoryReader


# ===================================================================
# Address constants (FireRed USA 1.0)
# ===================================================================

ADDR_SAVEBLOCK1_PTR = 0x0300500C
ADDR_SAVEBLOCK2_PTR = 0x03005010

# Offsets from SaveBlock1
OFF_PARTY_COUNT     = 0x0234
OFF_PARTY_DATA      = 0x0238     # 100 bytes × 6
OFF_MONEY           = 0x0290     # 4 bytes, XOR-encrypted with key at +0x0290
OFF_BAG_ITEMS       = 0x0310
OFF_MAP_GROUP       = 0x0004
OFF_MAP_NUMBER      = 0x0005
OFF_POS_X           = 0x0000     # local coords within map
OFF_POS_Y           = 0x0002

# Offsets from SaveBlock2
OFF_PLAYER_NAME     = 0x0000     # 8 bytes
OFF_PLAYER_GENDER   = 0x0008
OFF_TRAINER_ID      = 0x000A     # 4 bytes (TID + SID)
OFF_PLAY_TIME       = 0x000E     # hours(2) + minutes(1) + seconds(1)
OFF_BADGES          = 0x00F8     # 2 bytes bitmask

# Pokemon substructure order lookup (24 permutations)
SUBSTRUCTURE_ORDER = [
    "GAEM", "GAME", "GEAM", "GEMA", "GMAE", "GMEA",
    "AGEM", "AGME", "AEGM", "AEMG", "AMGE", "AMEG",
    "EGAM", "EGMA", "EAGM", "EAMG", "EMGA", "EMAG",
    "MGAE", "MGEA", "MAGE", "MAEG", "MEGA", "MEAG",
]

PARTY_MON_SIZE_GEN3 = 100
ENCRYPTED_BLOCK_SIZE = 48


class FireRedMemoryReader(GameMemoryReader):
    """Memory reader skeleton for *Pokemon FireRed* (USA 1.0).

    .. warning::
        This reader is a **Phase 2 stub**.  All data-reading methods
        raise :class:`NotImplementedError`.  The address constants and
        decryption scaffolding are provided for future implementation.

    Parameters
    ----------
    emulator : Emulator
        A loaded :class:`~pokemon_agent.emulator.PyGBAEmulator` running
        a FireRed ROM.
    """

    @property
    def game_name(self) -> str:
        return "Pokemon FireRed (USA)"

    # -- internal helpers (scaffolding) --

    def _get_saveblock1(self) -> int:
        """Dereference the SaveBlock1 pointer."""
        return self.emu.read_u32(ADDR_SAVEBLOCK1_PTR)

    def _get_saveblock2(self) -> int:
        """Dereference the SaveBlock2 pointer."""
        return self.emu.read_u32(ADDR_SAVEBLOCK2_PTR)

    def _decrypt_pokemon(self, addr: int) -> bytes:
        """Decrypt the 48-byte encrypted block of a party/box Pokemon.

        Not yet implemented — placeholder for Phase 2.
        """
        raise NotImplementedError(
            "FireRed Pokemon decryption is planned for Phase 2. "
            "The encrypted block uses PID XOR OTID as the key and "
            "requires substructure re-ordering based on PID % 24."
        )

    # -- public interface (all raise NotImplementedError) --

    def read_player(self) -> Dict[str, Any]:
        """Read player data (Phase 2)."""
        raise NotImplementedError(
            "FireRedMemoryReader.read_player() is not yet implemented. "
            "Planned for Phase 2. Address constants are defined; "
            "Gen 3 text decoding and save block dereferencing are required."
        )

    def read_party(self) -> List[Dict[str, Any]]:
        """Read party Pokemon (Phase 2)."""
        raise NotImplementedError(
            "FireRedMemoryReader.read_party() is not yet implemented. "
            "Planned for Phase 2. Requires PID/OTID-based decryption "
            "and substructure order lookup."
        )

    def read_bag(self) -> List[Dict[str, Any]]:
        """Read bag contents (Phase 2)."""
        raise NotImplementedError(
            "FireRedMemoryReader.read_bag() is not yet implemented. "
            "Planned for Phase 2."
        )

    def read_battle(self) -> Dict[str, Any]:
        """Read battle state (Phase 2)."""
        raise NotImplementedError(
            "FireRedMemoryReader.read_battle() is not yet implemented. "
            "Planned for Phase 2."
        )

    def read_dialog(self) -> Dict[str, Any]:
        """Read dialog state (Phase 2)."""
        raise NotImplementedError(
            "FireRedMemoryReader.read_dialog() is not yet implemented. "
            "Planned for Phase 2."
        )

    def read_map_info(self) -> Dict[str, Any]:
        """Read map info (Phase 2)."""
        raise NotImplementedError(
            "FireRedMemoryReader.read_map_info() is not yet implemented. "
            "Planned for Phase 2."
        )

    def read_flags(self) -> Dict[str, Any]:
        """Read story flags (Phase 2)."""
        raise NotImplementedError(
            "FireRedMemoryReader.read_flags() is not yet implemented. "
            "Planned for Phase 2."
        )
