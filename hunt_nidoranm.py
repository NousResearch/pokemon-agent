"""Offline-only (hybrid) physical shiny Nidoran-male hunt — Route 3, LeafGreen.

Predicts IVs EXACTLY offline (no emulator for non-boundary candidates) via the
deterministic-trigger VBlank model; the emulator is used only for the rare
boundary candidates and one reproduction of the winner. See hunt_hybrid.py.

    distrobox enter devbox -- .venv-gba/bin/python hunt_nidoranm.py
"""
from hunt_hybrid import run_hybrid_hunt
from pokemon_agent.wild_enumerate import n31

STATE = "roms/leafgreen_route3_grass.ss1"


def phys_viable(nat):
    inc, dec = nat // 5, nat % 5
    return not ((dec == 0 and inc != 0) or (dec == 2 and inc != 2))


def metric(iv, nat):
    # physical Nidoking: Atk31 & Spe31 first, then #31, ideal nature, then bulk
    hp, atk, df, spe, spa, spd = iv
    return ((atk == 31) + (spe == 31), n31(iv), 1 if nat in (3, 13) else 0, hp + df + spd)


if __name__ == "__main__":
    run_hybrid_hunt(32, (10,), STATE, metric, phys_viable,
                    "cache_nidoranm.npz", "roms/leafgreen_shiny_nidoranm.ss1",
                    label="Nidoran-male")
