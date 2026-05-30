"""Hybrid wild-shiny hunt engine (Route B). Enumerate offline, calibrate the env
under the deterministic trigger, predict IVs EXACTLY offline for non-boundary
candidates, and emulate ONLY the rare boundary candidates (+ one reproduction of
the winner to save a catchable state). Imported by hunt_nidoranm / shiny_grass_spearow.

    distrobox enter devbox -- .venv-gba/bin/python hunt_hybrid.py [species] [slot] [state]
"""
import sys
import time

from pokemon_agent.gba_calibrate import calibrate_env
from pokemon_agent.gba_state import save_state_file
from pokemon_agent.gba_trigger import fixed_trigger, make_bundle
from pokemon_agent.shiny_gen3 import rewind
from pokemon_agent.wild_enumerate import NAT, enumerate_candidates, n31, predict_env_exact

TID, SID = 51376, 36462


def run_hybrid_hunt(species, slots, state, metric, phys_viable, cache, out_state,
                    topk=40, calib_n=200, label="mon"):
    """Returns (ranked_rows, best). best = (G, pid, nature, true_iv, was_boundary)
    or None. Emulator is used only for boundary candidates in the top-K and one
    reproduction of the winner (to save its encounter state)."""
    t0 = time.time()
    cands = enumerate_candidates(species, slots, TID, SID, cache_path=cache)
    cal = calibrate_env(state, n=calib_n)
    rows = predict_env_exact(cands, cal["ta"], cal["tb_lo"], cal["tb_hi"], cal["ambig_ranges"])
    rows = [r for r in rows if phys_viable(r[2])]
    rows.sort(key=lambda r: metric(r[3], r[2]), reverse=True)
    n_bdy = sum(1 for r in rows if r[4])
    print("\n[%s] %d physical candidates: %d exact-offline, %d boundary (%.1f%% need NO emulator)"
          % (label, len(rows), len(rows) - n_bdy, n_bdy,
             100 * (len(rows) - n_bdy) / max(len(rows), 1)), flush=True)

    B = make_bundle(state); off = cal["dominant_offset"]; offsets = [off, off - 1, off + 1]

    # Resolve boundary candidates in the top-K to their TRUE IVs (the only IV-read
    # emulation in the hunt); non-boundary candidates are trusted exactly.
    resolved = []
    n_confirm = 0
    for G, pid, nat, iv, bdy in rows[:topk]:
        if not bdy:
            resolved.append((G, pid, nat, iv, False))
            continue
        n_confirm += 1
        true_iv = None
        for o in offsets:
            res = fixed_trigger(B, rewind(int(G), o))
            if res and res[0] == pid and res[2] == species:
                true_iv = tuple(res[1]); break
        if true_iv is not None:
            resolved.append((G, pid, nat, true_iv, True))
    resolved.sort(key=lambda r: metric(r[3], r[2]), reverse=True)

    print("[%s] top (offline-exact unless *boundary-confirmed):" % label, flush=True)
    for G, pid, nat, iv, bdy in resolved[:10]:
        print("  G=0x%08X %-7s IVs=%s #31=%d%s"
              % (G, NAT[nat], iv, n31(iv), "  *confirmed" if bdy else ""), flush=True)

    # Deliver: reproduce the winner once to save a catchable encounter state.
    best = None
    for G, pid, nat, iv, bdy in resolved:
        for o in offsets:
            res = fixed_trigger(B, rewind(int(G), o))
            if res and res[0] == pid and res[2] == species and tuple(res[1]) == iv:
                save_state_file(B["core"], out_state)
                best = (G, pid, nat, iv, bdy); break
        if best:
            break
    if best:
        G, pid, nat, iv, bdy = best
        dt = time.time() - t0
        print("[%s] BEST: G=0x%08X %s IVs=%s #31=%d -> %s (%d confirms, %.1fs)"
              % (label, G, NAT[nat], iv, n31(iv), out_state, n_confirm, dt), flush=True)
    return resolved, best


if __name__ == "__main__":
    sp = int(sys.argv[1]) if len(sys.argv) > 1 else 32
    sl = (int(sys.argv[2]),) if len(sys.argv) > 2 else (10,)
    st = sys.argv[3] if len(sys.argv) > 3 else "roms/leafgreen_route3_grass.ss1"

    def _phys(nat):
        inc, dec = nat // 5, nat % 5
        return not ((dec == 0 and inc != 0) or (dec == 2 and inc != 2))

    def _metric(iv, nat):
        hp, atk, df, spe, spa, spd = iv
        return ((atk == 31) + (spe == 31), n31(iv), 1 if nat in (3, 13) else 0, hp + df + spd)

    run_hybrid_hunt(sp, sl, st, _metric, _phys, "cache_hybrid_%d.npz" % sp,
                    "roms/leafgreen_hybrid_%d.ss1" % sp, label="sp%d" % sp)
