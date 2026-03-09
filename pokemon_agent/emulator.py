"""Unified emulator wrapper supporting PyBoy (GB/GBC) and PyGBA (GBA).

Provides a common interface for ROM loading, button input, frame advance,
screen capture, memory access, and save states across emulator backends.
"""

from __future__ import annotations

import os
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Dict, List, Optional

try:
    from PIL import Image
except ImportError:
    Image = None  # type: ignore[assignment,misc]


# ---------------------------------------------------------------------------
# Abstract base
# ---------------------------------------------------------------------------

class Emulator(ABC):
    """Abstract emulator interface.

    Subclasses wrap a concrete emulator library (PyBoy, PyGBA, etc.) and
    expose a uniform API for the agent layer.
    """

    BUTTONS: List[str] = ["a", "b", "start", "select", "up", "down", "left", "right"]

    def __init__(self) -> None:
        self.frame_count: int = 0
        self.rom_path: Optional[str] = None

    # -- lifecycle ----------------------------------------------------------

    @abstractmethod
    def load(self, rom_path: str) -> None:
        """Load a ROM file and initialise the emulator."""

    @abstractmethod
    def close(self) -> None:
        """Shut down the emulator and release resources."""

    # -- input --------------------------------------------------------------

    @abstractmethod
    def press(self, button: str, frames: int = 1) -> None:
        """Press *button* and hold it for *frames* frames.

        Parameters
        ----------
        button : str
            One of ``BUTTONS``.
        frames : int
            How many frames to hold the button before releasing.
        """

    @abstractmethod
    def release_all(self) -> None:
        """Release every button."""

    # -- timing -------------------------------------------------------------

    @abstractmethod
    def tick(self, frames: int = 1) -> None:
        """Advance the emulation by *frames* frames."""

    # -- video --------------------------------------------------------------

    @abstractmethod
    def get_screen(self) -> "Image.Image":
        """Return the current screen as a PIL Image."""

    # -- memory -------------------------------------------------------------

    @abstractmethod
    def read_u8(self, addr: int) -> int:
        """Read an unsigned 8-bit value from *addr*."""

    @abstractmethod
    def read_u16(self, addr: int) -> int:
        """Read an unsigned 16-bit little-endian value from *addr*."""

    @abstractmethod
    def read_u32(self, addr: int) -> int:
        """Read an unsigned 32-bit little-endian value from *addr*."""

    @abstractmethod
    def read_range(self, addr: int, size: int) -> bytes:
        """Read *size* bytes starting at *addr*."""

    # -- save / load --------------------------------------------------------

    @abstractmethod
    def save_state(self, path: str) -> None:
        """Persist an emulator save-state to *path*."""

    @abstractmethod
    def load_state(self, path: str) -> None:
        """Restore an emulator save-state from *path*."""

    # -- info ---------------------------------------------------------------

    def get_info(self) -> Dict:
        """Return runtime metadata about the emulator."""
        return {
            "backend": self.__class__.__name__,
            "rom_path": self.rom_path,
            "frame_count": self.frame_count,
        }


# ---------------------------------------------------------------------------
# PyBoy backend (Game Boy / Game Boy Color)
# ---------------------------------------------------------------------------

class PyBoyEmulator(Emulator):
    """Wraps the *PyBoy* library for .gb / .gbc ROMs.

    Runs headless (``window='null'``) so no display server is required.
    """

    def __init__(self) -> None:
        super().__init__()
        self._pyboy: Optional[object] = None

    # -- lifecycle ----------------------------------------------------------

    def load(self, rom_path: str) -> None:
        """Load a Game Boy ROM via PyBoy."""
        try:
            from pyboy import PyBoy  # type: ignore[import-untyped]
        except ImportError as exc:
            raise ImportError(
                "PyBoy is required for .gb/.gbc ROMs.  "
                "Install it with:  pip install pyboy"
            ) from exc

        rom_path = str(Path(rom_path).expanduser().resolve())
        if not os.path.isfile(rom_path):
            raise FileNotFoundError(f"ROM not found: {rom_path}")

        self._pyboy = PyBoy(rom_path, window="null")
        self.rom_path = rom_path
        self.frame_count = 0

    def close(self) -> None:
        """Stop PyBoy."""
        if self._pyboy is not None:
            self._pyboy.stop(save=False)  # type: ignore[union-attr]
            self._pyboy = None

    # -- input --------------------------------------------------------------

    def press(self, button: str, frames: int = 1) -> None:
        """Press a button and hold it for *frames* frames, then release.

        Uses button_press/button_release (not button()) to ensure the
        button stays held for the full duration. PyBoy's button() auto-
        releases after ``delay`` ticks which can cause issues with Gen 1
        walk registration that needs multi-frame holds.
        """
        button = button.lower()
        if button not in self.BUTTONS:
            raise ValueError(f"Unknown button '{button}'. Valid: {self.BUTTONS}")
        pb = self._pyboy
        pb.button_press(button)  # type: ignore[union-attr]
        self.tick(frames)
        pb.button_release(button)  # type: ignore[union-attr]

    def release_all(self) -> None:
        """Release all buttons."""
        pb = self._pyboy
        for btn in self.BUTTONS:
            try:
                pb.button_release(btn)  # type: ignore[union-attr]
            except Exception:
                pass

    # -- timing -------------------------------------------------------------

    def tick(self, frames: int = 1) -> None:
        """Advance emulation by *frames* frames."""
        pb = self._pyboy
        for _ in range(frames):
            pb.tick()  # type: ignore[union-attr]
            self.frame_count += 1

    # -- video --------------------------------------------------------------

    def get_screen(self) -> "Image.Image":
        """Return current screen as a PIL Image (160×144)."""
        return self._pyboy.screen.image  # type: ignore[union-attr]

    # -- memory -------------------------------------------------------------

    def read_u8(self, addr: int) -> int:
        return self._pyboy.memory[addr] & 0xFF  # type: ignore[index]

    def read_u16(self, addr: int) -> int:
        lo = self._pyboy.memory[addr] & 0xFF  # type: ignore[index]
        hi = self._pyboy.memory[addr + 1] & 0xFF  # type: ignore[index]
        return (hi << 8) | lo

    def read_u32(self, addr: int) -> int:
        b = bytes(self._pyboy.memory[addr : addr + 4])  # type: ignore[index]
        return int.from_bytes(b, "little")

    def read_range(self, addr: int, size: int) -> bytes:
        return bytes(self._pyboy.memory[addr : addr + size])  # type: ignore[index]

    # -- save / load --------------------------------------------------------

    def save_state(self, path: str) -> None:
        """Save emulator state to a file."""
        path = str(Path(path).expanduser().resolve())
        with open(path, "wb") as f:
            self._pyboy.save_state(f)  # type: ignore[union-attr]

    def load_state(self, path: str) -> None:
        """Load emulator state from a file."""
        path = str(Path(path).expanduser().resolve())
        with open(path, "rb") as f:
            self._pyboy.load_state(f)  # type: ignore[union-attr]

    # -- info ---------------------------------------------------------------

    def get_info(self) -> Dict:
        info = super().get_info()
        info["platform"] = "GB/GBC"
        return info


