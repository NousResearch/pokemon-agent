"""Load/save mGBA savestate *files* from Python.

The mgba Python bindings only expose ``save_raw_state()`` /
``load_raw_state()``, which deal in the bare ``GBASerializedState`` struct.
The standalone **mGBA app** writes savestate files in its native format —
which (when built with PNG support, as ours is) is a **PNG with the state
embedded in it**, plus optional extdata (savedata/RTC/screenshot).  Those
files do *not* load via ``load_raw_state``.

This module bridges the gap by calling libmgba's own
``mCoreLoadStateNamed`` / ``mCoreSaveStateNamed`` through the cffi ``lib``,
so a state created in the mGBA GUI loads correctly here regardless of its
on-disk format.

Workflow: play in the mGBA app, save a state next to the ROM
(``roms/...ss1`` etc. — mGBA has host filesystem access), then load it in a
hunt script with :func:`load_state_file`.
"""

from __future__ import annotations

from pathlib import Path

import mgba.core
import mgba.vfs as vfs

# from include/mgba/core/serialize.h
SAVESTATE_SCREENSHOT = 1
SAVESTATE_SAVEDATA = 2
SAVESTATE_CHEATS = 4
SAVESTATE_RTC = 8
SAVESTATE_METADATA = 16
SAVESTATE_ALL = 31

_lib = mgba.core.lib


def load_state_file(core, path: str | Path, flags: int = SAVESTATE_ALL) -> bool:
    """Load an mGBA savestate file (any native format) into ``core``.

    ``core`` is the ``mgba.core.Core`` wrapper (as returned by
    ``mgba.core.load_path`` or ``PyGBA.core``).  Returns True on success.
    """
    path = str(Path(path))
    vf = vfs.open_path(path, "r")
    if vf is None:
        raise FileNotFoundError(f"could not open savestate: {path}")
    try:
        return bool(_lib.mCoreLoadStateNamed(core._core, vf.handle, flags))
    finally:
        vf.close()


def save_state_file(core, path: str | Path, flags: int = SAVESTATE_ALL) -> bool:
    """Write ``core``'s state to ``path`` in mGBA's native savestate format.

    With ``SAVESTATE_SCREENSHOT`` set (the default via ``SAVESTATE_ALL``) and
    a PNG-enabled libmgba, the file is a PNG — directly openable in the mGBA
    app's "load state from file".
    """
    path = str(Path(path))
    vf = vfs.open_path(path, "w")
    if vf is None:
        raise OSError(f"could not open for writing: {path}")
    try:
        return bool(_lib.mCoreSaveStateNamed(core._core, vf.handle, flags))
    finally:
        vf.close()
