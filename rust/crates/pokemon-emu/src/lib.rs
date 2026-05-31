//! libmgba-backed emulator layer for the LeafGreen shiny hunt.
//!
//! The pure RNG/IV logic lives in `pokemon-rng`; this crate owns the parts that
//! must drive the emulator: writing gRngValue, stepping frames to trigger an
//! encounter, reading + decrypting the wild mon, and reproducing an exact seed.

pub mod core;
pub mod trigger;

pub use crate::core::Emu;
pub use crate::trigger::{jiggle_trigger, measure_offset, reproduce, Axis, Measured, Trigger};
