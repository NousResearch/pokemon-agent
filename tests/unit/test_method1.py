"""gen_method1 (FRLG starter / Method 1): 4 consecutive RNG calls, no gaps."""
import pytest

from pokemon_agent.shiny_gen3 import gen_method1, lcg_next

SEEDS = [0x00000000, 0x12345678, 0xDEADBEEF, 0x55FF2959]


@pytest.mark.parametrize("seed", SEEDS)
def test_method1_matches_manual_chain(seed):
    pid, ivs = gen_method1(seed)
    s = lcg_next(seed); lo = (s >> 16) & 0xFFFF
    s = lcg_next(s); hi = (s >> 16) & 0xFFFF
    s = lcg_next(s); iv1 = (s >> 16) & 0x7FFF
    s = lcg_next(s); iv2 = (s >> 16) & 0x7FFF
    assert pid == ((hi << 16) | lo)
    assert ivs.hp == iv1 & 31
    assert ivs.attack == (iv1 >> 5) & 31
    assert ivs.defense == (iv1 >> 10) & 31
    assert ivs.speed == iv2 & 31
    assert ivs.sp_attack == (iv2 >> 5) & 31
    assert ivs.sp_defense == (iv2 >> 10) & 31


@pytest.mark.parametrize("seed", SEEDS)
def test_ivs_in_range(seed):
    _pid, ivs = gen_method1(seed)
    for v in ivs.as_tuple():
        assert 0 <= v <= 31
