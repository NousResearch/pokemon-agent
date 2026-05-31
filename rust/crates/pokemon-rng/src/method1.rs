//! Gen-3 Method 1 (starter roll): four consecutive `Random()` calls — PID low,
//! PID high, then two 15-bit IV words, no gaps.

use crate::ivs::{ivs_from_words, Ivs};
use crate::lcg::lcg_next;

/// Generate (PID, IVs) by Method 1 starting from `seed`.
pub fn gen_method1(seed: u32) -> (u32, Ivs) {
    let mut s = lcg_next(seed);
    let pid_low = (s >> 16) & 0xFFFF;
    s = lcg_next(s);
    let pid_high = (s >> 16) & 0xFFFF;
    let pid = (pid_high << 16) | pid_low;
    s = lcg_next(s);
    let iv1 = ((s >> 16) & 0x7FFF) as u16;
    s = lcg_next(s);
    let iv2 = ((s >> 16) & 0x7FFF) as u16;
    (pid, ivs_from_words(iv1, iv2))
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::lcg::lcg_next;

    #[test]
    fn matches_manual_chain() {
        let seed = 0x1234_5678u32;
        let s1 = lcg_next(seed);
        let s2 = lcg_next(s1);
        let s3 = lcg_next(s2);
        let s4 = lcg_next(s3);
        let pid = (((s2 >> 16) & 0xFFFF) << 16) | ((s1 >> 16) & 0xFFFF);
        let (p, iv) = gen_method1(seed);
        assert_eq!(p, pid);
        assert_eq!(iv.hp, ((s3 >> 16) & 31) as u8);
        assert_eq!(iv.spe, ((s4 >> 16) & 31) as u8);
        for v in iv.as_array() {
            assert!(v <= 31);
        }
    }
}
