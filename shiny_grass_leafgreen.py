"""Deterministic emulation search for a shiny wild Mankey in LeafGreen.

Unlike the starter, Gen-3 *wild* encounters can't be one-shot manipulated
from a mid-game save state: the RNG advances every frame and overwriting
the seed also re-decides when the encounter triggers, so the PID rolls at a
non-constant offset (no clean offline model).  See docs/GBA_SETUP.md.

So we search instead — but deterministically: each trial writes a 32-bit
seed into ``gRngValue`` at the in-grass state, jiggles the player left/right
in place (turning triggers the encounter check every ~3 frames, ~7x more
encounters/sec than walking whole tiles) until
an encounter, and reads the wild mon.  Shininess can't be predicted without
emulating, so we parallelise across cores and keep every shiny Mankey found
within a time budget, then pick the best IVs for a physical attacker.

The winning seed fully reproduces the result (load state2, write seed, walk).

  ⚠️  Runs INSIDE the devbox with the GBA venv:
      distrobox enter devbox -- .venv-gba/bin/python shiny_grass_leafgreen.py --seconds 1200
"""

from __future__ import annotations

import argparse
import os
import random
import sys
import time
from concurrent.futures import ProcessPoolExecutor

from pathlib import Path

ROOT = Path(__file__).resolve().parent
ROM = str(ROOT / "roms" / "Pokemon - LeafGreen Version (USA).gba")
STATE = str(ROOT / "roms" / "Pokemon - LeafGreen Version (USA).ss2")
OUT_STATE = str(ROOT / "roms" / "leafgreen_shiny_mankey.ss1")

ENEMY = 0x0202402C          # gEnemyParty[0]
RNGVALUE = 0x03005000       # gRngValue
MANKEY = 56
# "Jiggle" the player left/right in place: turning triggers the wild-encounter
# check every ~3 frames (hold 2 / release 1), far more often than a full walk
# step (~22 frames) — empirically ~141 frames to an encounter vs ~225 walking,
# and it reliably triggers (almost no dead-end trials).  Verified all encounters
# are valid wild species.
JIGGLE_HOLD = 2
JIGGLE_REL = 1
JIGGLE_CAP = 450            # frames per trial before giving up on an encounter
SETTLE = 16                 # frames after PID appears, so IVs/level populate
TID = 51376
SID = 36462

NATURES = ["Hardy", "Lonely", "Brave", "Adamant", "Naughty", "Bold", "Docile",
           "Relaxed", "Impish", "Lax", "Timid", "Hasty", "Serious", "Jolly",
           "Naive", "Modest", "Mild", "Quiet", "Bashful", "Rash", "Calm",
           "Gentle", "Sassy", "Careful", "Quirky"]


def _decode_enemy(core):
    from pokemon_agent.shiny_gen3 import decrypt_block, ivs_from_decrypted
    u32 = core.memory.u32
    mon = b"".join(u32[ENEMY + 4 * i].to_bytes(4, "little") for i in range(25))
    pid = int.from_bytes(mon[0:4], "little")
    otid = int.from_bytes(mon[4:8], "little")
    chk = int.from_bytes(mon[0x1C:0x1E], "little")
    try:
        dec = decrypt_block(mon[0x20:0x20 + 48], pid, otid)
    except Exception:
        return None
    if sum(int.from_bytes(dec[i:i + 2], "little") for i in range(0, 48, 2)) & 0xFFFF != chk:
        return None
    species = int.from_bytes(dec[0:2], "little")
    if not (1 <= species <= 411):
        return None
    return species, mon[0x54], pid, ivs_from_decrypted(dec)


def _make_runner():
    """Build a core bound to STATE; return (core, base_raw, step_fn)."""
    import mgba.core, mgba.image, mgba.log
    from pokemon_agent.gba_state import load_state_file
    mgba.log.silence()
    core = mgba.core.load_path(ROM)
    fb = mgba.image.Image(*core.desired_video_dimensions())
    core.set_video_buffer(fb)
    core.reset()
    load_state_file(core, STATE)
    base = bytes(core.save_raw_state())
    return core, base


def _run_seed(core, base, V):
    """Write V at the in-grass state, walk until encounter; return enemy or None."""
    core.load_raw_state(base)
    core.memory.u32[RNGVALUE] = V & 0xFFFFFFFF
    base_pid = core.memory.u32[ENEMY]
    frames = 0
    i = 0
    triggered = False
    period = JIGGLE_HOLD + JIGGLE_REL
    while frames < JIGGLE_CAP:
        btn = core.KEY_LEFT if (i % 2 == 0) else core.KEY_RIGHT
        for ph in range(period):
            core.set_keys(btn) if ph < JIGGLE_HOLD else core.set_keys()
            core.run_frame(); frames += 1
            if core.memory.u32[ENEMY] != base_pid:
                triggered = True
                break
        if triggered:
            break
        i += 1
    if not triggered:
        return None
    for _ in range(SETTLE):
        core.run_frame()
    return _decode_enemy(core)


