//! Gen-3 linear congruential RNG: `seed = seed*0x41C64E6D + 0x6073 (mod 2^32)`.
//! `Random()` returns the high 16 bits of the advanced seed.

pub const LCG_MULT: u32 = 0x41C6_4E6D;
pub const LCG_ADD: u32 = 0x0000_6073;
/// Modular inverse of `LCG_MULT` mod 2^32, for stepping the LCG backwards.
pub const LCG_MULT_INV: u32 = 0xEEB9_EB65;

/// Advance the LCG one step.
#[inline]
pub fn lcg_next(seed: u32) -> u32 {
    seed.wrapping_mul(LCG_MULT).wrapping_add(LCG_ADD)
}

/// Step the LCG one step backwards (inverse of [`lcg_next`]).
#[inline]
pub fn lcg_prev(seed: u32) -> u32 {
    seed.wrapping_sub(LCG_ADD).wrapping_mul(LCG_MULT_INV)
}

/// Step the LCG backwards `n` times.
#[inline]
pub fn rewind(seed: u32, n: u32) -> u32 {
    let mut s = seed;
    for _ in 0..n {
        s = lcg_prev(s);
    }
    s
}

/// Step the LCG forwards `n` times.
#[inline]
pub fn advance(seed: u32, n: u32) -> u32 {
    let mut s = seed;
    for _ in 0..n {
        s = lcg_next(s);
    }
    s
}

/// `Random()` — advance the seed and return its high 16 bits.
#[inline]
pub fn rng16(seed: u32) -> u16 {
    (lcg_next(seed) >> 16) as u16
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn inv_is_modular_inverse() {
        assert_eq!(LCG_MULT.wrapping_mul(LCG_MULT_INV), 1);
    }

    #[test]
    fn next_matches_formula() {
        // (0 * MULT + ADD) & U32
        assert_eq!(lcg_next(0), LCG_ADD);
        // a couple of hand chains
        let s = 0x1234_5678u32;
        assert_eq!(lcg_next(s), s.wrapping_mul(LCG_MULT).wrapping_add(LCG_ADD));
    }

    #[test]
    fn prev_inverts_next() {
        for &s in &[0u32, 1, 0x6073, 0xDEAD_BEEF, 0xFFFF_FFFF, 0x55FF_2959] {
            assert_eq!(lcg_prev(lcg_next(s)), s);
            assert_eq!(lcg_next(lcg_prev(s)), s);
        }
    }

    #[test]
    fn rewind_advance_roundtrip() {
        let s = 0x0002_D02Au32;
        for n in [0u32, 1, 71, 240, 294, 1000] {
            assert_eq!(rewind(advance(s, n), n), s);
            assert_eq!(advance(rewind(s, n), n), s);
        }
    }
}
