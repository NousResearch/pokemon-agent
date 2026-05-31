//! The unified wild-shiny hunt: enumerate offline → rank by each candidate's
//! best-possible IV → realize the top-N by reproducing them in the emulator and
//! reading their TRUE IVs → deliver the best as a catchable save state. Ports
//! `hunt_hybrid.run_unified_hunt` + the per-species drivers.

use std::collections::HashMap;
use std::path::Path;
use std::time::Instant;

use pokemon_emu::{reproduce, Axis, Emu, Trigger};
use pokemon_rng::predict::best_possible_iv;
use pokemon_rng::{cache, enumerate, Candidate, Filter, Ivs};

pub const TID: u16 = 51376;
pub const SID: u16 = 36462;
const ROM: &str = "roms/Pokemon - LeafGreen Version (USA).gba";

/// Sort key: higher is better. Four i64 lanes cover every per-species metric.
pub type Metric = fn(Ivs, u8) -> [i64; 4];
pub type PhysViable = fn(u8) -> bool;

/// A (state, jiggle, dominant-offset) combo to realize candidates under.
pub struct Combo {
    pub label: &'static str,
    pub state: &'static str,
    pub axis: Axis,
    pub hold: u32,
    pub rel: u32,
    pub off0: i32,
}

pub struct Species {
    pub name: &'static str,
    pub id: u16,
    pub slots: &'static [u8],
    pub phys: PhysViable,
    pub metric: Metric,
    pub cache: &'static str,
    pub out_state: &'static str,
    pub combos: &'static [Combo],
    pub topn: usize,
}

/// One realized result.
pub struct Realized {
    pub cand: Candidate,
    pub ivs: Ivs,
    pub combo: &'static str,
    pub off: u32,
}

fn trigger_for(c: &Combo) -> Trigger {
    Trigger {
        axis: c.axis,
        hold: c.hold,
        rel: c.rel,
        cap: 140,
        settle: 20,
    }
}

/// Load the candidate cache, or enumerate the full 2^32 space and cache it.
pub fn load_or_enumerate(sp: &Species) -> Vec<Candidate> {
    if Path::new(sp.cache).exists() {
        let set = cache::load(sp.cache).expect("load cache");
        println!("[{}] loaded {} cached candidates", sp.name, set.len());
        return (0..set.len()).map(|i| set.candidate(i)).collect();
    }
    let natures: Vec<u8> = (0..25).collect();
    let f = Filter::new(TID, SID, sp.slots, &natures);
    let t0 = Instant::now();
    let cands = enumerate(&f);
    println!(
        "[{}] enumerated {} candidates in {:.1}s",
        sp.name,
        cands.len(),
        t0.elapsed().as_secs_f64()
    );
    cache::save(sp.cache, &cands, sp.id as i64, TID as i64, SID as i64).expect("save cache");
    cands
}

/// Run the unified hunt for `sp`; realize top-N, save the best, return results.
pub fn run_unified_hunt(sp: &Species) -> Vec<Realized> {
    let t0 = Instant::now();
    let cands = load_or_enumerate(sp);

    let metric = sp.metric;
    let mut rows: Vec<(Candidate, [i64; 4])> = cands
        .iter()
        .filter(|c| (sp.phys)(c.nature))
        .map(|c| {
            let bi = best_possible_iv(c, &|iv: Ivs, n: u8| metric(iv, n));
            (*c, metric(bi, c.nature))
        })
        .collect();
    rows.sort_by(|a, b| b.1.cmp(&a.1));
    println!(
        "[{}] ranked {} physical candidates offline in {:.1}s; realizing top {}...",
        sp.name,
        rows.len(),
        t0.elapsed().as_secs_f64(),
        sp.topn
    );

    // One emulator per distinct combo state, reused across candidates.
    let mut emus: HashMap<&str, Emu> = HashMap::new();
    for combo in sp.combos {
        if !emus.contains_key(combo.state) && Path::new(combo.state).exists() {
            match Emu::with_rom(Path::new(ROM), Path::new(combo.state)) {
                Ok(e) => {
                    emus.insert(combo.state, e);
                }
                Err(e) => eprintln!("warning: {}: {e}", combo.state),
            }
        }
    }

    let t1 = Instant::now();
    let mut realized: Vec<Realized> = Vec::new();
    for (c, _) in rows.iter().take(sp.topn) {
        let mut best: Option<Realized> = None;
        for combo in sp.combos {
            let Some(emu) = emus.get_mut(combo.state) else {
                continue;
            };
            if let Some((_pid, ivs, _sp, r)) = reproduce(
                emu,
                c.g,
                c.pid,
                Some(sp.id),
                trigger_for(combo),
                combo.off0,
                400,
            ) {
                let better = best
                    .as_ref()
                    .map(|b| metric(ivs, c.nature) > metric(b.ivs, c.nature))
                    .unwrap_or(true);
                if better {
                    best = Some(Realized {
                        cand: *c,
                        ivs,
                        combo: combo.label,
                        off: r,
                    });
                }
            }
        }
        if let Some(b) = best {
            realized.push(b);
        }
    }
    realized.sort_by(|a, b| metric(b.ivs, b.cand.nature).cmp(&metric(a.ivs, a.cand.nature)));
    println!(
        "[{}] realized {}/{} in {:.1}s; best:",
        sp.name,
        realized.len(),
        sp.topn,
        t1.elapsed().as_secs_f64()
    );
    for r in realized.iter().take(10) {
        println!(
            "  G=0x{:08X} nat={:2} IVs={:?} #31={} via {}",
            r.cand.g,
            r.cand.nature,
            r.ivs.as_array(),
            r.ivs.n31(),
            r.combo
        );
    }

    // Re-realize the winner and save the catchable state.
    if let Some(winner) = realized.first() {
        let combo = sp.combos.iter().find(|c| c.label == winner.combo).unwrap();
        if let Some(emu) = emus.get_mut(combo.state) {
            if let Some((_p, ivs, _s, _r)) = reproduce(
                emu,
                winner.cand.g,
                winner.cand.pid,
                Some(sp.id),
                trigger_for(combo),
                winner.off as i32,
                400,
            ) {
                if ivs == winner.ivs && emu.save_ss1(Path::new(sp.out_state)) {
                    println!(
                        "[{}] BEST saved -> {} ({:.1}s total)",
                        sp.name,
                        sp.out_state,
                        t0.elapsed().as_secs_f64()
                    );
                }
            }
        }
    }
    realized
}
