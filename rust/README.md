# Shiny LeafGreen hunter — Rust

All-Rust port of the Gen-3 (Pokémon LeafGreen) shiny-hunting stack. Replaces the
former Python pipeline (`pokemon_agent/{shiny_gen3,gen3_rng,wild_enumerate,
gba_trigger,…}.py` + `hunt_*.py`). The Gen-1 (Red) / Gen-2 (Gold) Python code is
unchanged and still lives at the repo root.

## Crates
- **`pokemon-rng`** — pure core (no emulator): LCG RNG, PID/IV decode, decrypt,
  wild-encounter generation, the offline VBlank IV model, the rayon-parallel 2^32
  shiny enumeration, ranking, the reproduce offset-lattice math, and `.npz` cache
  I/O (numpy-compatible). Host-testable, no native deps.
- **`pokemon-emu`** — libmgba-backed emulator layer: `Emu` (load ROM/`.ss1`,
  memory R/W, frame stepping, snapshot, decrypt the wild mon) and the encounter
  triggers (`jiggle_trigger`, `measure_offset`, `reproduce`).
- **`shiny-hunt`** — the CLI: `enumerate`, `hunt`, `reproduce`, `list`.
- **`vendor/mgba-rs`** — a pinned, patched copy of
  [`ocnc/mgba-rs`](https://github.com/ocnc/mgba-rs): builds libmgba 0.11 from
  source (cmake) with `USE_PNG=ON` (our `.ss1` are PNG save states), an extended
  bindgen allowlist (`mCoreLoad/SaveStateNamed`), and dynamic linking.

## Build & run
The pure crate builds on the host; the emulator crates need the **`devbox`**
distrobox (cmake, clang/libclang for bindgen, libpng). Run hunts from the **repo
root** so `roms/` and `cache_*.npz` resolve.

```sh
# host: pure logic + the differential gate against the existing Python caches
cd rust && cargo test -p pokemon-rng
cargo test --release -p pokemon-rng --test differential -- --ignored   # full 2^32 scan

# devbox: build the CLI and run a hunt (from the repo root)
distrobox enter devbox -- bash -lc 'cd <repo>/rust && cargo build --release -p shiny-hunt'
distrobox enter devbox -- bash -lc 'cd <repo> && ./rust/target/release/shiny-hunt hunt clefairy'

# devbox: emulator integration tests (golden + grass/cave reproduce)
distrobox enter devbox -- bash -lc 'cd <repo>/rust && cargo test -p pokemon-emu -- --test-threads=1'
```

`shiny-hunt hunt <species>` (clefairy/spearow/nidoranm): rank candidates offline,
realize the top-N by reproducing them in the emulator, and save the best as a
catchable `roms/leafgreen_shiny_<species>.ss1`.

## Notes / gotchas
- libmgba links **dynamically**; the build script copies `libmgba.so*` next to the
  binary/test executables and an `$ORIGIN` rpath (`.cargo/config.toml`) finds it.
  (Static linking hit `rust-lld` archive-member-pull / `--gc-sections` issues.)
- `devbox` needs `clang`/`clang-devel` for bindgen: `sudo dnf install clang clang-devel`.
- The vendored mGBA source ships without icon resources; stub `res/mgba-*.png` were
  added so cmake's install step succeeds.
- Determinism: same libmgba as before ⇒ bit-identical to the old Python (the golden
  seed `0x55FF2959` still yields Hasty Spearow `31/31/17/31/19/31`; the differential
  test replays every existing cache row through the Rust enumerator).
