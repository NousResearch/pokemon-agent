//! Offline IV prediction / ranking over enumerated candidates.

use crate::enumerate::Candidate;
use crate::ivs::{ivs_from_words, Ivs};

/// The four IV variants a candidate can realize across trigger timings:
/// iv1 ∈ {o1, o2}, iv2 ∈ {o2, o3, o4} (the reachable set used for ranking).
pub fn variants(c: &Candidate) -> [Ivs; 4] {
    [
        ivs_from_words(c.o1, c.o3),
        ivs_from_words(c.o2, c.o3),
        ivs_from_words(c.o2, c.o4),
        ivs_from_words(c.o1, c.o2),
    ]
}

/// Best IV a candidate can realize, by a metric `(ivs, nature) -> sort key`.
pub fn best_possible_iv<K: Ord, M: Fn(Ivs, u8) -> K>(c: &Candidate, metric: &M) -> Ivs {
    variants(c)
        .into_iter()
        .max_by_key(|&iv| metric(iv, c.nature))
        .unwrap()
}

/// Exact offline IVs under a deterministic trigger with thresholds (ta, tb_lo, tb_hi).
pub fn predict_env_exact(c: &Candidate, ta: u32, tb_lo: u32, tb_hi: u32) -> Ivs {
    let outs = [c.o1, c.o2, c.o3, c.o4];
    let iv1 = outs[if c.iters >= ta { 1 } else { 0 }];
    let iv2 = outs[1 + (c.iters >= tb_lo) as usize + (c.iters >= tb_hi) as usize];
    ivs_from_words(iv1, iv2)
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::enumerate::{enum_candidate, Filter};

    #[test]
    fn best_picks_max_n31() {
        let f = Filter::new(
            51376,
            36462,
            &(0..12).collect::<Vec<_>>(),
            &(0..25).collect::<Vec<_>>(),
        );
        let c = enum_candidate(0x0002_D02A, &f).unwrap();
        let metric = |iv: Ivs, _n: u8| iv.n31();
        let best = best_possible_iv(&c, &metric);
        // best must be at least as good as any single variant
        let max_n31 = variants(&c).iter().map(|iv| iv.n31()).max().unwrap();
        assert_eq!(best.n31(), max_n31);
    }
}
