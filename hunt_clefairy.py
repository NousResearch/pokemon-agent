"""Shiny Clefairy hunt — Mt. Moon (slot 7), LeafGreen. Uses the unified hunt.

    distrobox enter devbox -- .venv-gba/bin/python hunt_clefairy.py
"""
import time

from hunt_hybrid import run_unified_hunt
from pokemon_agent.wild_enumerate import n31

STATE = "roms/leafgreen_mtmoon2.ss1"
# Dominant trigger offset at this tile is 240; reproduce() self-corrects the rare
# 231/222 drift, so a single off0 is enough.
COMBOS = [("mtmoon2/LR2:1", STATE, "LR", 2, 1, 240)]


def allow_all(nat):
    return True


def metric(iv, nat):
    # Clefable is a flexible special tank: maximise total perfect IVs, then the
    # special-bulk stats (HP, SpA, SpD).
    return (n31(iv), iv[0] + iv[4] + iv[5], iv[3])


if __name__ == "__main__":
    t0 = time.time()
    realized, best = run_unified_hunt(
        35, (7,), metric, allow_all, "cache_clefairy.npz",
        "roms/leafgreen_shiny_clefairy.ss1", combos=COMBOS, topn=60, label="Clefairy")
    print("\n=== TOTAL CLEFAIRY HUNT TIME: %.1fs ===" % (time.time() - t0), flush=True)