# ---------------------------------------------------------------------------
# PyGBA backend (Game Boy Advance)
# ---------------------------------------------------------------------------

class PyGBAEmulator(Emulator):
    """Wraps the *PyGBA / mgba-py* library for .gba ROMs.

    This is a Phase-2 backend.  The interface mirrors :class:`PyBoyEmulator`
    so agent code is backend-agnostic.
    """

    _BUTTON_MAP = {
        "a": "press_a",
        "b": "press_b",
        "start": "press_start",
        "select": "press_select",
        "up": "press_up",
        "down": "press_down",
        "left": "press_left",
        "right": "press_right",
    }

    def __init__(self) -> None:
        super().__init__()
        self._gba: Optional[object] = None

    # -- lifecycle ----------------------------------------------------------

    def load(self, rom_path: str) -> None:
        """Load a GBA ROM via PyGBA / mgba."""
        try:
            from pygba import PyGBA  # type: ignore[import-untyped]
        except ImportError as exc:
            raise ImportError(
                "PyGBA (mgba-py) is required for .gba ROMs.  "
                "Install it with:  pip install pygba"
            ) from exc

        rom_path = str(Path(rom_path).expanduser().resolve())
        if not os.path.isfile(rom_path):
            raise FileNotFoundError(f"ROM not found: {rom_path}")

        self._gba = PyGBA.load(rom_path)  # type: ignore[attr-defined]
        self.rom_path = rom_path
        self.frame_count = 0

    def close(self) -> None:
        """Release PyGBA resources."""
        self._gba = None

    # -- input --------------------------------------------------------------

    def press(self, button: str, frames: int = 1) -> None:
        button = button.lower()
        method = self._BUTTON_MAP.get(button)
        if method is None:
            raise ValueError(f"Unknown button '{button}'. Valid: {self.BUTTONS}")
        getattr(self._gba, method)()  # type: ignore[union-attr]
        self.tick(frames)

    def release_all(self) -> None:
        # PyGBA buttons auto-release after wait(); no-op here.
        pass

    # -- timing -------------------------------------------------------------

    def tick(self, frames: int = 1) -> None:
        self._gba.wait(frames)  # type: ignore[union-attr]
        self.frame_count += frames

    # -- video --------------------------------------------------------------

    def get_screen(self) -> "Image.Image":
        return self._gba.screen.to_pil()  # type: ignore[union-attr]

    # -- memory -------------------------------------------------------------

    def read_u8(self, addr: int) -> int:
        return self._gba.read_u8(addr)  # type: ignore[union-attr]

    def read_u16(self, addr: int) -> int:
        return self._gba.read_u16(addr)  # type: ignore[union-attr]

    def read_u32(self, addr: int) -> int:
        return self._gba.read_u32(addr)  # type: ignore[union-attr]

    def read_range(self, addr: int, size: int) -> bytes:
        return bytes(self._gba.read_u8(addr + i) for i in range(size))  # type: ignore[union-attr]

    # -- save / load --------------------------------------------------------

    def save_state(self, path: str) -> None:
        self._gba.save_state(path)  # type: ignore[union-attr]

    def load_state(self, path: str) -> None:
        self._gba.load_state(path)  # type: ignore[union-attr]

    # -- info ---------------------------------------------------------------

    def get_info(self) -> Dict:
        info = super().get_info()
        info["platform"] = "GBA"
        return info


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

_EXT_MAP = {
    ".gb": PyBoyEmulator,
    ".gbc": PyBoyEmulator,
    ".gba": PyGBAEmulator,
}


def create_emulator(rom_path: str) -> Emulator:
    """Create the appropriate emulator for *rom_path* based on file extension.

    Parameters
    ----------
    rom_path : str
        Path to a Game Boy (.gb/.gbc) or Game Boy Advance (.gba) ROM.

    Returns
    -------
    Emulator
        A loaded, ready-to-use emulator instance.

    Raises
    ------
    ValueError
        If the file extension is not recognised.
    """
    ext = Path(rom_path).suffix.lower()
    cls = _EXT_MAP.get(ext)
    if cls is None:
        raise ValueError(
            f"Unsupported ROM extension '{ext}'. "
            f"Supported: {', '.join(_EXT_MAP)}"
        )
    emu = cls()
    emu.load(rom_path)
    return emu
