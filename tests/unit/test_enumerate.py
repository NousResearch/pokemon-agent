"""The pure enumerator: agreement with the canonical per-seed predictor, and
numpy-vs-numba bit-identical results."""
import pytest

from pokemon_agent.gen3_rng import wild_outcome_both
from pokemon_agent.wild_enumerate import _enum_range, _get_numba_kernel, _unpack_iv

TID, SID = 51376, 36462
# All slots + all natures so any shiny in the range is kept (shiny is ~1/8192).
ARGS = (0, 1 << 20, 1 << 22, TID, SID, tuple(range(12)), tuple(range(25)))


def _run(kernel):
    return _enum_range(ARGS + (kernel,))


def test_enumerator_agrees_with_wild_outcome():
    out = _run("numpy")
    assert len(out) > 20, "expected a handful of shiny candidates in 2^20 seeds"
    for G, pid, nat, iters, o1, o2, o3, o4 in out:
        a, b = wild_outcome_both(G)            # o1-variant, o2-variant
        assert a.pid == pid and a.nature == nat and a.loop_iters == iters
        # shiny check (these came from the enumerator's shiny filter)
        assert ((TID ^ SID ^ (pid >> 16) ^ (pid & 0xFFFF)) & 0xFFFF) < 8
        assert a.ivs.as_tuple() == _unpack_iv(o1, o3)
        assert b.ivs.as_tuple() == _unpack_iv(o2, o3)
        assert 0 <= o4 <= 0x7FFF


@pytest.mark.skipif(_get_numba_kernel() is None, reason="numba not installed")
def test_numba_matches_numpy_bit_identical():
    out_np = _run("numpy")
    out_nb = _run("numba")
    assert out_np == out_nb
