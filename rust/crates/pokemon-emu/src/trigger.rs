//! Encounter triggers. Ports `gba_trigger.py`: write a seed into gRngValue, mash a
//! left/right (or up/down) jiggle until an encounter fires, read the wild mon.

use pokemon_rng::lcg::lcg_next;
use pokemon_rng::reproduce::probe_order_default;
use pokemon_rng::{advance, generate_wild, rewind, Ivs};

use crate::core::{Emu, RNG_ADDR};

/// GBA key bitmasks (from the mgba `Key` enum order).
const KEY_RIGHT: u32 = 1 << 4;
const KEY_LEFT: u32 = 1 << 5;
const KEY_UP: u32 = 1 << 6;
const KEY_DOWN: u32 = 1 << 7;

#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub enum Axis {
    LR,
    UD,
}

impl Axis {
    fn keys(self) -> (u32, u32) {
        match self {
            Axis::LR => (KEY_LEFT, KEY_RIGHT),
            Axis::UD => (KEY_UP, KEY_DOWN),
        }
    }
}

/// Trigger parameters (mirrors the Python defaults: LR, hold=2, rel=1, cap=70,
/// settle=20). `cap` is raised to 140 by the reproduce layer for cave encounters.
#[derive(Clone, Copy, Debug)]
pub struct Trigger {
    pub axis: Axis,
    pub hold: u32,
    pub rel: u32,
    pub cap: u32,
    pub settle: u32,
}

impl Default for Trigger {
    fn default() -> Self {
        Trigger {
            axis: Axis::LR,
            hold: 2,
            rel: 1,
            cap: 70,
            settle: 20,
        }
    }
}

/// Write `v` into gRngValue and jiggle until an encounter fires; read the wild mon.
/// Returns (pid, ivs, species) or None if no encounter within `cap` iterations.
pub fn jiggle_trigger(emu: &mut Emu, v: u32, t: Trigger) -> Option<(u32, Ivs, u16)> {
    emu.reset_to_base();
    emu.write32(RNG_ADDR, v);
    let bp = emu.enemy_word();
    let (k1, k2) = t.axis.keys();
    let mut hit = false;
    for i in 0..t.cap {
        let btn = if i % 2 == 0 { k1 } else { k2 };
        for ph in 0..(t.hold + t.rel) {
            emu.set_keys(if ph < t.hold { btn } else { 0 });
            emu.run_frame();
            if emu.enemy_word() != bp {
                hit = true;
                break;
            }
        }
        if hit {
            break;
        }
    }
    if !hit {
        return None;
    }
    for _ in 0..t.settle {
        emu.run_frame();
    }
    emu.read_enemy()
}

/// LCG steps from `a` to `b` along the clean chain, or None if not within `cap`.
fn calls_between(a: u32, b: u32, cap: u32) -> Option<u32> {
    let mut s = a;
    for n in 0..cap {
        if s == b {
            return Some(n);
        }
        s = lcg_next(s);
    }
    None
}

/// A measured trigger: the wild mon plus the realized generation offset `R` (clean
/// RNG calls consumed from the written seed `v` before generation) and the seed it
/// was generated from (`advance(v, R)`). Ports `gba_trigger.measure_offset`.
pub struct Measured {
    pub pid: u32,
    pub ivs: Ivs,
    pub species: u16,
    pub r: u32,
    pub gen_seed: u32,
}

/// Run the same jiggle as [`jiggle_trigger`] but also MEASURE the realized offset
/// `R` via clean-chain counting + a pid-pinned search (window `rmax`).
pub fn measure_offset(emu: &mut Emu, v: u32, t: Trigger, rmax: u32) -> Option<Measured> {
    emu.reset_to_base();
    emu.write32(RNG_ADDR, v);
    let bp = emu.enemy_word();
    let (k1, k2) = t.axis.keys();
    let mut prev = emu.read32(RNG_ADDR);
    let mut total: u32 = 0;
    let mut n: Option<u32> = None;
    let mut hit = false;
    let mut i = 0;
    while i < t.cap && !hit {
        let btn = if i % 2 == 0 { k1 } else { k2 };
        for ph in 0..(t.hold + t.rel) {
            emu.set_keys(if ph < t.hold { btn } else { 0 });
            emu.run_frame();
            let cur = emu.read32(RNG_ADDR);
            if emu.enemy_word() != bp {
                hit = true;
                if n.is_none() {
                    n = Some(total);
                }
                break;
            }
            if let Some(c) = calls_between(prev, cur, 900) {
                if c <= 5 {
                    total += c;
                }
            }
            prev = cur;
        }
        i += 1;
    }
    let n = match (hit, n) {
        (true, Some(n)) => n,
        _ => return None,
    };
    for _ in 0..t.settle {
        emu.run_frame();
    }
    let (pid, ivs, species) = emu.read_enemy()?;
    // Pin the exact offset: search a small window around N first, then [0, rmax).
    let lo = n.saturating_sub(4);
    let hi = (n + 16).min(rmax);
    for r in lo..hi {
        if generate_wild(advance(v, r), 0).pid == pid {
            return Some(Measured {
                pid,
                ivs,
                species,
                r,
                gen_seed: advance(v, r),
            });
        }
    }
    for r in 0..rmax {
        if generate_wild(advance(v, r), 0).pid == pid {
            return Some(Measured {
                pid,
                ivs,
                species,
                r,
                gen_seed: advance(v, r),
            });
        }
    }
    None
}

/// Reproduce a specific generation-seed `g` and read its TRUE IVs — encounter-type
/// agnostic. Probes the reproducing-offset lattice (`probe_order`), writing
/// `rewind(g, o)` and accepting the first offset whose measured gen-seed == `g`
/// (verified by 32-bit equality + pid + species). Ports `gba_trigger.reproduce`.
pub fn reproduce(
    emu: &mut Emu,
    g: u32,
    pid: u32,
    species: Option<u16>,
    t: Trigger,
    off0: i32,
    rmax: u32,
) -> Option<(u32, Ivs, u16, u32)> {
    // Cave encounters fire ~iter 74-77, so reproduce needs cap >= 140.
    let t = Trigger {
        cap: t.cap.max(140),
        ..t
    };
    for o in probe_order_default(off0) {
        let v = rewind(g, o as u32);
        if let Some(m) = measure_offset(emu, v, t, rmax) {
            if m.gen_seed == g && m.pid == pid && species.is_none_or(|s| m.species == s) {
                return Some((m.pid, m.ivs, m.species, m.r));
            }
        }
    }
    None
}
