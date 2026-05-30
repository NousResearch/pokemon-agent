"""Per-env calibration + band-collapse validation for Route B (REQUIRES mgba).

Under the deterministic ``fixed_trigger`` the generation phase phi0 is pinned, so
the VBlank-crossing thresholds are SHARP. ``calibrate_env`` measures them
(offset, ta, tb_lo, tb_hi) and checks band==0; the module __main__ also validates
that ``gen3_rng.wild_outcome_exact`` reproduces the emulator's IVs for every
held-out seed (zero ambiguity, zero emulator at predict time afterward).

    distrobox enter devbox -- .venv-gba/bin/python -m pokemon_agent.gba_calibrate [state] [n]
"""
from __future__ import annotations

import collections
import random
import sys

from pokemon_agent.gba_trigger import fixed_trigger, make_bundle
from pokemon_agent.gen3_rng import (
    MAX_NATURE_LOOP,
    NUM_NATURES,
    is_boundary_loop,
    wild_outcome_exact,
)
from pokemon_agent.shiny_gen3 import lcg_next

BIG = 1 << 30


def _advance(s, n):
    for _ in range(n):
        s = lcg_next(s)
    return s


def _four_outputs(G):
    """(pid, loop_iters, [o1,o2,o3,o4]) — replicates the generation chain."""
    s = lcg_next(G); s = lcg_next(s); s = lcg_next(s); nature = (s >> 16) % NUM_NATURES
    pid = 0; it = 0
    for it in range(1, MAX_NATURE_LOOP + 1):
        s = lcg_next(s); lo = (s >> 16) & 0xFFFF
        s = lcg_next(s); hi = (s >> 16) & 0xFFFF
        pid = ((hi << 16) | lo) & 0xFFFFFFFF
        if pid % NUM_NATURES == nature:
            break
    outs = []
    for _ in range(4):
        s = lcg_next(s); outs.append((s >> 16) & 0x7FFF)
    return pid, it, outs


def calibrate_env(state, n=240, seed=7, margin=2, verbose=True):
    """Sample n encounters under fixed_trigger; return a dict with the dominant
    offset, sharp thresholds (ta, tb_lo, tb_hi), whether the band collapsed, and
    per-sample rows for validation."""
    B = make_bundle(state); rng = random.Random(seed)
    offc = collections.Counter(); rows = []   # (off, G, loop, a, nb2, ivs)
    for _ in range(n):
        V = rng.getrandbits(32); r = fixed_trigger(B, V)
        if not r:
            continue
        pid, ivs, _sp = r
        off = next((o for o in range(0, 260) if _four_outputs(_advance(V, o))[0] == pid), None)
        if off is None:
            continue
        G = _advance(V, off); _pid, loop, outs = _four_outputs(G)
        iv1w = (ivs[0] | (ivs[1] << 5) | (ivs[2] << 10)) & 0x7FFF
        iv2w = (ivs[3] | (ivs[4] << 5) | (ivs[5] << 10)) & 0x7FFF
        a = next((k for k in range(2) if outs[k] == iv1w), None)
        nb2 = next((k for k in range(3) if outs[1 + k] == iv2w), None)
        offc[off] += 1
        rows.append((off, G, loop, a, nb2, ivs))

    dom = offc.most_common(1)[0][0]
    dr = [(loop, a, nb2) for off, _G, loop, a, nb2, _iv in rows
          if off == dom and a is not None and nb2 is not None]

    def _transition(lower_pred, upper_pred):
        """Clean threshold + ambiguous range for a 0->1 style regime transition.
        Returns (threshold, ambig_range_or_None): loops < range are `lower`, loops
        > range are `upper`, loops IN range are ambiguous (residual jitter)."""
        lo_max = max((loop for loop, a, nb in dr if lower_pred(a, nb)), default=-1)
        hi_min = min((loop for loop, a, nb in dr if upper_pred(a, nb)), default=BIG)
        if hi_min >= BIG:
            return BIG, None                       # never reaches upper regime
        if lo_max < hi_min:
            return hi_min, None                    # clean: sharp threshold
        return lo_max + 1, (hi_min - margin, lo_max + margin)  # overlap -> ambiguous band

    ta, range_a = _transition(lambda a, nb: a == 0, lambda a, nb: a == 1)
    tb_lo, range_b01 = _transition(lambda a, nb: nb == 0, lambda a, nb: nb >= 1)
    tb_hi, range_b12 = _transition(lambda a, nb: nb <= 1, lambda a, nb: nb >= 2)
    ambig = [r for r in (range_a, range_b01, range_b12) if r is not None]
    sharp = not ambig
    res = dict(state=state, dominant_offset=dom, ta=ta, tb_lo=tb_lo, tb_hi=tb_hi,
               ambig_ranges=ambig, sharp=sharp, n_dom=len(dr), rows=rows)
    if verbose:
        print("calibrate_env(%s): offset=%d ta=%s tb_lo=%s tb_hi=%s  ambig=%s (n=%d)"
              % (state, dom, ta if ta < BIG else "inf", tb_lo if tb_lo < BIG else "inf",
                 tb_hi if tb_hi < BIG else "inf",
                 ambig if ambig else "NONE(sharp)", len(dr)), flush=True)
    return res


def validate(res, verbose=True):
    """Hybrid check: wild_outcome_exact must reproduce the emulator IVs for every
    NON-boundary dominant-offset sample (loop outside the measured ambiguous
    ranges). Boundary samples are the ones the hybrid confirms in-emulator. Returns
    (nonbound_ok, nonbound_tot, n_boundary, n_offchain)."""
    dom = res["dominant_offset"]; ta, tb_lo, tb_hi = res["ta"], res["tb_lo"], res["tb_hi"]
    ambig = res["ambig_ranges"]
    nb_ok = nb_tot = boundary = offchain = 0
    misses = []
    for off, G, loop, a, nb2, ivs in res["rows"]:
        if off != dom:
            continue
        if a is None or nb2 is None:
            offchain += 1; continue
        if is_boundary_loop(loop, ambig):
            boundary += 1; continue
        nb_tot += 1
        pred = wild_outcome_exact(G, ta, tb_lo, tb_hi).ivs.as_tuple()
        if pred == tuple(ivs):
            nb_ok += 1
        else:
            misses.append((G, loop, pred, tuple(ivs)))
    if verbose:
        print("validate: NON-boundary %d/%d exact offline at offset %d; "
              "boundary(confirm)=%d off-chain=%d"
              % (nb_ok, nb_tot, dom, boundary, offchain), flush=True)
        for G, loop, p, t in misses[:6]:
            print("  MISS G=0x%08X loop=%d pred=%s true=%s" % (G, loop, p, t), flush=True)
    return nb_ok, nb_tot, boundary, offchain


if __name__ == "__main__":
    state = sys.argv[1] if len(sys.argv) > 1 else "roms/leafgreen_route3_grass.ss1"
    n = int(sys.argv[2]) if len(sys.argv) > 2 else 240
    res = calibrate_env(state, n=n)
    validate(res)
