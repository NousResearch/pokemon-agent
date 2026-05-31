"""reproduce() pins an exact generation-seed at ANY encounter type — a low-offset
grass state (Route 3, ~71) and the high-offset Mt. Moon cave (~240) — by measuring
the realized offset and homing onto the lattice of reproducing offsets, NOT by
guessing. This is the regression guard for the cave 0/60 reproduction bug.
Requires mgba + cached candidate sets; runs in the devbox.
"""
import os

import pytest

CASES = [
    # (state, cache, species, off0) — grass (low offset) and cave (high offset).
    ("roms/leafgreen_route3_grass.ss1", "cache_spearow.npz", 21, 71),
    ("roms/leafgreen_mtmoon2.ss1", "cache_clefairy.npz", 35, 240),
]


@pytest.mark.emulator
@pytest.mark.slow
@pytest.mark.parametrize("state,cache,species,off0", CASES)
def test_reproduce_pins_exact_seed(state, cache, species, off0):
    import numpy as np

    from pokemon_agent.gba_trigger import make_bundle, reproduce
    from pokemon_agent.gen3_rng import generate_wild
    from pokemon_agent.wild_enumerate import _unpack_iv
    if not (os.path.exists(state) and os.path.exists(cache)):
        pytest.skip("state or cache not present")
    B = make_bundle(state)
    c = np.load(cache)
    realized = 0
    n = 10
    for i in range(n):
        G = int(c["G"][i]); pid = int(c["pid"][i])
        o1, o2, o3, o4 = (int(c[k][i]) for k in ("o1", "o2", "o3", "o4"))
        r = reproduce(B, G, pid, species, "LR", 2, 1, off0=off0)
        if r is None:
            continue
        realized += 1
        mpid, iv, sp, R = r
        # The reproduced encounter IS exactly G: pid/species match a fresh offline
        # generation from G (no off-by-offset error), and its true IVs are one of
        # G's four scanline-timing variants.
        assert sp == species
        assert mpid == pid == generate_wild(G).pid
        variants = {_unpack_iv(o1, o3), _unpack_iv(o2, o3),
                    _unpack_iv(o2, o4), _unpack_iv(o1, o2)}
        assert tuple(iv) in variants, f"{iv} not a timing-variant of G=0x{G:08X}"
    # Most candidates have a reproducing offset on the lattice at this state.
    assert realized >= 6, f"only reproduced {realized}/{n} at {state}"
