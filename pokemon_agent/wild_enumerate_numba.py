"""Numba JIT kernel for the nature-lock loop — the enumeration hot path.

Per-element scalar version of `wild_enumerate._nature_lock_numpy`, written to
produce bit-identical (pid, iters, post, matched) arrays (validated in
tests/unit/test_enumerate.py). Imported lazily; if numba is unavailable the
enumerator falls back to the numpy kernel. All arithmetic is uint64 with a
32-bit mask, matching the Gen-3 LCG exactly.
"""
from __future__ import annotations

import numpy as np
from numba import njit


@njit(cache=True)
def nature_lock_numba(cur, tgt, A, C, M, max_loop):
    SIX = np.uint64(16)
    N25 = np.uint64(25)
    n = cur.shape[0]
    pid = np.zeros(n, np.uint64)
    iters = np.zeros(n, np.int32)
    post = np.zeros(n, np.uint64)
    matched = np.zeros(n, np.bool_)
    for i in range(n):
        c = cur[i]
        t = tgt[i]
        for j in range(1, max_loop + 1):
            s1 = (c * A + C) & M
            lo = s1 >> SIX
            s2 = (s1 * A + C) & M
            hi = s2 >> SIX
            p = ((hi << SIX) | lo) & M
            if (p % N25) == t:
                pid[i] = p
                iters[i] = j
                post[i] = s2
                matched[i] = True
                break
            c = s2
    return pid, iters, post, matched
