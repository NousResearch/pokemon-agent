"""Measure the ambiguous-band width under different triggers, to decide Route B.

For N seeds, trigger an encounter, find the gen-seed G (offline d-search) and the
realized iv1 variant (o1 vs o2). At the dominant offset, report the loop range
where BOTH variants occur (the band). A deterministic trigger that pins phi0
should shrink the band toward 0.

    distrobox enter devbox -- .venv-gba/bin/python gba_band.py [jiggle|walkD|walkU] [n] [state]
"""
import collections
import sys

import mgba.core
import mgba.image
import mgba.log

from pokemon_agent.gba_state import load_state_file
from pokemon_agent.gen3_rng import wild_outcome
from pokemon_agent.shiny_gen3 import decrypt_block, ivs_from_decrypted, lcg_next

mgba.log.silence()
ROM = "roms/Pokemon - LeafGreen Version (USA).gba"
MODE = sys.argv[1] if len(sys.argv) > 1 else "jiggle"
N = int(sys.argv[2]) if len(sys.argv) > 2 else 120
STATE = sys.argv[3] if len(sys.argv) > 3 else "roms/leafgreen_route3_grass.ss1"
ENEMY = 0x0202402C
RNG = 0x03005000

core = mgba.core.load_path(ROM)
fb = mgba.image.Image(*core.desired_video_dimensions())
core.set_video_buffer(fb); core.reset(); load_state_file(core, STATE)
base = bytes(core.save_raw_state()); mem = core.memory
L, R, U, D = core.KEY_LEFT, core.KEY_RIGHT, core.KEY_UP, core.KEY_DOWN


def advance(s, n):
    for _ in range(n):
        s = lcg_next(s)
    return s


def trigger(V):
    core.load_raw_state(base); mem.u32[RNG] = V & 0xFFFFFFFF; bp = mem.u32[ENEMY]
    frames = 0
    if MODE == "jiggle":
        i = 0
        while frames < 600:
            btn = L if i % 2 == 0 else R
            for ph in range(3):
                core.set_keys(btn if ph < 2 else 0); core.run_frame(); frames += 1
                if mem.u32[ENEMY] != bp:
                    break
            else:
                i += 1; continue
            break
    elif MODE == "walkBF":  # back-and-forth full steps (stay on 2 tiles, identical step phi0)
        i = 0
        while frames < 600:
            key = D if (i % 2 == 0) else U
            for _ in range(16):
                core.set_keys(key); core.run_frame(); frames += 1
                if mem.u32[ENEMY] != bp:
                    break
            else:
                i += 1; continue
            break
    else:  # walk: hold one direction continuously (every step identical -> fixed phi0?)
        key = D if MODE == "walkD" else U
        while frames < 600:
            core.set_keys(key); core.run_frame(); frames += 1
            if mem.u32[ENEMY] != bp:
                break
    if mem.u32[ENEMY] == bp:
        return None
    for _ in range(20):
        core.run_frame()
    mon = b"".join(mem.u32[ENEMY + 4 * k].to_bytes(4, "little") for k in range(25))
    pid = int.from_bytes(mon[0:4], "little"); otid = int.from_bytes(mon[4:8], "little")
    dec = decrypt_block(mon[0x20:0x20 + 48], pid, otid)
    return pid, ivs_from_decrypted(dec).as_tuple()


import random  # noqa: E402

rng = random.Random(99)
offc = collections.Counter()
# per offset: {loop: set(variants)}
by_off = collections.defaultdict(lambda: collections.defaultdict(set))
n_ok = 0
for _ in range(N):
    V = rng.getrandbits(32); r = trigger(V)
    if not r:
        continue
    pid, ivs = r
    off = next((o for o in range(0, 240) if wild_outcome(advance(V, o), 1 << 30).pid == pid), None)
    if off is None:
        continue
    G = advance(V, off)
    sp = wild_outcome(G, 1 << 30)
    loop = sp.loop_iters
    o1v = wild_outcome(G, 1 << 30).ivs.as_tuple()
    o2v = wild_outcome(G, 0).ivs.as_tuple()
    realized = "o1" if ivs == o1v else ("o2" if ivs == o2v else "?")
    offc[off] += 1
    by_off[off][loop].add(realized)
    n_ok += 1

dom = offc.most_common(1)[0][0]
print("MODE=%s N=%d ok=%d  offset spread=%s  dominant=%d (%d)"
      % (MODE, N, n_ok, dict(sorted(offc.items())), dom, offc[dom]))
loops = by_off[dom]
o1_loops = sorted(L for L, vs in loops.items() if "o1" in vs)
o2_loops = sorted(L for L, vs in loops.items() if "o2" in vs)
both = sorted(L for L, vs in loops.items() if {"o1", "o2"} <= vs)
print("dominant offset %d: o1 loops max=%s, o2 loops min=%s" %
      (dom, max(o1_loops) if o1_loops else None, min(o2_loops) if o2_loops else None))
print("BAND (loops showing BOTH variants): %s  -> band width = %d" % (both, len(both)))
unknown = sum(1 for L, vs in loops.items() if "?" in vs)
if unknown:
    print("WARNING: %d loop(s) had unrecognized variant (iv2 may differ too)" % unknown)
