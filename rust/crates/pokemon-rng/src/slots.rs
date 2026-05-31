//! Land encounter-slot selection.

/// Cumulative percent thresholds; per-slot probabilities 20,20,10,10,10,10,5,5,4,4,1,1.
pub const SLOT_CUMULATIVE: [u8; 12] = [20, 40, 50, 60, 70, 80, 85, 90, 94, 98, 99, 100];

/// Map a `Random()>>16` value to a land encounter-slot index (0..=11).
#[inline]
pub fn slot_index(rand16: u16) -> u8 {
    let r = (rand16 % 100) as u8;
    for (i, &thr) in SLOT_CUMULATIVE.iter().enumerate() {
        if r < thr {
            return i as u8;
        }
    }
    11
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn boundaries() {
        assert_eq!(slot_index(0), 0);
        assert_eq!(slot_index(19), 0);
        assert_eq!(slot_index(20), 1);
        assert_eq!(slot_index(39), 1);
        assert_eq!(slot_index(40), 2);
        assert_eq!(slot_index(98), 10);
        assert_eq!(slot_index(99), 11);
        // wraps at 100
        assert_eq!(slot_index(100), 0);
        assert_eq!(slot_index(119), 0);
    }
}
