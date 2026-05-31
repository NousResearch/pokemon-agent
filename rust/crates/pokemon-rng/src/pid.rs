//! PID-derived quantities: nature and the Gen-3 shiny check.

pub const NUM_NATURES: u32 = 25;
pub const SHINY_THRESHOLD: u16 = 8;

/// Nature index 0..=24 from a PID.
#[inline]
pub fn nature_of(pid: u32) -> u8 {
    (pid % NUM_NATURES) as u8
}

/// Gen-3 shiny value: `TID ^ SID ^ (PID>>16) ^ (PID&0xFFFF)`, masked to 16 bits.
#[inline]
pub fn shiny_value(pid: u32, tid: u16, sid: u16) -> u16 {
    ((tid ^ sid) as u32 ^ (pid >> 16) ^ (pid & 0xFFFF)) as u16
}

/// Shiny iff the shiny value is below the threshold (8 ⇒ 1/8192).
#[inline]
pub fn is_shiny(pid: u32, tid: u16, sid: u16) -> bool {
    shiny_value(pid, tid, sid) < SHINY_THRESHOLD
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn nature_range() {
        for pid in [0u32, 24, 25, 0xFFFF_FFFF, 0x6743_2199] {
            assert!((nature_of(pid) as u32) < NUM_NATURES);
        }
        assert_eq!(nature_of(0), 0);
        assert_eq!(nature_of(26), 1);
    }

    #[test]
    fn shiny_self_otid() {
        // shiny value = (tid^sid) ^ (pid>>16) ^ (pid&0xFFFF); 0 when high=xb, low=0.
        let (tid, sid) = (51376u16, 36462u16);
        let xb = tid ^ sid;
        let pid = (xb as u32) << 16; // high half = xb, low half = 0
        assert_eq!(shiny_value(pid, tid, sid), 0);
        assert!(is_shiny(pid, tid, sid));
        assert!(!is_shiny(pid ^ 0x10, tid, sid)); // perturb -> not shiny
    }
}
