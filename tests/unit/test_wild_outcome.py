"""The decoded VBlank IV model: wild_outcome / wild_outcome_both invariants."""
import pytest

from pokemon_agent.gen3_rng import wild_outcome, wild_outcome_both

GEN_SEEDS = [0x00000000, 0x12345678, 0xDEADBEEF, 0x6AB32C6D, 0x74AAD729,
             0xA4A616C6, 0x98E47D36, 0x55FF2959]


@pytest.mark.parametrize("g", GEN_SEEDS)
def test_pid_matches_nature(g):
    w = wild_outcome(g, iv1_threshold=28)
    assert w.pid % 25 == w.nature
    assert 0 <= w.slot <= 11
    assert w.loop_iters >= 1
    for v in w.ivs.as_tuple():
        assert 0 <= v <= 31


@pytest.mark.parametrize("g", GEN_SEEDS)
def test_both_variants_differ_only_in_iv1(g):
    a, b = wild_outcome_both(g)   # a: always o1 (short side); b: always o2 (long side)
    # PID/nature/slot identical across variants
    assert a.pid == b.pid and a.nature == b.nature and a.slot == b.slot
    ta, tb = a.ivs.as_tuple(), b.ivs.as_tuple()
    # iv2 (Speed, SpAtk, SpDef) is o3 -> identical; iv1 (HP, Atk, Def) is o1 vs o2
    assert ta[3:] == tb[3:], "Speed/SpAtk/SpDef (iv2=o3) must be identical across variants"


@pytest.mark.parametrize("g", GEN_SEEDS)
def test_threshold_selects_variant(g):
    w = wild_outcome(g, iv1_threshold=28)
    a, b = wild_outcome_both(g)   # o1-variant, o2-variant
    expected = b if w.loop_iters >= 28 else a
    assert w.ivs.as_tuple() == expected.ivs.as_tuple()


def test_extreme_thresholds():
    g = 0x74AAD729
    short = wild_outcome(g, iv1_threshold=1 << 30)   # loop always < T -> o1
    long_ = wild_outcome(g, iv1_threshold=0)         # loop always >= T -> o2
    a, b = wild_outcome_both(g)
    assert short.ivs.as_tuple() == a.ivs.as_tuple()
    assert long_.ivs.as_tuple() == b.ivs.as_tuple()
