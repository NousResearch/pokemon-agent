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
        for _ in range(200):
            s1 = stp(cur); lo = s1 >> SIX; s2 = stp(s1); hi = s2 >> SIX
            p = ((hi << SIX) | lo) & M
            nm = (~matched) & ((p % np.uint64(25)) == tgt); pid[nm] = p[nm]; matched |= nm; cur = s2
            if matched.all():
                break
        pl = pid & np.uint64(0xFFFF); ph = pid >> SIX
        sh = matched & (((xb ^ ph ^ pl) & np.uint64(0xFFFF)) < np.uint64(8))
        for e in np.nonzero(sh)[0]:
            out.append((int(Gs[e]), int(pid[e]), int(tgt[e])))
    return out


def enumerate_candidates(species, slots, tid, sid, allowed_natures=tuple(range(25)),
                         cache_path=None, workers=None, verbose=True):
    """Stage 1. Enumerate all shiny gen-seeds G producing `species` (via `slots`)
    with an allowed nature, for this TID/SID. Returns (G, pid, nature) numpy
    arrays. Cached to `cache_path` (.npz) — state-independent, compute once."""
    import numpy as np
    if cache_path and os.path.exists(cache_path):
        d = np.load(cache_path)
        if verbose:
            print("Stage1: loaded %d cached candidates from %s" % (len(d["G"]), cache_path), flush=True)
        return d["G"], d["pid"], d["nature"]
    NW = workers or os.cpu_count(); span = (1 << 32) // NW
    ranges = [(i * span, (i + 1) * span if i < NW - 1 else (1 << 32), 1 << 22,
               tid, sid, tuple(slots), tuple(allowed_natures)) for i in range(NW)]
    out = []; t0 = time.time()
    with ProcessPoolExecutor(NW) as ex:
        for r in ex.map(_enum_range, ranges):
            out.extend(r)
    G = np.array([o[0] for o in out], dtype=np.uint64)
    pid = np.array([o[1] for o in out], dtype=np.uint64)
    nat = np.array([o[2] for o in out], dtype=np.uint8)
    if verbose:
        print("Stage1: enumerated %d candidates in %.1fs" % (len(out), time.time() - t0), flush=True)
    if cache_path:
        np.savez(cache_path, G=G, pid=pid, nature=nat, species=species, tid=tid, sid=sid)
        if verbose:
            print("Stage1: cached -> %s" % cache_path, flush=True)
    return G, pid, nat


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
    """Stage 2. Reproduce every candidate in ONE timing env (state + jiggle
    pattern + offsets), reading true IVs. Appends rows to `results_jsonl` tagged
    with `env_id`. Returns the rows (G, pid, nature, iv, species)."""
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
