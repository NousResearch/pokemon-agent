"""Fully-offline physical shiny Nidoran-male hunt (Route 3, LeafGreen).

Stage 1 enumerates the fixed candidate universe AND predicts IVs offline via the
decoded VBlank model (pokemon_agent.gen3_rng): iv2 = o3 (env-independent), iv1 in
{o1, o2} (the env's threshold selects which). So each candidate has two possible
IV sets, both computable from G — we rank the whole space against the global
ceiling offline, then CONFIRM only the top-K in-emulator (resolving which iv1
variant the env realizes) to deliver an exact result. No mass emulation.

    distrobox enter devbox -- .venv-gba/bin/python hunt_nidoranm.py
"""
import json, os, time
import shiny_grass_core as C
from pokemon_agent.shiny_gen3 import rewind
from pokemon_agent.gba_state import save_state_file

TID, SID = 51376, 36462
SPECIES, SLOTS = 32, (10,)
CACHE = "cache_nidoranm.npz"
OUT_STATE = "roms/leafgreen_shiny_nidoranm.ss1"
TOPK = 80
SS5 = "roms/Pokemon - LeafGreen Version (USA).ss5"


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

    # Offline ranking against the global ceiling: each candidate's two IV variants
    # (iv1 from o1 vs o2; iv2 = o3 fixed). Keep the better-scoring variant for rank.
    rows = []
    for i in range(n):
        nat = int(cands["nature"][i])
        if not phys_viable(nat):
            continue
        o1, o2, o3 = int(cands["o1"][i]), int(cands["o2"][i]), int(cands["o3"][i])
        ivA = C._unpack_iv(o1, o3); ivB = C._unpack_iv(o2, o3)
        best_iv = ivA if metric(ivA, nat) >= metric(ivB, nat) else ivB
        rows.append((int(cands["G"][i]), int(cands["pid"][i]), nat, best_iv))
    rows.sort(key=lambda r: metric(r[3], r[2]), reverse=True)
    print("offline: %d physical candidates ranked in %.1fs; top predicted:" % (len(rows), time.time() - t0), flush=True)
    for G, P, nat, iv in rows[:8]:
        print("  PRED G=0x%08X %-7s IVs=%s #31=%d" % (G, C.NAT[nat], iv, C.n31(iv)), flush=True)

    # Confirm the top-K across available envs (resolves the env-realized variant).
    envs = json.load(open("envs_route3.json"))["envs"] if os.path.exists("envs_route3.json") else \
        [{"env_id": "ss5", "state": SS5, "axis": "LR", "hold": 2, "rel": 1, "offsets": [59, 30, 10, 20, 48]}]
    t1 = time.time(); confirmed = []
    for G, P, nat, _iv in rows[:TOPK]:
        for e in envs:
            B = C._bundle(e["state"]); done = False
            for off in e["offsets"]:
                res = C._emulate(B, rewind(G, off), e["axis"], e["hold"], e["rel"])
                if res and res[0] == P and res[2] == SPECIES:
                    confirmed.append((G, P, nat, tuple(res[1]), e["env_id"])); done = True; break
            if done:
                break
    confirmed.sort(key=lambda r: metric(r[3], r[2]), reverse=True)
    print("\nconfirmed %d/%d top candidates in %.1fs; best confirmed:" % (len(confirmed), TOPK, time.time() - t1), flush=True)
    for G, P, nat, iv, env in confirmed[:8]:
        print("  CONF G=0x%08X %-7s IVs=%s #31=%d env=%s" % (G, C.NAT[nat], iv, C.n31(iv), env), flush=True)

    if confirmed:
        G, P, nat, iv, env = confirmed[0]
        e = next(x for x in envs if x["env_id"] == env)
        B = C._bundle(e["state"])
        for off in e["offsets"]:
            res = C._emulate(B, rewind(G, off), e["axis"], e["hold"], e["rel"])
            if res and res[0] == P and tuple(res[1]) == iv:
                save_state_file(B["core"], OUT_STATE)
                print("\nBEST: G=0x%08X %s IVs=%s -> saved %s (total %.1fs)"
                      % (G, C.NAT[nat], iv, OUT_STATE, time.time() - t0), flush=True)
                break


if __name__ == "__main__":
    main()
