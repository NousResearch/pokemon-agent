# mgba-sys

Raw FFI bindings to [libmgba](https://mgba.io/), a Game Boy Advance emulator core.

## Vendored libmgba

This crate includes a vendored copy of the libmgba source (GBA-only, trimmed
to ~3 MB) built automatically by the `build.rs` script. No git submodules
required.

- **libmgba version:** 0.10.0-1260-g6a99e17f5
- **libmgba commit:** [`6a99e17f59a6185251e8046aab7b999b6b3278fe`](https://github.com/mgba-emu/mgba/tree/6a99e17f59a6185251e8046aab7b999b6b3278fe)

## Building

Requires:

- **cmake** — builds the vendored libmgba C library
- **clang** — used by bindgen to generate Rust bindings
- **zlib** — compression library (usually pre-installed on macOS/Linux)

```sh
cargo build -p mgba-sys
```

## Usage

This crate exposes the raw C API. For a safe wrapper, use the [`mgba`](../mgba)
crate instead.

## License

MIT — applies to the Rust binding code in this crate. The bundled libmgba library
(`mgba/`) is licensed under [MPL-2.0](mgba/LICENSE).
