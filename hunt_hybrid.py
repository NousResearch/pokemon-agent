"""Unified wild-shiny hunt (Route B). One interface for BOTH high-rate and
low-rate species:

  1. enumerate offline (cached) and RANK by each candidate's BEST-POSSIBLE IV
     over its offset-variants (iv1 in {o1,o2}, iv2 in {o2,o3,o4}) — fully offline,
     no mass emulation;
  2. REALIZE the top-N by reproducing them across a set of (state, pattern,
     offset) combos and reading their TRUE IVs — this resolves the seed-dependent
     trigger offset (which is NOT offline-predictable), so the GLOBAL best is
     found whether the good candidates fire at the dominant offset (high-rate) or
     scatter across offsets (low-rate);
  3. deliver the best realized as a catchable encounter state.

    distrobox enter devbox -- .venv-gba/bin/python hunt_hybrid.py [species] [slot]
"""
import sys
import time

from pokemon_agent.gba_state import save_state_file
from pokemon_agent.gba_trigger import jiggle_trigger, make_bundle
from pokemon_agent.shiny_gen3 import rewind
from pokemon_agent.wild_enumerate import NAT, best_possible_iv, enumerate_candidates, n31

TID, SID = 51376, 36462
SS5 = "roms/Pokemon - LeafGreen Version (USA).ss5"
G3 = "roms/leafgreen_route3_grass.ss1"

# (label, state, axis, hold, rel, offsets) combos spanning the achievable
# trigger-offset range so candidates that fire at scattered offsets are realized.
DEFAULT_COMBOS = [
    ("g3/LR2:1", G3, "LR", 2, 1, [71, 72, 73, 52, 74]),
    ("g3/LR1:1", G3, "LR", 1, 1, [98, 96, 100]),
    ("ss5/LR2:1", SS5, "LR", 2, 1, [59, 30, 10, 20]),
    ("ss5/LR1:1", SS5, "LR", 1, 1, [98, 96, 100, 94]),
    ("ss5/LR3:1", SS5, "LR", 3, 1, [100, 40]),
    ("env01", "roms/envs/route3_env01.ss1", "LR", 2, 1, [39, 30, 10, 20]),
    ("env02", "roms/envs/route3_env02.ss1", "LR", 2, 1, [29, 10, 20]),
    ("env03", "roms/envs/route3_env03.ss1", "LR", 2, 1, [19, 10]),
]


def run_unified_hunt(species, slots, metric, phys_viable, cache, out_state,
                     combos=DEFAULT_COMBOS, topn=120, label="mon", verbose=True):
    """Returns (realized_sorted, best). best = (G, pid, nature, iv, combo_label)."""
    t0 = time.time()
    c = enumerate_candidates(species, slots, TID, SID, cache_path=cache)
    rows = []
    for i in range(len(c["G"])):
        nat = int(c["nature"][i])
        if not phys_viable(nat):
            continue
        bi = best_possible_iv(int(c["o1"][i]), int(c["o2"][i]), int(c["o3"][i]),
                              int(c["o4"][i]), nat, metric)
        rows.append((int(c["G"][i]), int(c["pid"][i]), nat, bi))
    rows.sort(key=lambda r: metric(r[3], r[2]), reverse=True)
    if verbose:
        print("[%s] ranked %d physical candidates offline in %.1fs; realizing top %d..."
              % (label, len(rows), time.time() - t0, topn), flush=True)

    t1 = time.time(); realized = []
    for G, pid, nat, _bv in rows[:topn]:
        best = None
        for clabel, state, axis, hold, rel, offs in combos:
            B = make_bundle(state); done = False
            for off in offs:
                res = jiggle_trigger(B, rewind(G, off), axis, hold, rel)
                if res and res[0] == pid and res[2] == species:
                    iv = tuple(res[1])
                    if best is None or metric(iv, nat) > metric(best[0], nat):
                        best = (iv, clabel, state, axis, hold, rel, off)
                    done = True; break
            if done:
                break
        if best is not None:
            realized.append((G, pid, nat, best))
    realized.sort(key=lambda r: metric(r[3][0], r[2]), reverse=True)
    if verbose:
        print("[%s] realized %d/%d in %.1fs; best realizable:"
              % (label, len(realized), topn, time.time() - t1), flush=True)
        for G, pid, nat, (iv, clabel, *_x) in realized[:10]:
            print("  G=0x%08X %-7s IVs=%s #31=%d via %s"
                  % (G, NAT[nat], iv, n31(iv), clabel), flush=True)

    best = None
    if realized:
        G, pid, nat, (iv, clabel, state, axis, hold, rel, off) = realized[0]
        B = make_bundle(state)
        res = jiggle_trigger(B, rewind(G, off), axis, hold, rel)
        if res and res[0] == pid and tuple(res[1]) == iv:
            save_state_file(B["core"], out_state)
        best = (G, pid, nat, iv, clabel)
        if verbose:
            print("[%s] BEST: G=0x%08X %s IVs=%s #31=%d -> %s (%.1fs)"
                  % (label, G, NAT[nat], iv, n31(iv), out_state, time.time() - t0), flush=True)
    return realized, best


if __name__ == "__main__":
    sp = int(sys.argv[1]) if len(sys.argv) > 1 else 32
    sl = (int(sys.argv[2]),) if len(sys.argv) > 2 else (10,)

    def _phys(nat):
        inc, dec = nat // 5, nat % 5
        return not ((dec == 0 and inc != 0) or (dec == 2 and inc != 2))

    def _metric(iv, nat):
        hp, atk, df, spe, spa, spd = iv
        return ((atk == 31) + (spe == 31), n31(iv), 1 if nat in (3, 13) else 0, hp + df + spd)

    run_unified_hunt(sp, sl, _metric, _phys, "cache_hybrid_%d.npz" % sp,
                     "roms/leafgreen_hybrid_%d.ss1" % sp, label="sp%d" % sp)
