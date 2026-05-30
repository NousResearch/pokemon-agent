"""Probe whether a candidate's GOOD IV variant is realizable: for a target
gen-seed G, sweep trigger offsets across all env states, reproduce, and read the
true (env-realized) IVs. Shows which variant (iv1=o1 vs o2) each offset lands.

    distrobox enter devbox -- .venv-gba/bin/python probe_realize.py [G_hex]
"""
import sys, json, os
import shiny_grass_core as C
from pokemon_agent.shiny_gen3 import rewind
from pokemon_agent.gen3_rng import wild_outcome

G = int(sys.argv[1], 0) if len(sys.argv) > 1 else 0x74AAD729
SPECIES = 32
SWEEP = range(0, 121)

# offline: PID + both IV variants + loop
loop = wild_outcome(G, 0).loop_iters
pid = wild_outcome(G, 0).pid
ivA = wild_outcome(G, 1 << 30).ivs.as_tuple()   # iv1 = o1 (good, short-loop side)
ivB = wild_outcome(G, 0).ivs.as_tuple()          # iv1 = o2 (long-loop side)
print("G=0x%08X pid=0x%08X loop_iters=%d" % (G, pid, loop))
print("variant A (iv1=o1): %s   #31=%d" % (ivA, C.n31(ivA)))
print("variant B (iv1=o2): %s   #31=%d" % (ivB, C.n31(ivB)))

envs = json.load(open("envs_route3.json"))["envs"] if os.path.exists("envs_route3.json") else [
    {"env_id": "ss5", "state": "roms/Pokemon - LeafGreen Version (USA).ss5", "axis": "LR", "hold": 2, "rel": 1}]

print("\nsweeping offsets 0..120 in each env (showing reproductions):")
hitsA = hitsB = 0
for e in envs:
    B = C._bundle(e["state"])
    for O in SWEEP:
        res = C._emulate(B, rewind(G, O), e["axis"], e["hold"], e["rel"])
        if res and res[0] == pid and res[2] == SPECIES:
            iv = tuple(res[1]); which = "A" if iv == ivA else ("B" if iv == ivB else "?")
            if which == "A":
                hitsA += 1
            elif which == "B":
                hitsB += 1
            print("  env=%s off=%-3d -> IVs=%s variant=%s" % (e["env_id"], O, iv, which), flush=True)

print("\nvariant A realized %d times, variant B %d times" % (hitsA, hitsB))
print("=> GOOD variant A is %sREALIZABLE" % ("" if hitsA else "NOT "))
