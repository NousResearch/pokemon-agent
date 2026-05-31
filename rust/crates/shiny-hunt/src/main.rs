//! `shiny-hunt` — enumerate / rank / reproduce shiny Gen-3 wild encounters.
//!
//! Run from the repo root (so `roms/` and `cache_*.npz` resolve), in the devbox:
//!   distrobox enter devbox -- bash -lc 'cd <repo> && rust/target/release/shiny-hunt hunt clefairy'

mod hunt;
mod species;

use std::path::Path;

use clap::{Parser, Subcommand};
use pokemon_emu::{reproduce, Emu, Trigger};

#[derive(Parser)]
#[command(
    name = "shiny-hunt",
    about = "Shiny Gen-3 (LeafGreen) wild-encounter hunter"
)]
struct Cli {
    #[command(subcommand)]
    cmd: Cmd,
}

#[derive(Subcommand)]
enum Cmd {
    /// List the configured species.
    List,
    /// Enumerate the full 2^32 space for a species and write its `.npz` cache.
    Enumerate { species: String },
    /// Full unified hunt: rank offline, realize the top-N, save the best state.
    Hunt { species: String },
    /// Reproduce a single generation-seed G (hex) and print its true IVs.
    Reproduce {
        species: String,
        #[arg(value_parser = parse_hex)]
        g: u32,
    },
}

fn parse_hex(s: &str) -> Result<u32, String> {
    let s = s.trim_start_matches("0x");
    u32::from_str_radix(s, 16).map_err(|e| e.to_string())
}

fn main() {
    let cli = Cli::parse();
    match cli.cmd {
        Cmd::List => {
            for s in species::SPECIES {
                println!(
                    "{:<10} id={:<4} slots={:?} topn={}",
                    s.name, s.id, s.slots, s.topn
                );
            }
        }
        Cmd::Enumerate { species } => {
            let sp = resolve(&species);
            hunt::load_or_enumerate(sp);
        }
        Cmd::Hunt { species } => {
            let sp = resolve(&species);
            hunt::run_unified_hunt(sp);
        }
        Cmd::Reproduce { species, g } => {
            let sp = resolve(&species);
            let combo = &sp.combos[0];
            let rom = "roms/Pokemon - LeafGreen Version (USA).gba";
            let mut emu =
                Emu::with_rom(Path::new(rom), Path::new(combo.state)).unwrap_or_else(|e| fatal(&e));
            // Recover the candidate's pid offline so reproduce can verify it.
            let pid = pokemon_rng::generate_wild(g, 0).pid;
            let t = Trigger {
                axis: combo.axis,
                hold: combo.hold,
                rel: combo.rel,
                cap: 140,
                settle: 20,
            };
            match reproduce(&mut emu, g, pid, Some(sp.id), t, combo.off0, 400) {
                Some((pid, ivs, species_id, r)) => println!(
                    "G=0x{g:08X} pid=0x{pid:08X} species={species_id} IVs={:?} #31={} @R={r}",
                    ivs.as_array(),
                    ivs.n31()
                ),
                None => println!("G=0x{g:08X}: not reproducible at {}", combo.state),
            }
        }
    }
}

fn resolve(name: &str) -> &'static hunt::Species {
    species::find(name).unwrap_or_else(|| {
        fatal(&format!(
            "unknown species '{name}'; known: {}",
            species::SPECIES
                .iter()
                .map(|s| s.name)
                .collect::<Vec<_>>()
                .join(", ")
        ))
    })
}

fn fatal(msg: &str) -> ! {
    eprintln!("error: {msg}");
    std::process::exit(1);
}
