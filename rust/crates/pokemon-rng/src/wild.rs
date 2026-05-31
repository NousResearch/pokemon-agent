//! Wild-encounter generation (FR/LG) and the offline VBlank IV model.

use crate::ivs::{ivs_from_words, Ivs};
use crate::lcg::lcg_next;
use crate::pid::NUM_NATURES;
use crate::slots::slot_index;

pub const MAX_NATURE_LOOP: u32 = 1000;

/// Decoded wild generation result from a generation seed.
#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub struct WildSpawn {
    pub slot: u8,
    pub level_rand: u16,
    pub nature: u8,
    pub pid: u32,
    pub ivs: Ivs,
    pub loop_iters: u32,
}

/// Shared prologue: slot, level, nature, and the nature-lock PID loop.
/// Returns (slot, level_rand, nature, pid, iters, state-after-PID).
#[inline]
fn prologue(gen_seed: u32, max_loop: u32) -> (u8, u16, u8, u32, u32, u32) {
    let mut s = lcg_next(gen_seed);
    let slot = slot_index((s >> 16) as u16);
    s = lcg_next(s);
    let level_rand = (s >> 16) as u16;
    s = lcg_next(s);
    let nature = ((s >> 16) % NUM_NATURES) as u8;
    let mut pid = 0u32;
    let mut iters = 0u32;
    for i in 1..=max_loop {
        s = lcg_next(s);
        let lo = (s >> 16) & 0xFFFF;
        s = lcg_next(s);
        let hi = (s >> 16) & 0xFFFF;
        pid = (hi << 16) | lo;
        iters = i;
        if (pid % NUM_NATURES) as u8 == nature {
            break;
        }
    }
    (slot, level_rand, nature, pid, iters, s)
}

#[inline]
fn next_out(s: &mut u32) -> u16 {
    *s = lcg_next(*s);
    ((*s >> 16) & 0x7FFF) as u16
}

/// Simulate FR/LG wild generation from `gen_seed` (state right before the slot
/// `Random()`). `iv_gap` models the lone VBlank advance between PID and IV reads
/// (0 = H-1, 1 = H-2). slot/level/nature/PID are independent of `iv_gap`.
pub fn generate_wild(gen_seed: u32, iv_gap: u32) -> WildSpawn {
    generate_wild_capped(gen_seed, iv_gap, MAX_NATURE_LOOP)
}

pub fn generate_wild_capped(gen_seed: u32, iv_gap: u32, max_loop: u32) -> WildSpawn {
    let (slot, level_rand, nature, pid, iters, mut s) = prologue(gen_seed, max_loop);
    for _ in 0..iv_gap {
        s = lcg_next(s);
    }
    let iv1 = next_out(&mut s);
    let iv2 = next_out(&mut s);
    WildSpawn {
        slot,
        level_rand,
        nature,
        pid,
        ivs: ivs_from_words(iv1, iv2),
        loop_iters: iters,
    }
}

/// Fully-offline wild outcome for a calibrated env: iv2 = o3 always; iv1 = o1 if
/// `loop_iters < iv1_threshold` else o2 (the lone per-frame VBlank shifts it).
pub fn wild_outcome(gen_seed: u32, iv1_threshold: u32) -> WildSpawn {
    let (slot, level_rand, nature, pid, iters, mut s) = prologue(gen_seed, MAX_NATURE_LOOP);
    let o1 = next_out(&mut s);
    let o2 = next_out(&mut s);
    let o3 = next_out(&mut s);
    let iv1 = if iters >= iv1_threshold { o2 } else { o1 };
    WildSpawn {
        slot,
        level_rand,
        nature,
        pid,
        ivs: ivs_from_words(iv1, o3),
        loop_iters: iters,
    }
}

/// Both IV variants a candidate can take (iv1 from o1 vs o2; iv2 = o3 fixed).
pub fn wild_outcome_both(gen_seed: u32) -> (WildSpawn, WildSpawn) {
    (wild_outcome(gen_seed, 1 << 30), wild_outcome(gen_seed, 0))
}

/// Fully exact offline outcome under a deterministic trigger (pinned phi0):
/// iv1 = o1 if loop < ta else o2; iv2 = o2/o3/o4 for 0/1/2 VBlanks (tb_lo, tb_hi).
pub fn wild_outcome_exact(gen_seed: u32, ta: u32, tb_lo: u32, tb_hi: u32) -> WildSpawn {
    let (slot, level_rand, nature, pid, iters, mut s) = prologue(gen_seed, MAX_NATURE_LOOP);
    let outs = [
        next_out(&mut s),
        next_out(&mut s),
        next_out(&mut s),
        next_out(&mut s),
    ];
    let iv1 = outs[if iters >= ta { 1 } else { 0 }];
    let iv2_idx = 1 + (iters >= tb_lo) as usize + (iters >= tb_hi) as usize;
    WildSpawn {
        slot,
        level_rand,
        nature,
        pid,
        ivs: ivs_from_words(iv1, outs[iv2_idx]),
        loop_iters: iters,
    }
}

/// True if `loop` falls in any inclusive ambiguous (lo, hi) range.
pub fn is_boundary_loop(loop_iters: u32, ambig_ranges: &[(u32, u32)]) -> bool {
    ambig_ranges
        .iter()
        .any(|&(lo, hi)| lo <= loop_iters && loop_iters <= hi)
}

/// Derive the per-offset iv1 threshold `T` and an optional ambiguous band from
/// emulator samples `(loop_iters, iv1_uses_o2)`. Returns (threshold, band).
pub fn calibrate_iv_threshold(samples: &[(u32, bool)]) -> (u32, Option<(u32, u32)>) {
    let o1_max = samples
        .iter()
        .filter(|(_, o2)| !o2)
        .map(|(it, _)| *it)
        .max();
    let o2_min = samples
        .iter()
        .filter(|(_, o2)| *o2)
        .map(|(it, _)| *it)
        .min();
    match o2_min {
        None => (1 << 30, None),
        Some(o2_min) => {
            let lo = o1_max.map(|m| m + 1).unwrap_or(0);
            let band = if o2_min >= 1 && (o2_min - 1) >= lo {
                Some((lo, o2_min - 1))
            } else {
                None
            };
            (o2_min, band)
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn pid_matches_nature() {
        for g in [0u32, 1, 0x55FF_2959, 0xDEAD_BEEF, 0x0002_D02A] {
            let w = generate_wild(g, 0);
            assert_eq!((w.pid % NUM_NATURES) as u8, w.nature);
            assert!(w.loop_iters >= 1);
        }
    }

    #[test]
    fn outcome_variants_differ_only_in_iv1_half() {
        let g = 0x55FF_2959;
        let (a, b) = wild_outcome_both(g);
        // iv2 half (Spe/SpA/SpD) identical; pid/nature identical
        assert_eq!((a.pid, a.nature), (b.pid, b.nature));
        assert_eq!(
            (a.ivs.spe, a.ivs.spa, a.ivs.spd),
            (b.ivs.spe, b.ivs.spa, b.ivs.spd)
        );
    }

    #[test]
    fn threshold_calibration() {
        // o1 up to loop 5, o2 from loop 9 -> T=9, band (6,8)
        let s = [(3, false), (5, false), (9, true), (12, true)];
        assert_eq!(calibrate_iv_threshold(&s), (9, Some((6, 8))));
        // contiguous -> no band
        let s2 = [(5, false), (6, true)];
        assert_eq!(calibrate_iv_threshold(&s2), (6, None));
        // never switches
        assert_eq!(calibrate_iv_threshold(&[(4, false)]).0, 1 << 30);
    }
}
