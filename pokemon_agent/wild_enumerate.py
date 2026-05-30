"""Pure, offline candidate enumeration + selection (NO emulator).

Stage 1 of the wild-shiny pipeline: scan the 2^32 gen-seed space and keep every
shiny candidate of the target species/slots/natures, recording the env-independent
IV ingredients (``iters`` = nature-loop length, ``o1/o2/o3`` = the three post-PID
RNG outputs). The per-env IV threshold is applied later by :func:`predict_env_ivs`
(see :mod:`pokemon_agent.gen3_rng` for the VBlank model). Runs on the host venv;
the hot nature-lock loop is a swappable kernel (numpy, or numba if installed —
:mod:`pokemon_agent.wild_enumerate_numba`).
"""
from __future__ import annotations

import json
import os
import time
from concurrent.futures import ProcessPoolExecutor

from pokemon_agent.gen3_rng import MAX_NATURE_LOOP, NUM_NATURES, SLOT_CUMULATIVE
from pokemon_agent.shiny_gen3 import LCG_ADD, LCG_MULT

NAT = ["Hardy", "Lonely", "Brave", "Adamant", "Naughty", "Bold", "Docile", "Relaxed", "Impish",
       "Lax", "Timid", "Hasty", "Serious", "Jolly", "Naive", "Modest", "Mild", "Quiet", "Bashful",
       "Rash", "Calm", "Gentle", "Sassy", "Careful", "Quirky"]


def n31(iv):
    return sum(1 for x in iv if x == 31)


# ----------------------------- nature-lock kernels -----------------------------
# Both kernels take the post-(slot,level,nature) LCG state `cur` and the target
# nature `tgt` per candidate, and return (pid, iters, post, matched) where `post`
# is the LCG state right after the matched PID's two Random() calls. The numpy
# kernel is vectorized over candidates; the numba kernel (if present) is a scalar
# per-element loop. They are validated bit-identical (tests/unit/test_enumerate.py).

def _nature_lock_numpy(cur, tgt, max_loop=MAX_NATURE_LOOP):
    import numpy as np
    A = np.uint64(LCG_MULT); C = np.uint64(LCG_ADD); M = np.uint64(0xFFFFFFFF); SIX = np.uint64(16)
    n = cur.shape[0]
    matched = np.zeros(n, bool); pid = np.zeros(n, np.uint64)
    iters = np.zeros(n, np.int32); post = np.zeros(n, np.uint64)
    c = cur.copy()
    for j in range(max_loop):
        s1 = (c * A + C) & M; lo = s1 >> SIX
        s2 = (s1 * A + C) & M; hi = s2 >> SIX
        p = ((hi << SIX) | lo) & M
        nm = (~matched) & ((p % np.uint64(NUM_NATURES)) == tgt)
        pid[nm] = p[nm]; iters[nm] = j + 1; post[nm] = s2[nm]; matched |= nm; c = s2
        if matched.all():
            break
    return pid, iters, post, matched


def _get_numba_kernel():
    try:
        from pokemon_agent.wild_enumerate_numba import nature_lock_numba
        return nature_lock_numba
    except Exception:
        return None


# ------------------------------- enumeration -----------------------------------

def _enum_range(args):
    import numpy as np
    start, end, chunk, tid, sid, slots_t, nats_t, kernel = args
    A = np.uint64(LCG_MULT); C = np.uint64(LCG_ADD); M = np.uint64(0xFFFFFFFF); SIX = np.uint64(16)
    def stp(s): return (s * A + C) & M
    xb = np.uint64((tid ^ sid) & 0xFFFF); cums = np.array(SLOT_CUMULATIVE)
    slots = np.array(slots_t); nats = np.array(nats_t)
    nature_lock = _get_numba_kernel() if kernel == "numba" else None
    out = []; b = start
    while b < end:
        n = min(chunk, end - b); G = np.arange(b, b + n, dtype=np.uint64); b += n
        s = stp(G); slot = np.searchsorted(cums, (s >> SIX) % np.uint64(100), side='right')
        s = stp(s); s = stp(s); nat = (s >> SIX) % np.uint64(NUM_NATURES)
        gi = np.nonzero(np.isin(slot, slots) & np.isin(nat, nats))[0]
        if not gi.size:
            continue
        Gs = G[gi]; tgt = nat[gi].astype(np.uint64); cur = s[gi].copy()
        if nature_lock is not None:
            pid, iters, post, matched = nature_lock(
                cur, tgt, np.uint64(LCG_MULT), np.uint64(LCG_ADD),
                np.uint64(0xFFFFFFFF), MAX_NATURE_LOOP)
        else:
            pid, iters, post, matched = _nature_lock_numpy(cur, tgt)
        # Three RNG outputs after the PID loop (env-independent): the VBlank model
        # picks iv1 from o1/o2 and iv2=o3 (see gen3_rng.wild_outcome).
        s1 = stp(post); o1 = (s1 >> SIX) & np.uint64(0x7FFF)
        s2 = stp(s1); o2 = (s2 >> SIX) & np.uint64(0x7FFF)
        s3 = stp(s2); o3 = (s3 >> SIX) & np.uint64(0x7FFF)
        s4 = stp(s3); o4 = (s4 >> SIX) & np.uint64(0x7FFF)
        pl = pid & np.uint64(0xFFFF); ph = pid >> SIX
        sh = matched & (((xb ^ ph ^ pl) & np.uint64(0xFFFF)) < np.uint64(8))
        for e in np.nonzero(sh)[0]:
            out.append((int(Gs[e]), int(pid[e]), int(tgt[e]), int(iters[e]),
                        int(o1[e]), int(o2[e]), int(o3[e]), int(o4[e])))
    return out


