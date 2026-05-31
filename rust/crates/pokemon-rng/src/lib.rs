//! Pure Gen-3 (FireRed/LeafGreen) RNG and shiny-hunting core.
//!
//! The LCG is `seed = seed*0x41C64E6D + 0x6073 (mod 2^32)` and `Random()` returns
//! the high 16 bits. Wild generation rolls slot, level, nature, a nature-lock PID
//! loop, then two IV words; the lone per-frame VBlank `Random()` between the PID
//! loop and the IV reads is what the offline IV model resolves (see [`wild`]).
//! Nothing here touches the emulator — it is exact, fast, and host-testable.

pub mod cache;
pub mod decrypt;
pub mod enumerate;
pub mod ivs;
pub mod lcg;
pub mod method1;
pub mod pid;
pub mod predict;
pub mod reproduce;
pub mod slots;
pub mod wild;

pub use enumerate::{enum_candidate, enumerate, Candidate, Filter};
pub use ivs::Ivs;
pub use lcg::{advance, lcg_next, lcg_prev, rewind};
pub use pid::{is_shiny, nature_of, shiny_value};
pub use wild::{generate_wild, wild_outcome, wild_outcome_both, wild_outcome_exact, WildSpawn};
