"""Reusable 3-stage wild-shiny hunt pipeline (LeafGreen). See
docs/CANDIDATE_GEN_PLAN.md for the design and rationale.

Stage 1  enumerate_candidates(...)  -> (G, pid, nature) for shiny + slot + nature.
          State/timing-INDEPENDENT (PID half). Cached to .npz so it's paid once.
Stage 2  verify_env(candidates, env) -> rows (G, pid, nature, iv, species) read
          from real mGBA cores in ONE timing environment. IVs are the timing-
          dependent half; stacking envs widens IV coverage for the same PIDs.
Stage 3  select_best(rows, metric)   -> ranked results.

An ENV is a timing environment = (state-file, jiggle axis/hold/rel, offsets).
Results accumulate (append-only jsonl) across envs and are resumable.
"""
from __future__ import annotations

import json
import os
import time
from concurrent.futures import ProcessPoolExecutor

ROM = "roms/Pokemon - LeafGreen Version (USA).gba"
ENEMY = 0x0202402C
RNG = 0x03005000
LCG_A = 0x41C64E6D
LCG_C = 0x00006073
NAT = ["Hardy", "Lonely", "Brave", "Adamant", "Naughty", "Bold", "Docile", "Relaxed", "Impish",
       "Lax", "Timid", "Hasty", "Serious", "Jolly", "Naive", "Modest", "Mild", "Quiet", "Bashful",
       "Rash", "Calm", "Gentle", "Sassy", "Careful", "Quirky"]


# ============================== Stage 1: enumerate ==============================

def _enum_range(args):
    import numpy as np
    start, end, chunk, tid, sid, slots_t, nats_t = args
    A = np.uint64(LCG_A); C = np.uint64(LCG_C); M = np.uint64(0xFFFFFFFF); SIX = np.uint64(16)
    def stp(s): return (s * A + C) & M
    xb = np.uint64((tid ^ sid) & 0xFFFF); cums = np.cumsum([20, 20, 10, 10, 10, 10, 5, 5, 4, 4, 1, 1])
    slots = np.array(slots_t); nats = np.array(nats_t)
    out = []; b = start
    while b < end:
        n = min(chunk, end - b); G = np.arange(b, b + n, dtype=np.uint64); b += n
        s = stp(G); slot = np.searchsorted(cums, (s >> SIX) % np.uint64(100), side='right')
        s = stp(s); s = stp(s); nat = (s >> SIX) % np.uint64(25)
        gi = np.nonzero(np.isin(slot, slots) & np.isin(nat, nats))[0]
        if not gi.size:
            continue
        Gs = G[gi]; tgt = nat[gi].astype(np.uint64); cur = s[gi].copy()
        matched = np.zeros(gi.size, bool); pid = np.zeros(gi.size, np.uint64)
        iters = np.zeros(gi.size, np.int32); post = np.zeros(gi.size, np.uint64)
        for j in range(400):
            s1 = stp(cur); lo = s1 >> SIX; s2 = stp(s1); hi = s2 >> SIX
            p = ((hi << SIX) | lo) & M
            nm = (~matched) & ((p % np.uint64(25)) == tgt)
            pid[nm] = p[nm]; iters[nm] = j + 1; post[nm] = s2[nm]; matched |= nm; cur = s2
            if matched.all():
                break
        # Three RNG outputs after the PID loop (env-independent): the VBlank model
        # picks iv1 from o1/o2 and iv2=o3 (see pokemon_agent.gen3_rng.wild_outcome).
        s1 = stp(post); o1 = (s1 >> SIX) & np.uint64(0x7FFF)
        s2 = stp(s1); o2 = (s2 >> SIX) & np.uint64(0x7FFF)
        s3 = stp(s2); o3 = (s3 >> SIX) & np.uint64(0x7FFF)
        pl = pid & np.uint64(0xFFFF); ph = pid >> SIX
        sh = matched & (((xb ^ ph ^ pl) & np.uint64(0xFFFF)) < np.uint64(8))
        for e in np.nonzero(sh)[0]:
            out.append((int(Gs[e]), int(pid[e]), int(tgt[e]), int(iters[e]),
                        int(o1[e]), int(o2[e]), int(o3[e])))
    return out


