# GBA (Pokémon LeafGreen / FireRed) emulation setup

> **The LeafGreen shiny-hunting pipeline is now Rust** — see [`rust/README.md`](../rust/README.md).
> It builds libmgba directly (via the vendored `mgba-rs`), so the PyGBA/cffi setup
> below is only needed for the remaining Python utilities (e.g. `play_gba.py`).

The Game Boy / GBC shiny scripts use **PyBoy**. GBA games (Gen 3 — LeafGreen,
FireRed, Ruby/Sapphire/Emerald) need a different emulator: **mGBA** via its
Python (cffi) bindings, wrapped by **PyGBA**.

Unlike PyBoy, none of this installs cleanly from PyPI:

- `mgba` (the Python bindings) is **not on PyPI at all** — it ships only as
  part of an mGBA source build with `-DBUILD_PYTHON=ON`.
- `pygba` *is* on PyPI but hard-depends on `mgba` (and on `pygame`, which
  needs SDL2 dev headers / a matching wheel).

## Why a distrobox, and why Python 3.12

We build everything inside the **`devbox`** distrobox (Fedora 41) instead of
on the host:

- keeps the host system clean (no `-devel` packages, no `make install`)
- passwordless sudo inside the container
- the repo is bind-mounted at the same path, so `.venv-gba` and `roms/` are
  shared between host and container

The host's default interpreter is Python **3.14**, which is too new for these
native builds (pygame failed to build, cffi/mgba compatibility is unproven).
We use Python **3.12** inside the devbox, which has wheels for pygame /
gymnasium and builds mGBA's cffi bindings cleanly.

GBA scripts therefore run **inside the devbox**:

```
distrobox enter devbox -- /var/home/karce/Projects/pokemon-agent/.venv-gba/bin/python shiny_leafgreen.py
```

## One-shot build

```
distrobox enter devbox -- bash /var/home/karce/Projects/pokemon-agent/scripts/build_mgba.sh
```

That script is the source of truth. It installs deps, builds mGBA 0.10.3 +
the Python bindings against `.venv-gba`, and installs `mgba` + `pygba`.

## The two gotchas (already handled in the build script)

1. **GCC 14 promotes warnings to errors.** The cffi-generated `lib.c` has a
   `va_list` vs `void *` mismatch in the `mLogger` field check. Fix:
   `-Wno-error=incompatible-pointer-types -Wno-error=implicit-function-declaration`,
   passed *both* as `CMAKE_C_FLAGS` (for the cmake-compiled object) **and** as
   the `CFLAGS` env var (for the setuptools/cffi-driven build, which doesn't
   inherit cmake flags).

