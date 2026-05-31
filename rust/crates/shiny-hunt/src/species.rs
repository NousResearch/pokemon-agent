//! Per-species hunt configuration (slots, nature filter, ranking metric, combos).

use pokemon_emu::Axis;
use pokemon_rng::Ivs;

use crate::hunt::{Combo, Species};

const G3: &str = "roms/leafgreen_route3_grass.ss1";
const SS5: &str = "roms/Pokemon - LeafGreen Version (USA).ss5";

/// Route 3 grass combos spanning the achievable trigger-offset range.
static GRASS_COMBOS: &[Combo] = &[
    Combo {
        label: "g3/LR2:1",
        state: G3,
        axis: Axis::LR,
        hold: 2,
        rel: 1,
        off0: 71,
    },
    Combo {
        label: "g3/LR1:1",
        state: G3,
        axis: Axis::LR,
        hold: 1,
        rel: 1,
        off0: 98,
    },
    Combo {
        label: "ss5/LR2:1",
        state: SS5,
        axis: Axis::LR,
        hold: 2,
        rel: 1,
        off0: 59,
    },
    Combo {
        label: "ss5/LR1:1",
        state: SS5,
        axis: Axis::LR,
        hold: 1,
        rel: 1,
        off0: 98,
    },
    Combo {
        label: "ss5/LR3:1",
        state: SS5,
        axis: Axis::LR,
        hold: 3,
        rel: 1,
        off0: 100,
    },
    Combo {
        label: "env01",
        state: "roms/envs/route3_env01.ss1",
        axis: Axis::LR,
        hold: 2,
        rel: 1,
        off0: 39,
    },
    Combo {
        label: "env02",
        state: "roms/envs/route3_env02.ss1",
        axis: Axis::LR,
        hold: 2,
        rel: 1,
        off0: 29,
    },
    Combo {
        label: "env03",
        state: "roms/envs/route3_env03.ss1",
        axis: Axis::LR,
        hold: 2,
        rel: 1,
        off0: 19,
    },
];

/// Mt. Moon cave (Clefairy slot 7), dominant offset 240.
static MTMOON_COMBOS: &[Combo] = &[Combo {
    label: "mtmoon2/LR2:1",
    state: "roms/leafgreen_mtmoon2.ss1",
    axis: Axis::LR,
    hold: 2,
    rel: 1,
    off0: 240,
}];

fn allow_all(_n: u8) -> bool {
    true
}

/// Physical-viable natures: exclude -Atk and -Spe (unless neutral in that stat).
fn phys_grass(n: u8) -> bool {
    let (inc, dec) = (n / 5, n % 5);
    !((dec == 0 && inc != 0) || (dec == 2 && inc != 2))
}

fn n31(iv: Ivs) -> i64 {
    iv.n31() as i64
}

/// Clefable special tank: total 31s, then HP+SpA+SpD, then Spe.
fn clefairy_metric(iv: Ivs, _n: u8) -> [i64; 4] {
    [
        n31(iv),
        iv.hp as i64 + iv.spa as i64 + iv.spd as i64,
        iv.spe as i64,
        0,
    ]
}

/// Physical sweeper: Atk31+Spe31 first, then total 31s, then bulk.
fn nidoran_metric(iv: Ivs, _n: u8) -> [i64; 4] {
    let dual = (iv.atk == 31) as i64 + (iv.spe == 31) as i64;
    [
        dual,
        n31(iv),
        iv.hp as i64 + iv.def as i64 + iv.spd as i64,
        0,
    ]
}

/// Fast physical Fearow: Atk31+Spe31, total 31s, ideal nature (Naughty/Hasty), bulk.
fn spearow_metric(iv: Ivs, n: u8) -> [i64; 4] {
    let dual = (iv.atk == 31) as i64 + (iv.spe == 31) as i64;
    let good_nat = (n == 3 || n == 13) as i64;
    [
        dual,
        n31(iv),
        good_nat,
        iv.hp as i64 + iv.def as i64 + iv.spd as i64,
    ]
}

pub static SPECIES: &[Species] = &[
    Species {
        name: "clefairy",
        id: 35,
        slots: &[7],
        phys: allow_all,
        metric: clefairy_metric,
        cache: "cache_clefairy.npz",
        out_state: "roms/leafgreen_shiny_clefairy.ss1",
        combos: MTMOON_COMBOS,
        topn: 60,
    },
    Species {
        name: "spearow",
        id: 21,
        slots: &[0, 2, 6],
        phys: phys_grass,
        metric: spearow_metric,
        cache: "cache_spearow.npz",
        out_state: "roms/leafgreen_shiny_spearow.ss1",
        combos: GRASS_COMBOS,
        topn: 120,
    },
    Species {
        name: "nidoranm",
        id: 32,
        slots: &[10],
        phys: phys_grass,
        metric: nidoran_metric,
        cache: "cache_nidoranm.npz",
        out_state: "roms/leafgreen_shiny_nidoranm.ss1",
        combos: GRASS_COMBOS,
        topn: 120,
    },
];

pub fn find(name: &str) -> Option<&'static Species> {
    SPECIES.iter().find(|s| s.name == name)
}
