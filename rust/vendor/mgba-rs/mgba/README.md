# mgba

Safe Rust wrapper around [libmgba](https://mgba.io/) for GBA emulation.

## Usage

```rust
use mgba::Core;
use std::path::Path;

let mut core = Core::new().expect("failed to create core");
core.load_rom(Path::new("game.gba")).expect("failed to load ROM");
core.reset().expect("reset failed");

// Run one frame
core.run_frame().expect("run_frame failed");

// Read the framebuffer (240x160 XBGR8 pixels)
let pixels = core.video_buffer();
```

## Building

This crate depends on `mgba-sys`, which builds libmgba from source via cmake.
See the [mgba-sys README](../mgba-sys/README.md) for build prerequisites.

## Features

- Safe ownership model with RAII cleanup
- Video buffer access (240x160 XBGR8)
- Audio sample reading (stereo interleaved i16 at 32768 Hz)
- Input key mapping
- `Send` but not `Sync` — safe to move between threads, but not to share references

## License

MIT — applies to the Rust wrapper code in this crate. The underlying libmgba library
is licensed under [MPL-2.0](../mgba-sys/mgba/LICENSE).
