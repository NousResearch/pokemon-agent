"""Encounter-slot mapping (slot_index / SLOT_CUMULATIVE)."""
from pokemon_agent.gen3_rng import SLOT_CUMULATIVE, slot_index


def test_cumulative_thresholds():
    # Standard Gen-3 land slots: 20,20,10,10,10,10,5,5,4,4,1,1 -> cumulative.
    assert SLOT_CUMULATIVE == (20, 40, 50, 60, 70, 80, 85, 90, 94, 98, 99, 100)
    assert SLOT_CUMULATIVE[-1] == 100


def test_slot_boundaries():
    # rand%100 < threshold picks the first matching slot.
    assert slot_index(0) == 0          # 0 < 20
    assert slot_index(19) == 0
    assert slot_index(20) == 1         # 20 < 40
    assert slot_index(39) == 1
    assert slot_index(40) == 2
    assert slot_index(97) == 9         # 97 < 98 -> slot 9
    assert slot_index(98) == 10        # 98 < 99 -> slot 10
    assert slot_index(99) == 11        # 99 < 100 -> slot 11
    # slot_index mods the raw value by 100, so it wraps every 100.
    assert slot_index(100) == slot_index(0)


def test_every_value_maps_to_valid_slot():
    for r in range(0, 65536, 137):
        assert 0 <= slot_index(r) <= 11
