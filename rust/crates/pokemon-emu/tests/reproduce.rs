//! Phase-2 integration: `reproduce()` pins an exact gen-seed at any encounter type
//! — low-offset grass (~71) and high-offset Mt. Moon cave (~240) — by measuring the
//! realized offset, not guessing. Regression guard for the cave 0/60 bug. Needs the
//! ROM + states + caches at the repo root; run in the devbox from rust/:
//!   cargo test -p pokemon-emu --test reproduce -- --nocapture

use std::path::PathBuf;

use pokemon_emu::{reproduce, Emu, Trigger};
use pokemon_rng::{cache, generate_wild, predict::variants};

fn repo_root() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../../..")
}

fn run_case(state_rel: &str, cache_rel: &str, species: u16, off0: i32) {
    let root = repo_root();
    let rom = root.join("roms/Pokemon - LeafGreen Version (USA).gba");
    let state = root.join(state_rel);
    let cache_path = root.join(cache_rel);
    if !rom.exists() || !state.exists() || !cache_path.exists() {
        eprintln!("skip {state_rel}: rom/state/cache missing");
        return;
    }
    let mut emu = Emu::with_rom(&rom, &state).expect("load rom+state");
    let set = cache::load(&cache_path).expect("load cache");
    let t = Trigger::default();
    let n = 10usize;
    let mut realized = 0;
    for i in 0..n.min(set.len()) {
        let c = set.candidate(i);
        let Some((pid, ivs, sp, _r)) = reproduce(&mut emu, c.g, c.pid, Some(species), t, off0, 400)
        else {
            continue;
        };
        realized += 1;
        // The reproduced encounter IS exactly G: pid/species match a fresh offline
        // generation, and the true IVs are one of G's four timing-variants.
        assert_eq!(sp, species);
        assert_eq!(pid, c.pid);
        assert_eq!(pid, generate_wild(c.g, 0).pid);
        assert!(
            variants(&c).contains(&ivs),
            "ivs {:?} not a variant of G",
            ivs.as_array()
        );
    }
    eprintln!("{state_rel}: reproduced {realized}/{}", n.min(set.len()));
    assert!(realized >= 6, "only reproduced {realized} at {state_rel}");
}

#[test]
fn reproduce_grass_low_offset() {
    run_case(
        "roms/leafgreen_route3_grass.ss1",
        "cache_spearow.npz",
        21,
        71,
    );
}

#[test]
fn reproduce_cave_high_offset() {
    run_case("roms/leafgreen_mtmoon2.ss1", "cache_clefairy.npz", 35, 240);
}
