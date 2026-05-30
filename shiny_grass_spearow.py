"""Fully-offline near-perfect shiny Spearow hunt (Route 3, LeafGreen).

Ported to the deterministic offline-IV pipeline (pokemon_agent.gen3_rng VBlank
model + shiny_grass_core). Enumerates the shiny Spearow universe AND predicts IVs
offline (each candidate has two variants: iv1=o1/o2, iv2=o3 fixed), ranks against
the ceiling for a physical Fearow (Atk31 & Spe31 -> #31), then brute-realizes the
top-N across {state x pattern x offset} combos and reads true IVs to deliver an
exact, catchable result. No mass emulation.

Spearow is slots 0/2/6 (~35%) on Route 3. Same Route 3 envs as the Nidoran hunt.

    distrobox enter devbox -- .venv-gba/bin/python shiny_grass_spearow.py
"""
import time
import shiny_grass_core as C
from pokemon_agent.shiny_gen3 import rewind
from pokemon_agent.gba_state import save_state_file

TID, SID = 51376, 36462
SPECIES, SLOTS = 21, (0, 2, 6)
# physical-viable natures (none lower Atk or Spe): Adamant/Jolly + other +Atk/+Spe + neutrals
NATURES = (3, 13, 4, 1, 14, 11, 0, 12, 24)
CACHE = "cache_spearow.npz"
OUT_STATE = "roms/leafgreen_shiny_spearow_best.ss1"
TOPN = 100
SS5 = "roms/Pokemon - LeafGreen Version (USA).ss5"

# {state x pattern} combos spanning the achievable trigger-offset / threshold range.
G3 = "roms/leafgreen_route3_grass.ss1"
COMBOS = [
    ("ss5/LR1:1", SS5, "LR", 1, 1, [98, 96, 100, 94]),
    ("ss5/LR3:1", SS5, "LR", 3, 1, [100, 40]),
    ("ss5/LR2:1", SS5, "LR", 2, 1, [59, 30, 10, 20]),
    ("g3/LR2:1", G3, "LR", 2, 1, [71, 72, 73, 52, 74]),
    ("g3/LR1:1", G3, "LR", 1, 1, [98, 96, 100]),
    ("env01", "roms/envs/route3_env01.ss1", "LR", 2, 1, [39, 30, 10, 20]),
    ("env02", "roms/envs/route3_env02.ss1", "LR", 2, 1, [29, 10, 20]),
    ("env03", "roms/envs/route3_env03.ss1", "LR", 2, 1, [19, 10]),
]


def metric(iv, nat):
    # Fearow = fast physical: Atk31 & Spe31 first, then total #31, then ideal
    # nature (Jolly/Adamant), then overall bulk.
    hp, atk, df, spe, spa, spd = iv
    return ((atk == 31) + (spe == 31), C.n31(iv), 1 if nat in (3, 13) else 0, hp + df + spd)


def main():
    t0 = time.time()
    cands = C.enumerate_candidates(SPECIES, SLOTS, TID, SID, allowed_natures=NATURES, cache_path=CACHE)
    n = len(cands["G"])
    rows = []
    for i in range(n):
        nat = int(cands["nature"][i])
        o1, o2, o3 = int(cands["o1"][i]), int(cands["o2"][i]), int(cands["o3"][i])
        ivA = C._unpack_iv(o1, o3); ivB = C._unpack_iv(o2, o3)
        best_iv = max((ivA, ivB), key=lambda iv: metric(iv, nat))
        rows.append((int(cands["G"][i]), int(cands["pid"][i]), nat, best_iv))
    rows.sort(key=lambda r: metric(r[3], r[2]), reverse=True)
    print("offline ranked %d shiny Spearow candidates in %.1fs; top predicted:" % (n, time.time() - t0), flush=True)
    for G, P, nat, iv in rows[:8]:
        print("  PRED G=0x%08X %-7s IVs=%s #31=%d" % (G, C.NAT[nat], iv, C.n31(iv)), flush=True)

    t1 = time.time(); realized = []
    for G, P, nat, _bv in rows[:TOPN]:
        best = None
        for label, state, axis, hold, rel, offs in COMBOS:
            B = C._bundle(state)
            for off in offs:
                res = C._emulate(B, rewind(G, off), axis, hold, rel)
                if res and res[0] == P and res[2] == SPECIES:
                    iv = tuple(res[1])
                    if best is None or metric(iv, nat) > metric(best[0], nat):
                        best = (iv, label, state, axis, hold, rel, off)
                    break
        if best is not None:
            realized.append((G, P, nat, best))
    realized.sort(key=lambda r: metric(r[3][0], r[2]), reverse=True)
    print("\nrealized %d/%d in %.1fs; best realizable physical shiny Spearow:"
          % (len(realized), TOPN, time.time() - t1), flush=True)
    for G, P, nat, (iv, label, *_x) in realized[:12]:
        print("  G=0x%08X %-7s IVs(H,A,D,Sp,SpA,SpD)=%s #31=%d via %s"
              % (G, C.NAT[nat], iv, C.n31(iv), label), flush=True)

    if realized:
        G, P, nat, (iv, label, state, axis, hold, rel, off) = realized[0]
        B = C._bundle(state)
        res = C._emulate(B, rewind(G, off), axis, hold, rel)
        if res and res[0] == P and tuple(res[1]) == iv:
            save_state_file(B["core"], OUT_STATE)
            print("\nBEST: G=0x%08X %s IVs=%s via %s -> saved %s (total %.1fs)"
                  % (G, C.NAT[nat], iv, label, OUT_STATE, time.time() - t0), flush=True)


if __name__ == "__main__":
    main()
