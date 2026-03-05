"""Abstract base for game-specific memory readers.

Each supported game (Red/Blue, FireRed, …) subclasses
:class:`GameMemoryReader` and implements the concrete address lookups
and data decoding required for that title.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional

from pokemon_agent.emulator import Emulator


class GameMemoryReader(ABC):
    """Base class for reading structured game data from emulator RAM.

    Parameters
    ----------
    emulator : Emulator
        A loaded :class:`~pokemon_agent.emulator.Emulator` instance whose
        memory will be read.
    """

    def __init__(self, emulator: Emulator) -> None:
        self.emu = emulator

    # -- helpers ------------------------------------------------------------

    def read_string(
        self,
        addr: int,
        max_len: int,
        encoding_table: Dict[int, str],
        terminator: int = 0x50,
    ) -> str:
        """Decode a string from emulator RAM using *encoding_table*.

        Parameters
        ----------
        addr : int
            Start address of the string.
        max_len : int
            Maximum number of bytes to read.
        encoding_table : dict[int, str]
            Mapping of byte values to characters.
        terminator : int
            Byte value that marks end-of-string (default 0x50 for Gen 1).
        """
        raw = self.emu.read_range(addr, max_len)
        chars: List[str] = []
        for b in raw:
            if b == terminator:
                break
            chars.append(encoding_table.get(b, "?"))
        return "".join(chars)

    def read_bcd(self, addr: int, num_bytes: int) -> int:
        """Decode a BCD-encoded integer (big-endian) from *addr*.

        Each byte stores two decimal digits (upper nibble, lower nibble).
        """
        raw = self.emu.read_range(addr, num_bytes)
        value = 0
        for b in raw:
            hi = (b >> 4) & 0x0F
            lo = b & 0x0F
            value = value * 100 + hi * 10 + lo
        return value

    def read_bits(self, addr: int, num_bytes: int) -> List[bool]:
        """Read *num_bytes* and return a flat list of bit flags (LSB first)."""
        raw = self.emu.read_range(addr, num_bytes)
        bits: List[bool] = []
        for b in raw:
            for i in range(8):
                bits.append(bool(b & (1 << i)))
        return bits

    # -- abstract interface -------------------------------------------------

    @property
    @abstractmethod
    def game_name(self) -> str:
        """Human-readable game title, e.g. 'Pokemon Red (USA)'."""

    @abstractmethod
    def read_player(self) -> Dict[str, Any]:
        """Return player info (name, money, badges, position, …)."""

    @abstractmethod
    def read_party(self) -> List[Dict[str, Any]]:
        """Return the player's party as a list of Pokemon dicts."""

    @abstractmethod
    def read_bag(self) -> List[Dict[str, Any]]:
        """Return bag contents as a list of {item, quantity}."""

    @abstractmethod
    def read_battle(self) -> Dict[str, Any]:
        """Return battle state (type, enemy info, …)."""

    @abstractmethod
    def read_dialog(self) -> Dict[str, Any]:
        """Return dialogue/text-box state."""

    @abstractmethod
    def read_map_info(self) -> Dict[str, Any]:
        """Return current map id and name."""

    @abstractmethod
    def read_flags(self) -> Dict[str, Any]:
        """Return key story/event flags."""
