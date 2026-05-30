"""Test whether input-pattern variation (different trigger offset -> different
threshold T) can realize a candidate's long-loop IV variant (iv1=o2). Sweeps a
few jiggle patterns across two states for a target G.

    distrobox enter devbox -- .venv-gba/bin/python probe_pattern.py [G_hex]
"""
import sys
import shiny_grass_core as C
from pokemon_agent.shiny_gen3 import rewind
from pokemon_agent.gen3_rng import wild_outcome

G = int(sys.argv[1], 0) if len(sys.argv) > 1 else 0x74AAD729
SPECIES = 32
pid = wild_outcome(G, 0).pid; loop = wild_outcome(G, 0).loop_iters
ivA = wild_outcome(G, 1 << 30).ivs.as_tuple()   # iv1=o1
ivB = wild_outcome(G, 0).ivs.as_tuple()          # iv1=o2
print("G=0x%08X pid=0x%08X loop=%d  A(o1)=%s  B(o2)=%s" % (G, pid, loop, ivA, ivB))

STATES = ["roms/Pokemon - LeafGreen Version (USA).ss5", "roms/envs/route3_env03.ss1"]
PATTERNS = [("LR", 2, 1), ("LR", 1, 1), ("LR", 3, 1), ("UD", 1, 1)]
seenB = False
for st in STATES:
    B = C._bundle(st)
    for axis, hold, rel in PATTERNS:
        hit = None
        for O in range(0, 131):
            res = C._emulate(B, rewind(G, O), axis, hold, rel)
            if res and res[0] == pid and res[2] == SPECIES:
                iv = tuple(res[1]); which = "A" if iv == ivA else ("B" if iv == ivB else "?")
                hit = (O, iv, which)
                if which == "B":
                    seenB = True
                break
        tag = "%s/%s%d:%d" % (st.split("/")[-1][:10], axis, hold, rel)
        print("  %-22s -> %s" % (tag, ("off=%d IVs=%s variant=%s" % hit if hit else "no repro")), flush=True)

print("\nvariant B (good) realizable via pattern/offset: %s" % ("YES" if seenB else "NO"))
