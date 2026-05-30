"""Route B hybrid: under the deterministic fixed_trigger, calibrate per-env
thresholds + ambiguous ranges and assert every NON-boundary candidate is
predicted EXACTLY offline (the emulator is only needed for the rare boundary
band). Requires mgba — runs in the devbox.
"""
import pytest

from pokemon_agent.gba_calibrate import calibrate_env, validate


@pytest.mark.emulator
@pytest.mark.slow
def test_hybrid_nonboundary_is_exact(route3_grass_state):
    res = calibrate_env(route3_grass_state, n=120, verbose=False)
    nb_ok, nb_tot, boundary, offchain = validate(res, verbose=False)
    assert nb_tot >= 20, "expected a meaningful non-boundary sample"
    # The whole point of the hybrid: non-boundary predictions are 100% offline-exact.
    assert nb_ok == nb_tot, f"non-boundary mispredictions: {nb_tot - nb_ok}"
