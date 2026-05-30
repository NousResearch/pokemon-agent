"""Emulator layer for the wild-shiny pipeline (REQUIRES mgba; devbox only).

Owns the single source of the encounter trigger + per-core bundle + verify/
confirm helpers, consolidating what used to be duplicated across
shiny_grass_core / gba_iv_struct / validate_iv_prediction. The deterministic
fixed-phase trigger + cycle-exact instrumentation (Route B) are added here.
"""
from __future__ import annotations

import json
import os
import time
from concurrent.futures import ProcessPoolExecutor

ROM = "roms/Pokemon - LeafGreen Version (USA).gba"
ENEMY = 0x0202402C   # gEnemyParty[0]
RNG = 0x03005000     # gRngValue
VCOUNT = 0x04000006  # DISPSTAT VCOUNT (current scanline)

_B = {}  # per-process core bundle, keyed by state path


def make_bundle(state, rom=ROM):
    """Load the ROM + a save state into an mGBA core; cache per state path."""
    if state in _B:
        return _B[state]
    import mgba.core
    import mgba.image
    import mgba.log

    from pokemon_agent.gba_state import load_state_file
    mgba.log.silence()
    core = mgba.core.load_path(rom)
    fb = mgba.image.Image(*core.desired_video_dimensions())
    core.set_video_buffer(fb); core.reset(); load_state_file(core, state)
    B = dict(core=core, fb=fb, mem=core.memory, base=bytes(core.save_raw_state()),
             L=core.KEY_LEFT, R=core.KEY_RIGHT, U=core.KEY_UP, D=core.KEY_DOWN)
    _B[state] = B
    return B


def _read_enemy(mem):
    from pokemon_agent.shiny_gen3 import decrypt_block, ivs_from_decrypted
    mon = b"".join(mem.u32[ENEMY + 4 * k].to_bytes(4, "little") for k in range(25))
    pid = int.from_bytes(mon[0:4], "little"); otid = int.from_bytes(mon[4:8], "little")
    try:
        dec = decrypt_block(mon[0x20:0x20 + 48], pid, otid)
    except Exception:
        return None
    sp = int.from_bytes(dec[0:2], "little")
    return pid, ivs_from_decrypted(dec).as_tuple(), sp


def jiggle_trigger(B, V, axis="LR", hold=2, rel=1, cap=70, settle=20):
    """Legacy variable-phase trigger: write V into gRngValue, mash a left/right (or
    up/down) jiggle until an encounter fires, read the wild mon. Returns
    (pid, iv_tuple, species) or None. φ0 jitters seed-to-seed under this trigger."""
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
    for _ in range(settle):
        core.run_frame()
    return _read_enemy(mem)


# Back-compat alias (older scripts call C._emulate).
_emulate = jiggle_trigger


def fixed_trigger(B, V, step_frames=16, cap_frames=600, settle=20):
    """Deterministic fixed-phase trigger (Route B): write V, then take identical
    back-and-forth full steps (down/up, ``step_frames`` each) until an encounter
    fires. Every step's encounter check runs at the SAME intra-frame scanline, so
    the generation phase phi0 is seed-independent -> the IV-threshold is SHARP (no
    ambiguous band; verified band=0 vs jiggle's ~1-3). Stays on two tiles (high
    yield). Returns (pid, iv_tuple, species) or None."""
    core = B["core"]; mem = B["mem"]
    core.load_raw_state(B["base"]); mem.u32[RNG] = V & 0xFFFFFFFF; bp = mem.u32[ENEMY]
    D, U = B["D"], B["U"]
    frames = 0; i = 0; hit = False
    while frames < cap_frames:
        key = D if (i % 2 == 0) else U
        for _ in range(step_frames):
            core.set_keys(key); core.run_frame(); frames += 1
            if mem.u32[ENEMY] != bp:
                hit = True; break
        if hit:
            break
        i += 1
    if not hit:
        return None
    for _ in range(settle):
        core.run_frame()
    return _read_enemy(mem)


def _verify_chunk(args):
    from pokemon_agent.shiny_gen3 import rewind
    sub, state, offsets, axis, hold, rel, target_sp = args
    B = make_bundle(state); rows = []
    for G, P, nat in sub:
        for off in offsets:
            res = jiggle_trigger(B, rewind(int(G), off), axis, hold, rel)
            if res and res[0] == P and (target_sp is None or res[2] == target_sp):
                rows.append((int(G), int(P), int(nat), list(res[1]), res[2])); break
    return rows


def verify_env(candidates, state, offsets, env_id, axis="LR", hold=2, rel=1,
               target_species=None, results_jsonl=None, workers=None, verbose=True):
    """Mass-verify (validation / legacy): reproduce every candidate in ONE env,
    reading true IVs. `candidates` is the enumerate dict or a (G,pid,nature) tuple."""
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
        print("Stage2[%s]: %d/%d reproduced in %.1fs"
              % (env_id, len(rows), len(cand), time.time() - t0), flush=True)
    if results_jsonl:
        with open(results_jsonl, "a") as f:
            for G_, P, nat_, iv, sp in rows:
                f.write(json.dumps({"env": env_id, "G": G_, "pid": P, "nature": nat_,
                                    "iv": iv, "species": sp}) + "\n")
    return rows


def confirm_candidates(ranked_rows, state, offsets, axis="LR", hold=2, rel=1,
                       target_species=None, k=30, verbose=True):
    """Emulate the top-`k` ranked predicted candidates to read their TRUE IVs —
    the safety net for the ambiguous band (removed once Route B validates band=0).
    `ranked_rows` best-first (G, pid, nature, pred_iv, *extra)."""
    from pokemon_agent.shiny_gen3 import rewind
    B = make_bundle(state); seen = set(); confirmed = []; tried = 0; t0 = time.time()
    for row in ranked_rows:
        G, P, nat = row[0], row[1], row[2]
        if G in seen:
            continue
        seen.add(G); tried += 1
        if tried > k:
            break
        for off in offsets:
            res = jiggle_trigger(B, rewind(int(G), off), axis, hold, rel)
            if res and res[0] == P and (target_species is None or res[2] == target_species):
                confirmed.append((int(G), int(P), int(nat), tuple(res[1]), res[2])); break
    if verbose:
        print("confirm: %d/%d top candidates reproduced in %.1fs"
              % (len(confirmed), min(tried, k), time.time() - t0), flush=True)
    return confirmed
