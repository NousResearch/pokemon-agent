"""LCG primitives: forward/backward inverses and the documented recurrence."""
import pytest

from pokemon_agent.shiny_gen3 import LCG_ADD, LCG_MULT, lcg_next, lcg_prev, rewind

SEEDS = [0x00000000, 0x00000001, 0xFFFFFFFF, 0x12345678, 0xDEADBEEF,
         0x55FF2959, 0x41C64E6D, 0x80000000, 0x6AB32C6D]


@pytest.mark.parametrize("s", SEEDS)
def test_lcg_next_recurrence(s):
    assert lcg_next(s) == (s * LCG_MULT + LCG_ADD) & 0xFFFFFFFF


@pytest.mark.parametrize("s", SEEDS)
def test_prev_inverts_next(s):
    assert lcg_prev(lcg_next(s)) == s
    assert lcg_next(lcg_prev(s)) == s


@pytest.mark.parametrize("s", SEEDS)
@pytest.mark.parametrize("n", [0, 1, 2, 7, 59, 256, 1000])
def test_rewind_then_advance_is_identity(s, n):
    r = rewind(s, n)
    for _ in range(n):
        r = lcg_next(r)
    assert r == s


def test_next_stays_32bit():
    s = 0xFFFFFFFF
    for _ in range(1000):
        s = lcg_next(s)
        assert 0 <= s <= 0xFFFFFFFF
