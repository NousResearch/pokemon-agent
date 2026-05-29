"""Deterministic RNG-manipulated shiny starter for Pokemon LeafGreen.

Gen 3's RNG is a plain LCG and the starter is rolled by **Method 1** (PID
then IVs, four consecutive ``Random()`` calls).  Because we hold a save
state captured on the "...want BULBASAUR? YES" prompt and can write
``gRngValue`` directly, the whole thing is deterministic:

    result = Method1( advance(written_seed, N) )

where ``N`` is a fixed offset (the number of RNG calls between writing the
seed and the PID roll, for our fixed input pattern).  So to obtain *any*
target Pokemon we:

  1. search the 2^32 seed space (pure math) for a generation-seed ``G`` whose
     Method-1 output is shiny + the nature/IVs we want, then
  2. write ``rewind(G, N)`` into ``gRngValue`` and replay the fixed pattern.

Gen 3 couples PID and IVs (same RNG calls), so for a *fixed* TID/SID shiny +
flawless is impossible — the achievable ceiling here is 4 perfect IVs.

  ⚠️  Runs INSIDE the devbox with the GBA venv (see docs/GBA_SETUP.md):
      distrobox enter devbox -- .venv-gba/bin/python shiny_leafgreen_starter.py ...

Typical use:
    # confirm the calibration still holds for the current input state
    ... shiny_leafgreen_starter.py --calibrate
    # enumerate the shiny space, cache it, show the best per nature
    ... shiny_leafgreen_starter.py --search
    # produce a specific target (PID from the search) and save a state
    ... shiny_leafgreen_starter.py --target-pid 0x5F7F19A3
    # or just take the best shiny of a given nature from the cache
    ... shiny_leafgreen_starter.py --nature Bold
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import mgba.core
import mgba.image
import mgba.log

from pokemon_agent.gba_state import load_state_file, save_state_file
from pokemon_agent.shiny_gen3 import (
    Gen3IVs, decrypt_block, gen_method1, is_shiny, ivs_from_decrypted, rewind,
)

ROOT = Path(__file__).resolve().parent
ROM = ROOT / "roms" / "Pokemon - LeafGreen Version (USA).gba"
# Pre-confirmation state: standing on the BULBASAUR "YES" prompt.
INPUT_STATE = ROOT / "roms" / "Pokemon - LeafGreen Version (USA).ss1"
OUT_STATE = ROOT / "roms" / "leafgreen_shiny_bulbasaur.ss1"
CACHE = ROOT / "_lg_shiny_bulba.npz"

# --- calibrated constants (LeafGreen USA, this input state) ---------------
GPLAYER_PARTY0 = 0x02024284   # gPlayerParty[0]
GRNGVALUE = 0x03005000        # gRngValue
PATTERN_FRAMES = 120          # fixed input window that reaches givemon
OFFSET_N = 90                 # RNG calls from written seed -> PID roll
SPECIES_BULBASAUR = 1
MON_SIZE = 100

NATURES = ["Hardy", "Lonely", "Brave", "Adamant", "Naughty", "Bold", "Docile",
           "Relaxed", "Impish", "Lax", "Timid", "Hasty", "Serious", "Jolly",
           "Naive", "Modest", "Mild", "Quiet", "Bashful", "Rash", "Calm",
           "Gentle", "Sassy", "Careful", "Quirky"]


# --------------------------------------------------------------------------
# emulator plumbing
# --------------------------------------------------------------------------

def new_core():
    mgba.log.silence()
    core = mgba.core.load_path(str(ROM))
    if core is None:
        raise SystemExit(f"mGBA failed to load {ROM}")
    fb = mgba.image.Image(*core.desired_video_dimensions())
    core.set_video_buffer(fb)
    core.reset()
    return core, fb


def read_mon(core) -> bytes:
    u32 = core.memory.u32
    return b"".join(u32[GPLAYER_PARTY0 + 4 * i].to_bytes(4, "little") for i in range(MON_SIZE // 4))


def decode_party0(core) -> tuple[int, int, int, Gen3IVs]:
    """Return (species, pid, otid, ivs) for party slot 0."""
    mon = read_mon(core)
    pid = int.from_bytes(mon[0:4], "little")
    otid = int.from_bytes(mon[4:8], "little")
    dec = decrypt_block(mon[0x20:0x20 + 48], pid, otid)
    species = int.from_bytes(dec[0:2], "little")
    return species, pid, otid, ivs_from_decrypted(dec)


def run_pattern(core, written_seed: int) -> tuple[int, int, int, Gen3IVs]:
    """Load INPUT_STATE, write ``gRngValue``, replay the fixed pattern, decode."""
    load_state_file(core, INPUT_STATE)
    core.memory.u32[GRNGVALUE] = written_seed & 0xFFFFFFFF
    for frame in range(PATTERN_FRAMES):
        core.set_keys(core.KEY_A) if (frame % 4) < 2 else core.set_keys()
        core.run_frame()
    return decode_party0(core)


# --------------------------------------------------------------------------
# calibration — re-derive TID/SID and confirm OFFSET_N from the input state
# --------------------------------------------------------------------------

def calibrate(core) -> tuple[int, int]:
    from pokemon_agent.shiny_gen3 import lcg_next

    def offset_for(V, pid, ivs):
        r1, r2 = pid & 0xFFFF, (pid >> 16) & 0xFFFF
        iv1 = ivs.hp | (ivs.attack << 5) | (ivs.defense << 10)
        iv2 = ivs.speed | (ivs.sp_attack << 5) | (ivs.sp_defense << 10)
        s, seq = V, []
        for _ in range(4000):
            s = lcg_next(s); seq.append((s >> 16) & 0xFFFF)
        for c in range(len(seq) - 4):
            if seq[c] == r1 and seq[c + 1] == r2:
                gap = "method1" if ((seq[c + 2] & 0x7FFF) == iv1 and (seq[c + 3] & 0x7FFF) == iv2) else "?"
                return c, gap
        return None, None

    tid = sid = None
    for V in (0x00000000, 0x11111111, 0xA3C59172):
        species, pid, otid, ivs = run_pattern(core, V)
        if species != SPECIES_BULBASAUR:
            print(f"  WARNING: V=0x{V:08X} produced species {species}, not Bulbasaur", file=sys.stderr)
        tid, sid = otid & 0xFFFF, (otid >> 16) & 0xFFFF
        off, meth = offset_for(V, pid, ivs)
        ok = (off == OFFSET_N and meth == "method1")
        print(f"  V=0x{V:08X} -> PID=0x{pid:08X} IVs={ivs.as_tuple()} "
              f"offset={off} {meth} {'OK' if ok else 'MISMATCH'}")
    print(f"  TID={tid} SID={sid}  (expected offset N={OFFSET_N}, Method 1)")
    return tid, sid


# --------------------------------------------------------------------------
# search — enumerate the shiny space (numpy)
# --------------------------------------------------------------------------

def search(tid: int, sid: int) -> None:
    import numpy as np
    A = np.uint64(0x41C64E6D); C = np.uint64(0x6073); M = np.uint64(0xFFFFFFFF)
    xb = np.uint64((tid ^ sid) & 0xFFFF)
    CHUNK = 1 << 22
    gs = []; pids = []; i1 = []; i2 = []
    for base in range(0, 1 << 32, CHUNK):
        G = np.arange(base, base + CHUNK, dtype=np.uint64)
        s1 = (G * A + C) & M; plo = s1 >> np.uint64(16)
        s2 = (s1 * A + C) & M; phi = s2 >> np.uint64(16)
        s3 = (s2 * A + C) & M; iv1 = (s3 >> np.uint64(16)) & np.uint64(0x7FFF)
        s4 = (s3 * A + C) & M; iv2 = (s4 >> np.uint64(16)) & np.uint64(0x7FFF)
        shiny = ((xb ^ phi ^ plo) & np.uint64(0xFFFF)) < np.uint64(8)
        idx = np.nonzero(shiny)[0]
        if idx.size:
            gs.append(G[idx].astype(np.uint32))
            pids.append(((phi << np.uint64(16)) | plo)[idx].astype(np.uint32))
            i1.append(iv1[idx].astype(np.uint16)); i2.append(iv2[idx].astype(np.uint16))
    G = np.concatenate(gs); PID = np.concatenate(pids)
    IV1 = np.concatenate(i1).astype(np.uint32); IV2 = np.concatenate(i2).astype(np.uint32)
    np.savez(CACHE, G=G, PID=PID, IV1=IV1, IV2=IV2)
    print(f"shiny seeds: {G.size}  cached -> {CACHE.name}")

    HP = IV1 & 31; AT = (IV1 >> 5) & 31; DF = (IV1 >> 10) & 31
    SP = IV2 & 31; SA = (IV2 >> 5) & 31; SD = (IV2 >> 10) & 31
    n31 = (HP == 31) * 1 + (AT == 31) + (DF == 31) + (SP == 31) + (SA == 31) + (SD == 31)
    total = HP + AT + DF + SP + SA + SD
    nat = PID % 25
    print(f"max perfect IVs among all shiny: {int(n31.max())}")
    for nm in ("Bold", "Modest", "Timid", "Calm", "Quiet", "Relaxed"):
        mask = nat == NATURES.index(nm)
        if not mask.any():
            continue
        j = int(np.argmax((n31 * 1000 + total) * mask))
        print(f"  {nm:<7} best: PID=0x{int(PID[j]):08X} "
              f"IVs=({int(HP[j])},{int(AT[j])},{int(DF[j])},{int(SP[j])},{int(SA[j])},{int(SD[j])}) "
              f"#31={int(n31[j])} total={int(total[j])}")


def g_for_pid(target_pid: int) -> int:
    import numpy as np
    if not CACHE.exists():
        raise SystemExit(f"no search cache at {CACHE}; run --search first")
    d = np.load(CACHE)
    idx = np.nonzero(d["PID"] == np.uint32(target_pid))[0]
    if not idx.size:
        raise SystemExit(f"PID 0x{target_pid:08X} not in shiny cache (not shiny for this TID/SID?)")
    return int(d["G"][idx[0]])


def best_g_for_nature(nature: str) -> tuple[int, int]:
    import numpy as np
    if nature not in NATURES:
        raise SystemExit(f"unknown nature {nature!r}")
    if not CACHE.exists():
        raise SystemExit(f"no search cache at {CACHE}; run --search first")
    d = np.load(CACHE)
    PID = d["PID"]; IV1 = d["IV1"].astype(np.uint32); IV2 = d["IV2"].astype(np.uint32)
    HP = IV1 & 31; AT = (IV1 >> 5) & 31; DF = (IV1 >> 10) & 31
    SP = IV2 & 31; SA = (IV2 >> 5) & 31; SD = (IV2 >> 10) & 31
    n31 = (HP == 31) * 1 + (AT == 31) + (DF == 31) + (SP == 31) + (SA == 31) + (SD == 31)
    total = HP + AT + DF + SP + SA + SD
    mask = (PID % 25) == NATURES.index(nature)
    if not mask.any():
        raise SystemExit(f"no shiny seed with nature {nature}")
    j = int(np.argmax((n31 * 1000 + total) * mask))
    return int(d["G"][j]), int(PID[j])


# --------------------------------------------------------------------------
# execute — write rewind(G, N), replay, verify, save state
# --------------------------------------------------------------------------

def execute(core, G: int) -> int:
    pid_exp, ivs_exp = gen_method1(G)
    V = rewind(G, OFFSET_N)
    print(f"target G=0x{G:08X}  write gRngValue=0x{V:08X}  "
          f"predict PID=0x{pid_exp:08X} IVs={ivs_exp.as_tuple()} nature={NATURES[pid_exp % 25]}")
    species, pid, otid, ivs = run_pattern(core, V)
    shiny = is_shiny(pid, otid & 0xFFFF, (otid >> 16) & 0xFFFF)
    ok = (species == SPECIES_BULBASAUR and pid == pid_exp and ivs.as_tuple() == ivs_exp.as_tuple())
    print(f"got     species={species} PID=0x{pid:08X} IVs={ivs.as_tuple()} "
          f"nature={NATURES[pid % 25]} shiny={shiny}  {'OK' if ok else 'MISMATCH'}")
    if not (ok and shiny):
        print("ERROR: result did not match prediction / not shiny", file=sys.stderr)
        return 1
    # advance through a little dialog so the saved state shows the receive,
    # then write a native (mGBA-app-loadable) savestate.
    for frame in range(40):
        core.set_keys(core.KEY_A) if (frame % 4) < 2 else core.set_keys()
        core.run_frame()
    save_state_file(core, OUT_STATE)
    print(f"saved shiny state -> {OUT_STATE}")
    print("Open it in the mGBA app to continue (you'll be mid-receive dialog).")
    return 0


def parse_args(argv=None):
    p = argparse.ArgumentParser(description="RNG-manip shiny LeafGreen starter.")
    p.add_argument("--calibrate", action="store_true",
                   help="Re-derive TID/SID and confirm the offset/method from the input state.")
    p.add_argument("--search", action="store_true",
                   help="Enumerate the shiny seed space, cache it, print best per nature.")
    p.add_argument("--target-pid", type=lambda s: int(s, 0), default=None,
                   help="Execute the seed whose Method-1 PID equals this (from the cache).")
    p.add_argument("--target-g", type=lambda s: int(s, 0), default=None,
                   help="Execute this exact generation-seed G.")
    p.add_argument("--nature", default=None,
                   help="Execute the best-IV shiny of this nature from the cache.")
    return p.parse_args(argv)


def main() -> int:
    args = parse_args()
    if not INPUT_STATE.exists():
        print(f"ERROR: input state not found: {INPUT_STATE}", file=sys.stderr)
        return 1

    if args.search and (args.target_pid or args.target_g or args.nature):
        pass  # search first, then execute below

    core, _ = new_core()

    if args.calibrate:
        calibrate(core)
        return 0

    tid = sid = None
    if args.search:
        tid, sid = calibrate(core)
        search(tid, sid)
        if not (args.target_pid or args.target_g or args.nature):
            return 0

    if args.target_g is not None:
        return execute(core, args.target_g)
    if args.target_pid is not None:
        return execute(core, g_for_pid(args.target_pid))
    if args.nature is not None:
        G, pid = best_g_for_nature(args.nature)
        print(f"best {args.nature} shiny: PID=0x{pid:08X}")
        return execute(core, G)

    print("nothing to do; pass --calibrate, --search, --nature, --target-pid or --target-g")
    return 0


if __name__ == "__main__":
    sys.exit(main())
