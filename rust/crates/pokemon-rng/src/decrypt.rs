//! Gen-3 Pokémon data decryption: XOR by `pid^otid`, then unscramble the four
//! 12-byte substructures from their `pid % 24` order into canonical G,A,E,M.

use crate::ivs::{decode_ivs, Ivs};

pub const ENCRYPTED_BLOCK_SIZE: usize = 48;
pub const SUBSTRUCT_SIZE: usize = 12;

/// Substructure orderings indexed by `pid % 24`. Letters: G,A,E,M.
pub const SUBSTRUCTURE_ORDER: [&str; 24] = [
    "GAEM", "GAME", "GEAM", "GEMA", "GMAE", "GMEA", "AGEM", "AGME", "AEGM", "AEMG", "AMGE", "AMEG",
    "EGAM", "EGMA", "EAGM", "EAMG", "EMGA", "EMAG", "MGAE", "MGEA", "MAGE", "MAEG", "MEGA", "MEAG",
];

#[inline]
fn gaem_index(letter: u8) -> usize {
    match letter {
        b'G' => 0,
        b'A' => 1,
        b'E' => 2,
        b'M' => 3,
        _ => unreachable!("substructure letter must be one of GAEM"),
    }
}

/// Decrypt the 48-byte encrypted block and reorder it into canonical G,A,E,M.
pub fn decrypt_block(block: &[u8], pid: u32, otid: u32) -> [u8; ENCRYPTED_BLOCK_SIZE] {
    assert_eq!(block.len(), ENCRYPTED_BLOCK_SIZE, "block must be 48 bytes");
    let key = pid ^ otid;
    let mut dec = [0u8; ENCRYPTED_BLOCK_SIZE];
    for i in (0..ENCRYPTED_BLOCK_SIZE).step_by(4) {
        let word = u32::from_le_bytes([block[i], block[i + 1], block[i + 2], block[i + 3]]);
        dec[i..i + 4].copy_from_slice(&(word ^ key).to_le_bytes());
    }
    let order = SUBSTRUCTURE_ORDER[(pid % 24) as usize].as_bytes();
    let mut canonical = [0u8; ENCRYPTED_BLOCK_SIZE];
    for (stored_idx, &letter) in order.iter().enumerate() {
        let dst = gaem_index(letter);
        let src = stored_idx * SUBSTRUCT_SIZE;
        let dstoff = dst * SUBSTRUCT_SIZE;
        canonical[dstoff..dstoff + SUBSTRUCT_SIZE].copy_from_slice(&dec[src..src + SUBSTRUCT_SIZE]);
    }
    canonical
}

/// Pull the IV word out of a canonical (G,A,E,M) decrypted block (Misc +4).
pub fn ivs_from_decrypted(canonical: &[u8]) -> Ivs {
    let misc = 3 * SUBSTRUCT_SIZE;
    let iv_word = u32::from_le_bytes([
        canonical[misc + 4],
        canonical[misc + 5],
        canonical[misc + 6],
        canonical[misc + 7],
    ]);
    decode_ivs(iv_word)
}

/// Parse a 100-byte `gEnemyParty[0]` mon struct into (pid, ivs, species).
/// The encrypted 48-byte block sits at offset 0x20; species is the first field
/// of the Growth substructure.
pub fn parse_enemy(mon: &[u8]) -> Option<(u32, Ivs, u16)> {
    if mon.len() < 0x20 + ENCRYPTED_BLOCK_SIZE {
        return None;
    }
    let pid = u32::from_le_bytes([mon[0], mon[1], mon[2], mon[3]]);
    let otid = u32::from_le_bytes([mon[4], mon[5], mon[6], mon[7]]);
    let dec = decrypt_block(&mon[0x20..0x20 + ENCRYPTED_BLOCK_SIZE], pid, otid);
    let species = u16::from_le_bytes([dec[0], dec[1]]);
    Some((pid, ivs_from_decrypted(&dec), species))
}

#[cfg(test)]
mod tests {
    use super::*;

    // Encrypt = inverse of decrypt: scramble canonical -> stored order, XOR by key.
    fn encrypt_block(canonical: &[u8; 48], pid: u32, otid: u32) -> [u8; 48] {
        let order = SUBSTRUCTURE_ORDER[(pid % 24) as usize].as_bytes();
        let mut stored = [0u8; 48];
        for (stored_idx, &letter) in order.iter().enumerate() {
            let src = gaem_index(letter) * SUBSTRUCT_SIZE;
            let dst = stored_idx * SUBSTRUCT_SIZE;
            stored[dst..dst + SUBSTRUCT_SIZE]
                .copy_from_slice(&canonical[src..src + SUBSTRUCT_SIZE]);
        }
        let key = pid ^ otid;
        let mut enc = [0u8; 48];
        for i in (0..48).step_by(4) {
            let w = u32::from_le_bytes([stored[i], stored[i + 1], stored[i + 2], stored[i + 3]]);
            enc[i..i + 4].copy_from_slice(&(w ^ key).to_le_bytes());
        }
        enc
    }

    #[test]
    fn decrypt_roundtrip_and_ivs() {
        let pid = 0x6743_2199u32;
        let otid = 0x8E6E_C8B0u32;
        let mut canonical = [0u8; 48];
        // species (Growth +0) = 35 (Clefairy)
        canonical[0..2].copy_from_slice(&35u16.to_le_bytes());
        // IV word (Misc +4) packs 31/0/31/0/31/0
        let iv_word: u32 = 31 | (31 << 10) | (31 << 20);
        canonical[3 * 12 + 4..3 * 12 + 8].copy_from_slice(&iv_word.to_le_bytes());
        let enc = encrypt_block(&canonical, pid, otid);
        let dec = decrypt_block(&enc, pid, otid);
        assert_eq!(dec, canonical);
        let iv = ivs_from_decrypted(&dec);
        assert_eq!(iv.as_array(), [31, 0, 31, 0, 31, 0]);
        // parse_enemy end-to-end
        let mut mon = vec![0u8; 100];
        mon[0..4].copy_from_slice(&pid.to_le_bytes());
        mon[4..8].copy_from_slice(&otid.to_le_bytes());
        mon[0x20..0x20 + 48].copy_from_slice(&enc);
        let (p, ivs, sp) = parse_enemy(&mon).unwrap();
        assert_eq!((p, sp), (pid, 35));
        assert_eq!(ivs.as_array(), [31, 0, 31, 0, 31, 0]);
    }
}
