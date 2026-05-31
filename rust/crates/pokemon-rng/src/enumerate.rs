//! Bulk shiny-candidate enumeration over the full 2^32 generation-seed space.
//! Mirrors `wild_enumerate._enum_range` bit-for-bit; rayon replaces numpy/numba.

use crate::lcg::lcg_next;
use crate::pid::NUM_NATURES;
use crate::slots::slot_index;
use crate::wild::MAX_NATURE_LOOP;
use rayon::prelude::*;

/// One shiny candidate: the env-independent ingredients the IV model needs.
#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub struct Candidate {
    pub g: u32,
    pub pid: u32,
    pub nature: u8,
    pub iters: u32,
    pub o1: u16,
    pub o2: u16,
    pub o3: u16,
    pub o4: u16,
}

/// Filters for the scan: allowed encounter slots (bit i) and natures (bit i).
#[derive(Clone, Copy)]
pub struct Filter {
    pub tid: u16,
    pub sid: u16,
    pub slot_mask: u16,
    pub nature_mask: u32,
}

impl Filter {
    pub fn new(tid: u16, sid: u16, slots: &[u8], natures: &[u8]) -> Self {
        let slot_mask = slots.iter().fold(0u16, |m, &s| m | (1 << s));
        let nature_mask = natures.iter().fold(0u32, |m, &n| m | (1 << n));
        Filter {
            tid,
            sid,
            slot_mask,
            nature_mask,
        }
    }
}

/// Evaluate one generation seed; `Some(Candidate)` iff it yields an allowed-slot,
/// allowed-nature, shiny encounter for this TID/SID.
#[inline]
pub fn enum_candidate(g: u32, f: &Filter) -> Option<Candidate> {
    let mut s = lcg_next(g);
    let slot = slot_index((s >> 16) as u16);
    if (f.slot_mask >> slot) & 1 == 0 {
        return None;
    }
    s = lcg_next(s); // level
    s = lcg_next(s); // nature roll
    let nature = ((s >> 16) % NUM_NATURES) as u8;
    if (f.nature_mask >> nature) & 1 == 0 {
        return None;
    }
    // nature-lock PID loop
    let mut pid = 0u32;
    let mut iters = 0u32;
    let mut matched = false;
    for i in 1..=MAX_NATURE_LOOP {
        s = lcg_next(s);
        let lo = (s >> 16) & 0xFFFF;
        s = lcg_next(s);
        let hi = (s >> 16) & 0xFFFF;
        pid = (hi << 16) | lo;
        if (pid % NUM_NATURES) as u8 == nature {
            iters = i;
            matched = true;
            break;
        }
    }
    if !matched {
        return None;
    }
    // shiny check
    let xb = (f.tid ^ f.sid) as u32;
    if ((xb ^ (pid >> 16) ^ (pid & 0xFFFF)) & 0xFFFF) >= 8 {
        return None;
    }
    // four post-PID outputs (15-bit)
    let o1 = next15(&mut s);
    let o2 = next15(&mut s);
    let o3 = next15(&mut s);
    let o4 = next15(&mut s);
    Some(Candidate {
        g,
        pid,
        nature,
        iters,
        o1,
        o2,
        o3,
        o4,
    })
}

#[inline]
fn next15(s: &mut u32) -> u16 {
    *s = lcg_next(*s);
    ((*s >> 16) & 0x7FFF) as u16
}

/// Scan the whole 2^32 space in parallel and collect all shiny candidates.
pub fn enumerate(f: &Filter) -> Vec<Candidate> {
    // Chunk the space so rayon balances work and per-chunk Vecs stay cache-friendly.
    const CHUNK: u64 = 1 << 22;
    let n_chunks = (1u64 << 32) / CHUNK;
    (0..n_chunks)
        .into_par_iter()
        .flat_map_iter(move |c| {
            let start = c * CHUNK;
            (start..start + CHUNK).filter_map(move |g| enum_candidate(g as u32, f))
        })
        .collect()
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::wild::wild_outcome_both;

    #[test]
    fn candidate_agrees_with_wild_outcome() {
        // For a known shiny Clefairy seed, the enumerator's pid/o1..o3 must match
        // wild_outcome_both's reachable IVs (iv1 from o1/o2, iv2 from o3).
        let f = Filter::new(
            51376,
            36462,
            &(0..12).collect::<Vec<_>>(),
            &(0..25).collect::<Vec<_>>(),
        );
        let g = 0x0002_D02Au32;
        let c = enum_candidate(g, &f).expect("known shiny seed");
        let (a, b) = wild_outcome_both(g);
        assert_eq!(c.pid, a.pid);
        // a uses iv1=o1, b uses iv1=o2; both use iv2=o3
        use crate::ivs::ivs_from_words;
        assert_eq!(a.ivs, ivs_from_words(c.o1, c.o3));
        assert_eq!(b.ivs, ivs_from_words(c.o2, c.o3));
    }

    #[test]
    fn small_window_finds_only_shiny_allowed() {
        let f = Filter::new(51376, 36462, &[7], &(0..25).collect::<Vec<_>>());
        // brute a small window; every hit must be shiny + slot 7
        for g in 0u32..200_000 {
            if let Some(c) = enum_candidate(g, &f) {
                assert!(crate::pid::is_shiny(c.pid, 51376, 36462));
            }
        }
    }
}
