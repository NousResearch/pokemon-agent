"""Golden regression: write-seed 0x55FF2959 on the Route 3 grass state reproduces
the Hasty shiny Spearow 31/31/17/31/19/31 (the one the user caught). Requires mgba.
"""
import pytest

from pokemon_agent.gba_trigger import jiggle_trigger, make_bundle


@pytest.mark.emulator
def test_hasty_spearow_golden(route3_grass_state, golden):
    B = make_bundle(route3_grass_state)
    res = jiggle_trigger(B, golden["hasty_spearow_seed"])
    assert res is not None, "the golden seed should trigger an encounter"
    pid, ivs, species = res
    assert species == golden["hasty_spearow_species"]
    assert tuple(ivs) == golden["hasty_spearow_ivs"]
