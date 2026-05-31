//! Phase-0 gate: drive libmgba from Rust and reproduce the golden encounter —
//! write seed 0x55FF2959 on the Route 3 grass state → Hasty shiny Spearow
//! 31/31/17/31/19/31. Requires the ROM + save state at the repo root; run from
//! the repo root in the devbox:
//!   cargo test -p pokemon-emu --test golden -- --nocapture

use std::path::PathBuf;

use pokemon_emu::{jiggle_trigger, Emu, Trigger};

fn repo_root() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../../..")
}

#[test]
fn hasty_spearow_golden() {
    let root = repo_root();
    let rom = root.join("roms/Pokemon - LeafGreen Version (USA).gba");
    let state = root.join("roms/leafgreen_route3_grass.ss1");
    if !rom.exists() || !state.exists() {
        eprintln!("skip: ROM or grass state not present");
        return;
    }
    let mut emu = Emu::with_rom(&rom, &state).expect("load rom+state");
    let res = jiggle_trigger(&mut emu, 0x55FF_2959, Trigger::default());
    let (pid, ivs, species) = res.expect("golden seed should trigger an encounter");
    eprintln!(
        "golden: pid=0x{pid:08X} species={species} ivs={:?}",
        ivs.as_array()
    );
    assert_eq!(species, 21, "expected Spearow (21)");
    assert_eq!(
        ivs.as_array(),
        [31, 31, 17, 31, 19, 31],
        "expected Hasty 31/31/17/31/19/31"
    );
}