2. **`USE_FFMPEG=OFF` breaks the bindings.** mGBA 0.10.3's e-Reader scan
   functions (`EReaderScan*`, `EReaderBlockList*`) are declared unconditionally
   in the headers but *defined* only inside a `#ifdef USE_FFMPEG` block in
   `src/gba/cart/ereader.c`. With ffmpeg off, the cffi bindings reference ~28
   symbols that libmgba doesn't export → `ImportError: undefined symbol:
   EReaderScanLoadImageA` at `import mgba`. Fix: build with `-DUSE_FFMPEG=ON`
   (needs `ffmpeg-free-devel`). e-Reader is irrelevant to us, but enabling
   ffmpeg is far more robust than trying to gate the headers across files.

## Working API (mgba 0.10.3 + pygba 0.2.9)

`PyGBA` (from `pygba`):

- `PyGBA.load(rom_path)` → `gba`
- `gba.wait(n)` — advance `n` frames
- `gba.press_a()`, `press_b()`, `press_up/down/left/right()`, `press_l/r()`,
  `press_start()`, `press_select()`, `press_key(...)`
- `gba.read_u8(addr)`, `read_u16(addr)`, `read_u32(addr)`, `read_memory(addr, n)`

Lower-level (via `gba.core`, the mgba core):

- **memory writes:** `gba.core.memory.u8[addr] = value` (and `.u16` / `.u32`)
- **save states (in-memory):** `state = gba.core.save_raw_state()` /
  `gba.core.load_raw_state(state)` — analogous to PyBoy's BytesIO save/load
- `gba.core.run_frame()`, `gba.core.frame_counter`

> ⚠️ `pygba.PyGBA` has **no** `save_state(path)` method, so the repo's
> `pokemon_agent/emulator.py` `PyGBAEmulator.save_state/load_state` (which call
> `self._gba.save_state(path)`) will fail. The standalone shiny scripts bypass
> that and use `core.save_raw_state()` directly.

- **silence the noisy BIOS logger** before loading: `import mgba.log;
  mgba.log.silence()`

## Playing the game / creating save states

### Recommended: the mGBA Flatpak app (has audio + a real UI)

The host is atomic Fedora, so install via Flatpak (one-time, already done):

```
flatpak remote-add --user --if-not-exists flathub https://dl.flathub.org/repo/flathub.flatpakrepo
flatpak install -y --user flathub io.mgba.mGBA
flatpak run io.mgba.mGBA
```

mGBA has `host` filesystem access, so open the ROM directly from
`roms/Pokemon - LeafGreen Version (USA).gba`. Play to the point you want,
then **save a state** (mGBA: `Shift+F1..F9` save slot, `F1..F9` load).
Slot states are written next to the ROM, e.g.
`roms/Pokemon - LeafGreen Version (USA).ss1`.

For the **starter-reset hunt**: play to the moment just before you confirm
your starter, then save to a slot. Tell me which slot — the hunt script
loads that file.

#### Savestate format bridge (important)

mGBA's native savestates are **PNG files** (the screenshot *is* the file,
with the state embedded). The bindings' `load_raw_state()` only understands
the bare struct and will **reject** a PNG state. Load mGBA app states
through `pokemon_agent/gba_state.py`, which calls libmgba's own
`mCoreLoadStateNamed`:

```python
import mgba.core
from pokemon_agent.gba_state import load_state_file
core = mgba.core.load_path("roms/Pokemon - LeafGreen Version (USA).gba")
core.reset()
load_state_file(core, "roms/Pokemon - LeafGreen Version (USA).ss1")
```

Verified: a PNG savestate written by libmgba loads back and restores state
exactly. (The app is 0.10.5 and the bindings are 0.10.3 — same savestate
era; if a real app-made state ever fails to load, rebuild the bindings from
the 0.10.5 tag via `scripts/build_mgba.sh`.)

### Alternative: `play_gba.py` (scripted/headless, no audio)

A pygame (SDL2) window driving mGBA from Python; **no audio** (the audio
subsystem is stubbed). Useful for automation, not for comfortable play.
Run inside the devbox:

```
distrobox enter devbox -- \
  /var/home/karce/Projects/pokemon-agent/.venv-gba/bin/python play_gba.py
```

Controls: arrows = D-pad, `Z`/`X` = A/B, `Enter` = Start, `Backspace` =
Select, `Q`/`W` = L/R, hold `Space` = turbo, `Esc` = quit. Save states
written here use `save_raw_state()` (bare struct), so load them with
`load_raw_state()`, *not* the `gba_state` helper.

## Gen 3 vs Gen 2 shiny mechanics (important — different!)

Gen 2 (Gold) shininess is a function of **DVs**. Gen 3 is completely
different — it's a function of the 32-bit **Personality Value (PID)** and the
trainer IDs:

```
shiny  ⇔  (TID ^ SID ^ (PID >> 16) ^ (PID & 0xFFFF)) < 8
```

IVs (0–31 each) are stored separately and don't affect shininess. Party/box
Pokémon data is also **encrypted** (key = `PID ^ OTID`, 12-byte substructures
reordered by `PID % 24`) — see `pokemon_agent/memory/firered.py` for the
address/decryption scaffolding (LeafGreen shares FireRed's engine).
