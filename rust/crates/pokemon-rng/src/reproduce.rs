//! Pure offset math for emulator reproduction: the lattice of probe offsets.
//!
//! Writing `rewind(G, o)` makes the encounter generate from exactly `G` iff the
//! realized offset `R(o) == o`. The reproducing offsets sit on a ~`lattice`-spaced
//! grid at/below the dominant offset (one per overworld step). `probe_order`
//! enumerates those offsets best-first; the emulator layer measures each.

/// Offsets to try, best-first, for reproducing at dominant offset `off0`.
pub fn probe_order(off0: i32, lattice: i32, depth: i32, jitter: i32, window: i32) -> Vec<i32> {
    let mut order: Vec<i32> = Vec::new();
    let push = |o: i32, order: &mut Vec<i32>| {
        if o >= 0 && !order.contains(&o) {
            order.push(o);
        }
    };
    for k in 0..=depth {
        let base = off0 - lattice * k;
        for j in 0..=jitter {
            if j == 0 {
                push(base, &mut order);
            } else {
                push(base + j, &mut order);
                push(base - j, &mut order);
            }
        }
    }
    let mut o = off0;
    while o >= off0 - window {
        push(o, &mut order);
        o -= 1;
    }
    order
}

/// Defaults matching the Python `reproduce()` (lattice 10, depth 7, jitter 2).
pub fn probe_order_default(off0: i32) -> Vec<i32> {
    probe_order(off0, 10, 7, 2, 0)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn grass_lattice_hits_known_fixed_points() {
        // off0=71 -> lattice points include 62/52/42 (71-9.., +/-2 jitter covers them)
        let order = probe_order_default(71);
        for fp in [71, 62, 52, 42] {
            assert!(order.contains(&fp), "missing fixed point {fp} in {order:?}");
        }
        // dominant offset is tried first
        assert_eq!(order[0], 71);
        // no negatives, no dups
        assert!(order.iter().all(|&o| o >= 0));
        let mut sorted = order.clone();
        sorted.sort_unstable();
        sorted.dedup();
        assert_eq!(sorted.len(), order.len());
    }

    #[test]
    fn cave_lattice_covers_spacing_9() {
        // off0=240 -> 231 and 222 are spacing-9 deviations; jitter=2 reaches them
        let order = probe_order_default(240);
        for fp in [240, 231, 222] {
            assert!(order.contains(&fp), "missing {fp}");
        }
    }
}
