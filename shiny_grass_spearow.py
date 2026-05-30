"""Offline-only (hybrid) physical shiny Spearow hunt — Route 3, LeafGreen.

Predicts IVs EXACTLY offline (no emulator for non-boundary candidates) via the
deterministic-trigger VBlank model; the emulator is used only for the rare
boundary candidates and one reproduction of the winner. Spearow is slots 0/2/6
(~35%). See hunt_hybrid.py.

    distrobox enter devbox -- .venv-gba/bin/python shiny_grass_spearow.py
"""
from hunt_hybrid import run_hybrid_hunt
from pokemon_agent.wild_enumerate import n31

STATE = "roms/leafgreen_route3_grass.ss1"


def phys_viable(nat):
    inc, dec = nat // 5, nat % 5
    return not ((dec == 0 and inc != 0) or (dec == 2 and inc != 2))


def metric(iv, nat):
    # fast physical Fearow: Atk31 & Spe31 first, then #31, ideal nature, then bulk
    hp, atk, df, spe, spa, spd = iv
    return ((atk == 31) + (spe == 31), n31(iv), 1 if nat in (3, 13) else 0, hp + df + spd)


if __name__ == "__main__":
    run_hybrid_hunt(21, (0, 2, 6), STATE, metric, phys_viable,
                    "cache_spearow.npz", "roms/leafgreen_shiny_spearow.ss1",
                    label="Spearow")