def enumerate_candidates(species, slots, tid, sid, allowed_natures=tuple(range(25)),
                         cache_path=None, workers=None, verbose=True):
    """Stage 1. Enumerate all shiny gen-seeds G producing `species` (via `slots`)
    with an allowed nature, for this TID/SID. Returns a dict of numpy arrays:
    G, pid, nature, iters (nature-loop length), and o1/o2/o3 (the three post-PID
    RNG outputs — the env-independent ingredients of the VBlank IV model). Cached
    to `cache_path` (.npz); apply an env's IV threshold cheaply via
    predict_env_ivs() without re-enumerating."""
    import numpy as np
    keys = ("G", "pid", "nature", "iters", "o1", "o2", "o3")
    if cache_path and os.path.exists(cache_path):
        d = np.load(cache_path)
        if "o3" in d:
            if verbose:
                print("Stage1: loaded %d cached candidates from %s" % (len(d["G"]), cache_path), flush=True)
            return {k: d[k] for k in keys}
        elif verbose:
            print("Stage1: cache lacks IV fields; re-enumerating", flush=True)
    NW = workers or os.cpu_count(); span = (1 << 32) // NW
    ranges = [(i * span, (i + 1) * span if i < NW - 1 else (1 << 32), 1 << 22,
               tid, sid, tuple(slots), tuple(allowed_natures)) for i in range(NW)]
    out = []; t0 = time.time()
    with ProcessPoolExecutor(NW) as ex:
        for r in ex.map(_enum_range, ranges):
            out.extend(r)
    cols = list(zip(*out)) if out else ([],) * 7
    arr = {
        "G": np.array(cols[0], dtype=np.uint64), "pid": np.array(cols[1], dtype=np.uint64),
        "nature": np.array(cols[2], dtype=np.uint8), "iters": np.array(cols[3], dtype=np.int32),
        "o1": np.array(cols[4], dtype=np.uint16), "o2": np.array(cols[5], dtype=np.uint16),
        "o3": np.array(cols[6], dtype=np.uint16),
    }
    if verbose:
        print("Stage1: enumerated %d candidates in %.1fs" % (len(out), time.time() - t0), flush=True)
    if cache_path:
        np.savez(cache_path, species=species, tid=tid, sid=sid, **arr)
        if verbose:
            print("Stage1: cached -> %s" % cache_path, flush=True)
    return arr


def _unpack_iv(iv1, iv2):
    return (iv1 & 31, (iv1 >> 5) & 31, (iv1 >> 10) & 31,
            iv2 & 31, (iv2 >> 5) & 31, (iv2 >> 10) & 31)


