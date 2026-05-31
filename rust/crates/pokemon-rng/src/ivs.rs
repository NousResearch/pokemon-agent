//! Gen-3 IV decode and the 6-IV value type.

/// Six IVs in the canonical order (HP, Atk, Def, Spe, SpA, SpD), each 0..=31.
#[derive(Clone, Copy, PartialEq, Eq, Debug, Default, Hash)]
pub struct Ivs {
    pub hp: u8,
    pub atk: u8,
    pub def: u8,
    pub spe: u8,
    pub spa: u8,
    pub spd: u8,
}

impl Ivs {
    pub fn as_tuple(self) -> (u8, u8, u8, u8, u8, u8) {
        (self.hp, self.atk, self.def, self.spe, self.spa, self.spd)
    }

    pub fn as_array(self) -> [u8; 6] {
        [self.hp, self.atk, self.def, self.spe, self.spa, self.spd]
    }

    pub fn total(self) -> u32 {
        self.as_array().iter().map(|&x| x as u32).sum()
    }

    /// Number of perfect (==31) IVs.
    pub fn n31(self) -> u32 {
        self.as_array().iter().filter(|&&x| x == 31).count() as u32
    }
}

/// Decode the 32-bit packed IV word (the Misc-substructure layout): HP[0:5],
/// Atk[5:10], Def[10:15], Spe[15:20], SpA[20:25], SpD[25:30], egg bit 30, ability 31.
pub fn decode_ivs(iv_word: u32) -> Ivs {
    Ivs {
        hp: (iv_word & 0x1F) as u8,
        atk: ((iv_word >> 5) & 0x1F) as u8,
        def: ((iv_word >> 10) & 0x1F) as u8,
        spe: ((iv_word >> 15) & 0x1F) as u8,
        spa: ((iv_word >> 20) & 0x1F) as u8,
        spd: ((iv_word >> 25) & 0x1F) as u8,
    }
}

/// Build IVs from the two 15-bit RNG IV words used during wild generation:
/// iv1 packs HP/Atk/Def (5 bits each), iv2 packs Spe/SpA/SpD.
pub fn ivs_from_words(iv1: u16, iv2: u16) -> Ivs {
    Ivs {
        hp: (iv1 & 31) as u8,
        atk: ((iv1 >> 5) & 31) as u8,
        def: ((iv1 >> 10) & 31) as u8,
        spe: (iv2 & 31) as u8,
        spa: ((iv2 >> 5) & 31) as u8,
        spd: ((iv2 >> 10) & 31) as u8,
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn iv_word_bit_layout() {
        // Each field set to its max individually round-trips to the right slot.
        assert_eq!(decode_ivs(31).hp, 31);
        assert_eq!(decode_ivs(31 << 5).atk, 31);
        assert_eq!(decode_ivs(31 << 25).spd, 31);
        let all = 0x3FFF_FFFFu32; // 30 low bits set
        assert_eq!(decode_ivs(all).as_array(), [31, 31, 31, 31, 31, 31]);
    }

    #[test]
    fn from_words_matches_decode() {
        // iv1 -> hp/atk/def, iv2 -> spe/spa/spd
        let iv = ivs_from_words(0x7FFF, 0x7FFF);
        assert_eq!(iv.as_array(), [31, 31, 31, 31, 31, 31]);
        assert_eq!(ivs_from_words(0, 0).total(), 0);
    }
}
