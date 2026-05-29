# GBA (Pokémon LeafGreen / FireRed) emulation setup

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
