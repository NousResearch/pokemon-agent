"""Multi-env (full-coverage) physical shiny Nidoran-male hunt over the Stage1/2/3
core. Enumerate the fixed candidate universe once (cached), reproduce across all
envs in the manifest (each env's offset cluster covers a different subset), keep
the best IV seen per seed, then rank physical-viable picks.

    distrobox enter devbox -- .venv-gba/bin/python hunt_nidoranm.py
"""
import json, os, sys
import shiny_grass_core as C

TID, SID = 51376, 36462
SPECIES, SLOTS = 32, (10,)
CACHE = "cache_nidoranm.npz"
RESULTS = "results_nidoranm.jsonl"
OUT_STATE = "roms/leafgreen_shiny_nidoranm.ss1"
SS5 = "roms/Pokemon - LeafGreen Version (USA).ss5"


def phys_viable(nat):
    inc, dec = nat // 5, nat % 5
    return not ((dec == 0 and inc != 0) or (dec == 2 and inc != 2))


def metric(iv, nat):
    hp, atk, df, spe, spa, spd = iv
    return ((atk == 31) + (spe == 31), C.n31(iv), 1 if nat in (3, 13) else 0, atk + spe, hp)


def main():
    cands = C.enumerate_candidates(SPECIES, SLOTS, TID, SID, cache_path=CACHE)
    total = len(cands[0])
    if os.path.exists("envs_route3.json"):
        envs = json.load(open("envs_route3.json"))["envs"]
    else:
        envs = [{"env_id": "ss5", "state": SS5, "axis": "LR", "hold": 2, "rel": 1,
                 "offsets": [59, 30, 10, 20, 48]}]
    if os.path.exists(RESULTS):
        os.remove(RESULTS)
    for e in envs:
        C.verify_env(cands, e["state"], e["offsets"], e["env_id"], axis=e["axis"],
                     hold=e["hold"], rel=e["rel"], target_species=SPECIES, results_jsonl=RESULTS)

    rows = C.load_results(RESULTS)
    # Best IV per seed (a seed may appear in several envs; deterministic IV, but
    # long-loop seeds can have an alternate — keep whichever ranks higher).
    best_by_G = {}
    for r in rows:
        if not phys_viable(r["nature"]):
            continue
        G = r["G"]; key = metric(tuple(r["iv"]), r["nature"])
        if G not in best_by_G or key > metric(tuple(best_by_G[G]["iv"]), best_by_G[G]["nature"]):
            best_by_G[G] = r
    uniq = len(best_by_G)
    phys_universe = int(sum(phys_viable(int(n)) for n in cands[2]))
    print("\ncoverage: %d/%d physical-viable seeds reproduced (%.0f%%); universe=%d all-nature"
          % (uniq, phys_universe, 100 * uniq / max(phys_universe, 1), total), flush=True)

    best = C.select_best(list(best_by_G.values()), metric, top=25)
    print("\ntop physical shiny Nidoran-male (Atk/Spe-perfect, then #31):", flush=True)
    for G, P, nat, iv, env in best:
        print("  G=0x%08X %-7s IVs(H,A,D,Sp,SpA,SpD)=%s #31=%d AtkSpe31=%d env=%s"
              % (G, C.NAT[nat], iv, C.n31(iv), (iv[1] == 31) + (iv[3] == 31), env), flush=True)

    # Save the battle state for the top pick (reproduce in its env).
    if best:
        from pokemon_agent.shiny_gen3 import rewind
        from pokemon_agent.gba_state import save_state_file
        G, P, nat, iv, env = best[0]
        em = next(e for e in envs if e["env_id"] == env)
        B = C._bundle(em["state"])
        for off in em["offsets"]:
            res = C._emulate(B, rewind(int(G), off), em["axis"], em["hold"], em["rel"])
            if res and res[0] == P:
                save_state_file(B["core"], OUT_STATE)
                print("\nBEST saved -> %s (G=0x%08X %s IVs=%s)" % (OUT_STATE, G, C.NAT[nat], iv), flush=True)
                break


if __name__ == "__main__":
    main()