def _is_shiny(pid):
    return ((TID ^ SID ^ (pid >> 16) ^ (pid & 0xFFFF)) & 0xFFFF) < 8


FINDS_LOG = str(ROOT / "leafgreen_mankey_finds.jsonl")


def _worker(args):
    import json
    wid, deadline, seed0, count_target = args
    core, base = _make_runner()
    rng = random.Random((seed0 ^ (wid * 0x9E3779B1)) & 0xFFFFFFFF)
    finds = []
    trials = enc = 0
    while time.time() < deadline:
        V = rng.getrandbits(32)
        r = _run_seed(core, base, V)
        trials += 1
        if r is None:
            continue
        enc += 1
        species, level, pid, ivs = r
        if species == MANKEY and _is_shiny(pid):
            iv = ivs.as_tuple()
            finds.append((V, pid, level, iv))
            # Durable, append-only log so a long run's progress survives.
            try:
                with open(FINDS_LOG, "a") as f:
                    f.write(json.dumps({
                        "ts": time.time(), "V": f"0x{V:08X}", "pid": f"0x{pid:08X}",
                        "nature": NATURES[pid % 25], "level": level, "ivs": list(iv),
                        "score": list(_score(pid, iv)),
                    }) + "\n")
            except OSError:
                pass
    return wid, trials, enc, finds


def _phys_ok(nature_idx):
    inc, dec = nature_idx // 5, nature_idx % 5  # 0Atk 1Def 2Spe 3SpA 4SpD
    lowers_atk = (dec == 0 and inc != 0)
    lowers_spe = (dec == 2 and inc != 2)
    return not (lowers_atk or lowers_spe)


def _score(pid, ivs):
    hp, atk, df, spe, spa, spd = ivs
    nat = pid % 25
    perfect_as = (atk == 31) + (spe == 31)
    pref = 1 if NATURES[nat] in ("Jolly", "Adamant") else 0
    return (perfect_as, atk + spe, pref, hp + df + spd)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seconds", type=int, default=1200, help="search wall-clock budget")
    ap.add_argument("--workers", type=int, default=os.cpu_count())
    ap.add_argument("--calibrate", action="store_true", help="20s single-core rate check")
    ap.add_argument("--replay", type=lambda s: int(s, 0), default=None,
                    help="reproduce a specific winning seed and save the battle state")
    args = ap.parse_args()

    if args.replay is not None:
        core, base = _make_runner()
        r = _run_seed(core, base, args.replay)
        if r is None:
            print("replay: no encounter for that seed", file=sys.stderr); return 1
        species, level, pid, ivs = r
        print(f"replay V=0x{args.replay:08X}: species={species} L{level} "
              f"PID=0x{pid:08X} nature={NATURES[pid % 25]} IVs={ivs.as_tuple()} "
              f"shiny={_is_shiny(pid)}")
        if species == MANKEY and _is_shiny(pid):
            from pokemon_agent.gba_state import save_state_file
            save_state_file(core, OUT_STATE)
            print(f"saved battle state -> {OUT_STATE}")
        return 0

    if args.calibrate:
        args.seconds, args.workers = 20, 1

    deadline = time.time() + args.seconds
    seed0 = random.getrandbits(32)
    print(f"searching {args.seconds}s on {args.workers} workers (seed0=0x{seed0:08X})...")
    tasks = [(w, deadline, seed0, 0) for w in range(args.workers)]
    all_finds = []; trials = enc = 0
    with ProcessPoolExecutor(max_workers=args.workers) as ex:
        for wid, t, e, finds in ex.map(_worker, tasks):
            trials += t; enc += e; all_finds.extend(finds)

    rate = trials / args.seconds
    print(f"trials={trials} ({rate:.0f}/s), encounters={enc}, shiny Mankeys={len(all_finds)}")
    if not all_finds:
        print("no shiny Mankey in budget; re-run or raise --seconds")
        return 0

    phys = [f for f in all_finds if _phys_ok(f[1] % 25)] or all_finds
    phys.sort(key=lambda f: _score(f[1], f[3]), reverse=True)
    print("\ntop shiny Mankeys (physical-usable nature, best Atk+Spe first):")
    for V, pid, level, iv in phys[:8]:
        print(f"  V=0x{V:08X} nature={NATURES[pid % 25]:<8} L{level} IVs(H,A,D,Sp,SpA,SpD)={iv}")
    best = phys[0]
    print(f"\nBEST: V=0x{best[0]:08X} nature={NATURES[best[1] % 25]} IVs={best[3]}")
    # Auto-reproduce the best and save the battle state, so a long unattended
    # run finishes with a usable result.
    core, base = _make_runner()
    r = _run_seed(core, base, best[0])
    if r is not None and r[0] == MANKEY and _is_shiny(r[2]):
        from pokemon_agent.gba_state import save_state_file
        save_state_file(core, OUT_STATE)
        print(f"saved battle state -> {OUT_STATE}")
    print(f"reproduce:  shiny_grass_leafgreen.py --replay 0x{best[0]:08X}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
