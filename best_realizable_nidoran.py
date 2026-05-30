"""Find and deliver the BEST REALIZABLE physical shiny Nidoran-male.

Offline (gen3_rng VBlank model) each candidate has two IV variants (iv1=o1 vs o2;
iv2=o3 fixed). Which variant a given env realizes depends on its trigger offset's
threshold T (loop<T -> o1, loop>=T -> o2). The achievable offset range (via tile
states x jiggle patterns) spans T ~ [18,59], so most candidates can realize BOTH
variants. We rank the space offline by the better variant, then brute-realize the
top-N across {state x pattern x offset} combos, read true IVs, and deliver the
global best realizable one as a catchable encounter state.

    distrobox enter devbox -- .venv-gba/bin/python best_realizable_nidoran.py
"""
import os, time
import shiny_grass_core as C
from pokemon_agent.shiny_gen3 import rewind
from pokemon_agent.gba_state import save_state_file

TID, SID = 51376, 36462
SPECIES, SLOTS = 32, (10,)
CACHE = "cache_nidoranm.npz"
OUT_STATE = "roms/leafgreen_shiny_nidoranm_best.ss1"
TOPN = 120
SS5 = "roms/Pokemon - LeafGreen Version (USA).ss5"

# (label, state, axis, hold, rel, offsets-to-try) spanning the achievable T range:
# high-offset/low-T (variant B) ... low-offset/high-T (variant A), + repro coverage.
COMBOS = [
    ("ss5/LR1:1", SS5, "LR", 1, 1, [98, 96, 100, 94]),
    ("ss5/LR3:1", SS5, "LR", 3, 1, [100, 40]),
    ("ss5/LR2:1", SS5, "LR", 2, 1, [59, 30, 10, 20]),
    ("env01", "roms/envs/route3_env01.ss1", "LR", 2, 1, [39, 30, 10, 20]),
    ("env02", "roms/envs/route3_env02.ss1", "LR", 2, 1, [29, 10, 20]),
    ("env03", "roms/envs/route3_env03.ss1", "LR", 2, 1, [19, 10]),
]


def phys_viable(nat):
    inc, dec = nat // 5, nat % 5
    return not ((dec == 0 and inc != 0) or (dec == 2 and inc != 2))


def metric(iv, nat):
    hp, atk, df, spe, spa, spd = iv
    return ((atk == 31) + (spe == 31), C.n31(iv), 1 if nat in (3, 13) else 0, atk + spe, hp)


def main():
    t0 = time.time()
    cands = C.enumerate_candidates(SPECIES, SLOTS, TID, SID, cache_path=CACHE)
    n = len(cands["G"])
    rows = []
    for i in range(n):
        nat = int(cands["nature"][i])
        if not phys_viable(nat):
            continue
        o1, o2, o3 = int(cands["o1"][i]), int(cands["o2"][i]), int(cands["o3"][i])
        ivA = C._unpack_iv(o1, o3); ivB = C._unpack_iv(o2, o3)
        best_iv = max((ivA, ivB), key=lambda iv: metric(iv, nat))
        rows.append((int(cands["G"][i]), int(cands["pid"][i]), nat, best_iv))
    rows.sort(key=lambda r: metric(r[3], r[2]), reverse=True)
    print("offline ranked %d physical candidates in %.1fs; realizing top %d..."
          % (len(rows), time.time() - t0, TOPN), flush=True)

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
    print("realized %d/%d candidates in %.1fs; best realizable physical Nidoran-male:"
          % (len(realized), TOPN, time.time() - t1), flush=True)
    for G, P, nat, (iv, label, *_x) in realized[:12]:
        print("  G=0x%08X %-7s IVs=%s #31=%d via %s" % (G, C.NAT[nat], iv, C.n31(iv), label), flush=True)

    if realized:
        G, P, nat, (iv, label, state, axis, hold, rel, off) = realized[0]
        B = C._bundle(state)
        res = C._emulate(B, rewind(G, off), axis, hold, rel)
        if res and res[0] == P and tuple(res[1]) == iv:
            save_state_file(B["core"], OUT_STATE)
            print("\nBEST REALIZABLE: G=0x%08X %s IVs=%s via %s -> saved %s (total %.1fs)"
                  % (G, C.NAT[nat], iv, label, OUT_STATE, time.time() - t0), flush=True)
        else:
            print("\n(could not re-reproduce best for save; IVs=%s)" % (iv,), flush=True)


if __name__ == "__main__":
    main()
