"""calibrate_iv_threshold: derive the per-offset iv1 threshold T + ambiguous band
from (loop_iters, iv1_uses_o2) samples."""
from pokemon_agent.gen3_rng import calibrate_iv_threshold


def test_clean_contiguous_separation():
    # o1 used up to loop 12, o2 from loop 13 -> sharp threshold, no band.
    T, band = calibrate_iv_threshold([(10, False), (12, False), (13, True), (20, True)])
    assert T == 13
    assert band is None


def test_banded_gap():
    # gap between max-o1 (10) and min-o2 (20) -> ambiguous band (11..19).
    T, band = calibrate_iv_threshold([(10, False), (20, True)])
    assert T == 20
    assert band == (11, 19)


def test_never_switches():
    # all samples use o1 -> threshold "infinity", no band.
    T, band = calibrate_iv_threshold([(10, False), (12, False), (30, False)])
    assert T >= (1 << 29)
    assert band is None


def test_all_o2():
    # all samples use o2 -> T is the smallest observed loop, and the unsampled
    # loops below it (0..4) are reported as an ambiguous band (never seen using o1).
    T, band = calibrate_iv_threshold([(5, True), (9, True), (40, True)])
    assert T == 5
    assert band == (0, 4)