def predict_env_ivs(cands, band):
    """Apply an env's IV threshold to cached candidates (offline, no emulation).

    `band` = (lo, hi): nature-loop lengths <lo take iv1=o1, >hi take iv1=o2, and
    those IN [lo,hi] are ambiguous (sub-frame jitter) so BOTH variants are
    emitted. iv2 is always o3 (per fixed offset). Returns rows
    (G, pid, nature, iv_tuple, ambiguous_bool).
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


# ============================== Stage 2: verify env =============================

_B = {}  # per-worker core bundle, keyed by state path


def _bundle(state):
    if state in _B:
        return _B[state]
    import mgba.core, mgba.image, mgba.log
    from pokemon_agent.gba_state import load_state_file
    mgba.log.silence()
    core = mgba.core.load_path(ROM); fb = mgba.image.Image(*core.desired_video_dimensions())
    core.set_video_buffer(fb); core.reset(); load_state_file(core, state)
    B = dict(core=core, fb=fb, mem=core.memory, base=bytes(core.save_raw_state()),
             L=core.KEY_LEFT, R=core.KEY_RIGHT, U=core.KEY_UP, D=core.KEY_DOWN)
    _B[state] = B
    return B


def _emulate(B, V, axis, hold, rel, cap=70):
    from pokemon_agent.shiny_gen3 import decrypt_block, ivs_from_decrypted
    core = B["core"]; mem = B["mem"]
    core.load_raw_state(B["base"]); mem.u32[RNG] = V & 0xFFFFFFFF; bp = mem.u32[ENEMY]
    k1, k2 = (B["L"], B["R"]) if axis == "LR" else (B["U"], B["D"])
    i = 0; hit = False
    while i < cap:
        btn = k1 if i % 2 == 0 else k2
        for ph in range(hold + rel):
            core.set_keys(btn) if ph < hold else core.set_keys(); core.run_frame()
            if mem.u32[ENEMY] != bp:
                hit = True; break
        if hit:
            break
        i += 1
    if not hit:
        return None
    for _ in range(20):
        core.run_frame()
    mon = b"".join(mem.u32[ENEMY + 4 * k].to_bytes(4, "little") for k in range(25))
    pid = int.from_bytes(mon[0:4], "little"); otid = int.from_bytes(mon[4:8], "little")
    try:
        dec = decrypt_block(mon[0x20:0x20 + 48], pid, otid)
    except Exception:
        return None
    sp = int.from_bytes(dec[0:2], "little")
    return pid, ivs_from_decrypted(dec).as_tuple(), sp


def _verify_chunk(args):
    from pokemon_agent.shiny_gen3 import rewind
    sub, state, offsets, axis, hold, rel, target_sp = args
    B = _bundle(state); rows = []
    for G, P, nat in sub:
        for off in offsets:
            res = _emulate(B, rewind(int(G), off), axis, hold, rel)
            if res and res[0] == P and (target_sp is None or res[2] == target_sp):
                rows.append((int(G), int(P), int(nat), list(res[1]), res[2])); break
    return rows


def verify_env(candidates, state, offsets, env_id, axis="LR", hold=2, rel=1,
               target_species=None, results_jsonl=None, workers=None, verbose=True):
    """Stage 2 (validation / legacy mass-verify). Reproduce every candidate in
    ONE timing env, reading true IVs. `candidates` is the enumerate_candidates
    dict (or a (G,pid,nature) tuple). Appends rows to `results_jsonl`."""
    if isinstance(candidates, dict):
        G, pid, nat = candidates["G"], candidates["pid"], candidates["nature"]
    else:
        G, pid, nat = candidates
    NW = workers or os.cpu_count()
    cand = list(zip(G.tolist(), pid.tolist(), nat.tolist()))
    sl = [cand[i::NW] for i in range(NW)]
    args = [(s, state, tuple(offsets), axis, hold, rel, target_species) for s in sl]
    rows = []; t0 = time.time()
    with ProcessPoolExecutor(NW) as ex:
        for r in ex.map(_verify_chunk, args):
            rows.extend(r)
    if verbose:
        print("Stage2[%s]: %d/%d reproduced in %.1fs" % (env_id, len(rows), len(cand), time.time() - t0), flush=True)
    if results_jsonl:
        with open(results_jsonl, "a") as f:
            for G_, P, nat_, iv, sp in rows:
                f.write(json.dumps({"env": env_id, "G": G_, "pid": P, "nature": nat_,
                                    "iv": iv, "species": sp}) + "\n")
    return rows


def confirm_candidates(ranked_rows, state, offsets, axis="LR", hold=2, rel=1,
                       target_species=None, k=30, verbose=True):
    """Emulate the top-`k` ranked (predicted) candidates in one env to read their
    TRUE IVs — resolves the ambiguous-band predictions and guarantees an exact
    result. `ranked_rows` are best-first (G, pid, nature, pred_iv, amb); returns
    confirmed (G, pid, nature, true_iv, species) for those that reproduce."""
    from pokemon_agent.shiny_gen3 import rewind
    B = _bundle(state); seen = set(); confirmed = []; tried = 0; t0 = time.time()
    for G, P, nat, _pred, _amb in ranked_rows:
        if G in seen:
            continue
        seen.add(G); tried += 1
        if tried > k:
            break
        for off in offsets:
            res = _emulate(B, rewind(int(G), off), axis, hold, rel)
            if res and res[0] == P and (target_species is None or res[2] == target_species):
                confirmed.append((int(G), int(P), int(nat), tuple(res[1]), res[2])); break
    if verbose:
        print("confirm: %d/%d top candidates reproduced in %.1fs"
              % (len(confirmed), min(tried, k), time.time() - t0), flush=True)
    return confirmed


# ============================== Stage 3: select ================================

def load_results(results_jsonl):
    """Load accumulated rows from the results DB; dedupe by (G, env)."""
    seen = {};
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
    """Stage 3. Rank rows by a metric function `metric(iv, nature)->sortkey`
    (higher=better). `rows` may be dicts (from load_results) or tuples."""
    norm = []
    for r in rows:
        if isinstance(r, dict):
            norm.append((r["G"], r["pid"], r["nature"], tuple(r["iv"]), r["env"]))
        else:
            G_, P, nat_, iv, sp = r
            norm.append((G_, P, nat_, tuple(iv), None))
    norm.sort(key=lambda t: metric(t[3], t[2]), reverse=True)
    return norm[:top]


def n31(iv):
    return sum(1 for x in iv if x == 31)