def enumerate_candidates(species, slots, tid, sid, allowed_natures=tuple(range(25)),
                         cache_path=None, workers=None, verbose=True, kernel="auto"):
    """Stage 1. Enumerate all shiny gen-seeds G producing `species` (via `slots`)
    with an allowed nature, for this TID/SID. Returns a dict of numpy arrays:
    G, pid, nature, iters, o1, o2, o3 (env-independent VBlank-IV ingredients).
    Cached to `cache_path` (.npz). `kernel`: "auto" (numba if available else
    numpy), "numba", or "numpy"."""
    import numpy as np
    keys = ("G", "pid", "nature", "iters", "o1", "o2", "o3", "o4")
    if cache_path and os.path.exists(cache_path):
        d = np.load(cache_path)
        if "o4" in d:
            if verbose:
                print("Stage1: loaded %d cached candidates from %s"
                      % (len(d["G"]), cache_path), flush=True)
            return {k: d[k] for k in keys}
        elif verbose:
            print("Stage1: cache lacks o4 IV field; re-enumerating", flush=True)
    if kernel == "auto":
        kernel = "numba" if _get_numba_kernel() is not None else "numpy"
    NW = workers or os.cpu_count(); span = (1 << 32) // NW
    ranges = [(i * span, (i + 1) * span if i < NW - 1 else (1 << 32), 1 << 22,
               tid, sid, tuple(slots), tuple(allowed_natures), kernel) for i in range(NW)]
    out = []; t0 = time.time()
    with ProcessPoolExecutor(NW) as ex:
        for r in ex.map(_enum_range, ranges):
            out.extend(r)
    cols = list(zip(*out)) if out else ([],) * 8
    arr = {
        "G": np.array(cols[0], dtype=np.uint64), "pid": np.array(cols[1], dtype=np.uint64),
        "nature": np.array(cols[2], dtype=np.uint8), "iters": np.array(cols[3], dtype=np.int32),
        "o1": np.array(cols[4], dtype=np.uint16), "o2": np.array(cols[5], dtype=np.uint16),
        "o3": np.array(cols[6], dtype=np.uint16), "o4": np.array(cols[7], dtype=np.uint16),
    }
    if verbose:
        print("Stage1: enumerated %d candidates in %.1fs (kernel=%s)"
              % (len(out), time.time() - t0, kernel), flush=True)
    if cache_path:
        np.savez(cache_path, species=species, tid=tid, sid=sid, **arr)
        if verbose:
            print("Stage1: cached -> %s" % cache_path, flush=True)
    return arr


# --------------------------- offline IV application ----------------------------

def _unpack_iv(iv1, iv2):
    return (iv1 & 31, (iv1 >> 5) & 31, (iv1 >> 10) & 31,
            iv2 & 31, (iv2 >> 5) & 31, (iv2 >> 10) & 31)


def predict_env_ivs(cands, band):
    """Apply an env's IV threshold to cached candidates (offline, no emulation).

    `band` = (lo, hi): nature-loop lengths <lo take iv1=o1, >hi take iv1=o2, and
    those IN [lo,hi] are ambiguous (emit BOTH variants). iv2 is always o3. Returns
    rows (G, pid, nature, iv_tuple, ambiguous_bool). With a deterministic trigger
    the band is empty, so every row is unambiguous.
    """
    lo, hi = band
    G = cands["G"]; pid = cands["pid"]; nat = cands["nature"]; it = cands["iters"]
    o1 = cands["o1"]; o2 = cands["o2"]; o3 = cands["o3"]
    rows = []
    for i in range(len(G)):
        Gi = int(G[i]); Pi = int(pid[i]); Ni = int(nat[i]); o3i = int(o3[i])
        if it[i] < lo:
            variants = [int(o1[i])]
        elif it[i] > hi:
            variants = [int(o2[i])]
        else:
            variants = [int(o1[i]), int(o2[i])]
        amb = len(variants) > 1
        for iv1 in variants:
            rows.append((Gi, Pi, Ni, _unpack_iv(iv1, o3i), amb))
    return rows


# ------------------------------- Stage 3: select -------------------------------

def load_results(results_jsonl):
    """Load accumulated rows from a results DB jsonl; dedupe by (G, env)."""
    seen = {}
    if not os.path.exists(results_jsonl):
        return []
    with open(results_jsonl) as f:
        for line in f:
            try:
                d = json.loads(line)
            except ValueError:
                continue
            seen[(d["G"], d["env"])] = d
    return list(seen.values())


def select_best(rows, metric, top=25):
    """Rank rows by `metric(iv, nature)->sortkey` (higher=better). `rows` may be
    dicts (from load_results) or tuples (G, pid, nature, iv, *extra)."""
    norm = []
    for r in rows:
        if isinstance(r, dict):
            norm.append((r["G"], r["pid"], r["nature"], tuple(r["iv"]), r["env"]))
        else:
            G_, P, nat_, iv = r[0], r[1], r[2], r[3]
            norm.append((G_, P, nat_, tuple(iv), None))
    norm.sort(key=lambda t: metric(t[3], t[2]), reverse=True)
    return norm[:top]
