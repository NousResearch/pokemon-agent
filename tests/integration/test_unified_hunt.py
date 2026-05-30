"""The unified hunt finds a strong physical result for a LOW-rate species
(Nidoran-male, 1% slot) — the case the single-offset hybrid missed. Requires mgba
+ a cached candidate set; runs in the devbox.
"""
import os

import pytest


@pytest.mark.emulator
@pytest.mark.slow
def test_unified_finds_atk31_nidoran():
    from hunt_hybrid import DEFAULT_COMBOS, run_unified_hunt
    combos = [c for c in DEFAULT_COMBOS if os.path.exists(c[1])]
    if not combos or not os.path.exists("cache_nidoranm.npz"):
        pytest.skip("env states or cache not present")

    def phys(nat):
        inc, dec = nat // 5, nat % 5
        return not ((dec == 0 and inc != 0) or (dec == 2 and inc != 2))

    def metric(iv, nat):
        return ((iv[1] == 31) + (iv[3] == 31), sum(1 for x in iv if x == 31), iv[0] + iv[2] + iv[5])

    _realized, best = run_unified_hunt(
        32, (10,), metric, phys, "cache_nidoranm.npz", "/tmp/test_nidoran_best.ss1",
        combos=combos, topn=30, verbose=False)
    assert best is not None, "unified hunt should realize a candidate"
    _G, _pid, _nat, iv, _clabel = best
    # the best physical Nidoran-male realizes Attack 31 (recovers the dual-31s)
    assert iv[1] == 31, f"expected an Atk31 physical Nidoran, got {iv}"
