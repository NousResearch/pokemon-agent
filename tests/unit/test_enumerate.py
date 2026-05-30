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


def test_predict_env_exact_regime_and_boundary():
    import numpy as np

    from pokemon_agent.wild_enumerate import predict_env_exact
    cands = dict(
        G=np.array([1, 2, 3], dtype=np.uint64),
        pid=np.array([0, 0, 0], dtype=np.uint64),
        nature=np.array([0, 0, 0], dtype=np.uint8),
        iters=np.array([10, 40, 100], dtype=np.int32),
        o1=np.array([100, 200, 300], dtype=np.uint16),
        o2=np.array([111, 222, 333], dtype=np.uint16),
        o3=np.array([7, 8, 9], dtype=np.uint16),
        o4=np.array([70, 80, 90], dtype=np.uint16),
    )
    rows = predict_env_exact(cands, ta=50, tb_lo=0, tb_hi=1 << 30, ambig_ranges=[(37, 47)])
    # loop 10: a=0 -> iv1=o1=100, nb2=1 -> iv2=o3=7; not boundary
    assert rows[0][4] is False and rows[0][3] == _unpack_iv(100, 7)
    # loop 40: inside (37,47) -> boundary (confirm in-emulator)
    assert rows[1][4] is True
    # loop 100: a=1 -> iv1=o2=333, nb2=1 -> iv2=o3=9; not boundary
    assert rows[2][4] is False and rows[2][3] == _unpack_iv(333, 9)


def test_best_possible_iv_picks_best_variant():
    from pokemon_agent.wild_enumerate import best_possible_iv

    def metric(iv, nat):  # favour Atk31 & Spe31, then total #31
        return ((iv[1] == 31) + (iv[3] == 31), sum(1 for x in iv if x == 31))

    o1 = 31 << 5   # iv1 word: Atk=31 (bits 5-9), HP=Def=0
    o2 = 0         # iv1 word: all zero
    o3 = 31        # iv2 word: Spe=31 (bits 0-4)
    o4 = 0
    best = best_possible_iv(o1, o2, o3, o4, 0, metric)
    # best variant uses iv1=o1 (Atk31) + iv2=o3 (Spe31)
    assert best == _unpack_iv(o1, o3)
    assert best[1] == 31 and best[3] == 31
