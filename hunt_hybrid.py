"""Hybrid wild-shiny hunt (Route B): enumerate offline, calibrate the env under
the deterministic trigger, predict IVs EXACTLY offline for non-boundary
candidates, and confirm ONLY the rare boundary candidates in-emulator.

    distrobox enter devbox -- .venv-gba/bin/python hunt_hybrid.py [species] [slot] [state]
"""
import sys
import time

from pokemon_agent.gba_calibrate import calibrate_env
from pokemon_agent.gba_trigger import fixed_trigger, make_bundle
from pokemon_agent.shiny_gen3 import rewind
from pokemon_agent.wild_enumerate import (
    NAT,
    enumerate_candidates,
    n31,
    predict_env_exact,
)

TID, SID = 51376, 36462
SPECIES = int(sys.argv[1]) if len(sys.argv) > 1 else 32          # Nidoran-male
SLOTS = (int(sys.argv[2]),) if len(sys.argv) > 2 else (10,)
STATE = sys.argv[3] if len(sys.argv) > 3 else "roms/leafgreen_route3_grass.ss1"
CACHE = "cache_hybrid_%d.npz" % SPECIES


def phys_viable(nat):
    inc, dec = nat // 5, nat % 5
    return not ((dec == 0 and inc != 0) or (dec == 2 and inc != 2))


def metric(iv, nat):
    hp, atk, df, spe, spa, spd = iv
    return ((atk == 31) + (spe == 31), n31(iv), 1 if nat in (3, 13) else 0, hp + df + spd)


def main():
    t0 = time.time()
    cands = enumerate_candidates(SPECIES, SLOTS, TID, SID, cache_path=CACHE)
    cal = calibrate_env(STATE, n=160)
    rows = predict_env_exact(cands, cal["ta"], cal["tb_lo"], cal["tb_hi"], cal["ambig_ranges"])
    rows = [r for r in rows if phys_viable(r[2])]
    rows.sort(key=lambda r: metric(r[3], r[2]), reverse=True)
    n_bdy = sum(1 for r in rows if r[4])
    print("\n%d physical candidates: %d exact-offline, %d boundary(confirm) (%.0f%% offline)"
          % (len(rows), len(rows) - n_bdy, n_bdy, 100 * (len(rows) - n_bdy) / max(len(rows), 1)),
          flush=True)
    print("top predicted (boundary*=confirm needed):", flush=True)
    for G, pid, nat, iv, bdy in rows[:12]:
        print("  G=0x%08X %-7s IVs=%s #31=%d%s"
              % (G, NAT[nat], iv, n31(iv), "  *boundary" if bdy else ""), flush=True)

    # Confirm ONLY the boundary candidates among the top-K (the offline ones are trusted).
    topk = rows[:40]
    bdy_top = [r for r in topk if r[4]]
    B = make_bundle(STATE); off = cal["dominant_offset"]
    confirmed = 0
    for G, pid, nat, iv, _b in bdy_top:
        res = fixed_trigger(B, rewind(int(G), off))
        if res and res[0] == pid:
            confirmed += 1
    print("\nconfirmed %d/%d boundary candidates in top-40 (offline ones needed no emulator); %.1fs"
          % (confirmed, len(bdy_top), time.time() - t0), flush=True)


if __name__ == "__main__":
    main()
