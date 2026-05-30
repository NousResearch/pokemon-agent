"""Per-env IV-model calibration: dump the VBlank structure (a = #vblanks before
iv1; ab = #vblanks before iv2) vs nature-loop length at the env's dominant
trigger offset, and derive the thresholds the offline model needs:
  iv1 = o[1+a]   (a: 0 -> 1 at loop threshold Ta)
  iv2 = o[2+ab]  (ab: typically 1; ->2 at Tab_hi for long loops; ->0 below Tab_lo)

    distrobox enter devbox -- .venv-gba/bin/python gba_iv_struct.py [state] [n]
"""
import sys, random, collections
import mgba.core, mgba.image, mgba.log
from pokemon_agent.gba_state import load_state_file
from pokemon_agent.shiny_gen3 import lcg_next, decrypt_block, ivs_from_decrypted

ROM = "roms/Pokemon - LeafGreen Version (USA).gba"
STATE = sys.argv[1] if len(sys.argv) > 1 else "roms/Pokemon - LeafGreen Version (USA).ss5"
NSAMP = int(sys.argv[2]) if len(sys.argv) > 2 else 220
ENEMY = 0x0202402C; RNG = 0x03005000


def advance(s, n):
    for _ in range(n):
        s = lcg_next(s)
    return s


def gen_o(G, nout=7, max_loop=2000):
    s = lcg_next(G); s = lcg_next(s); s = lcg_next(s); nature = (s >> 16) % 25
    pid = 0; iters = 0
    for iters in range(1, max_loop + 1):
        s = lcg_next(s); lo = (s >> 16) & 0xFFFF
        s = lcg_next(s); hi = (s >> 16) & 0xFFFF
        pid = ((hi << 16) | lo) & 0xFFFFFFFF
        if pid % 25 == nature:
            break
    outs = []
    for _ in range(nout):
        s = lcg_next(s); outs.append((s >> 16) & 0x7FFF)
    return pid, iters, outs


mgba.log.silence()
core = mgba.core.load_path(ROM); fb = mgba.image.Image(*core.desired_video_dimensions())
core.set_video_buffer(fb); core.reset(); load_state_file(core, STATE)
base = bytes(core.save_raw_state()); mem = core.memory; L, R = core.KEY_LEFT, core.KEY_RIGHT


def emulate(V):
    core.load_raw_state(base); mem.u32[RNG] = V; bp = mem.u32[ENEMY]
    frames = 0; i = 0; hit = False
    while frames < 460:
        btn = L if i % 2 == 0 else R
        for ph in range(3):
            core.set_keys(btn) if ph < 2 else core.set_keys(); core.run_frame(); frames += 1
            if mem.u32[ENEMY] != bp:
                hit = True; break
        if hit:
            break
        i += 1
    if not hit:
        return None
    for _ in range(22):
        core.run_frame()
    mon = b"".join(mem.u32[ENEMY + 4 * k].to_bytes(4, "little") for k in range(25))
    pid = int.from_bytes(mon[0:4], "little"); otid = int.from_bytes(mon[4:8], "little")
    dec = decrypt_block(mon[0x20:0x20 + 48], pid, otid)
    return pid, ivs_from_decrypted(dec).as_tuple()


rng = random.Random(777); by_off = collections.defaultdict(list); offc = collections.Counter()
for _ in range(NSAMP):
    V = rng.getrandbits(32); r = emulate(V)
    if not r:
        continue
    pid, ivs = r
    off = next((o for o in range(0, 240) if gen_o(advance(V, o))[0] == pid), None)
    if off is None:
        continue
    G = advance(V, off); _pid, iters, outs = gen_o(G)
    hp, atk, df, spe, spa, spd = ivs
    iv1 = hp | (atk << 5) | (df << 10); iv2 = spe | (spa << 5) | (spd << 10)
    a = next((k for k in range(len(outs)) if outs[k] == iv1), None)        # iv1 index (0-based) => a
    ab = next((k for k in range(len(outs)) if outs[k] == iv2), None)       # iv2 index => 1+ab
    by_off[off].append((iters, a, ab)); offc[off] += 1

dom = offc.most_common(1)[0][0]
rows = sorted(by_off[dom])
print("dominant offset=%d  n=%d\n(loop, a=iv1_idx, ab=iv2_idx):" % (dom, len(rows)))
for it, a, ab in rows:
    flag = "" if (a in (0, 1) and ab == 2) else "  <-- edge"
    print("  loop=%-4d a=%s ab=%s%s" % (it, a, ab, flag), flush=True)

# thresholds
a01 = [it for it, a, ab in rows if a == 0]; a1 = [it for it, a, ab in rows if a == 1]
ab2 = [it for it, a, ab in rows if ab == 2]; ab_other = [(it, ab) for it, a, ab in rows if ab not in (2,)]
print("\nTa (a:0->1): max a=0 loop=%s, min a=1 loop=%s" %
      (max(a01) if a01 else None, min(a1) if a1 else None))
print("iv2 index ab: counts=%s" % dict(collections.Counter(ab for _it, _a, ab in rows)))
if ab_other:
    print("iv2 NON-standard (ab!=2) cases: %s" % ab_other)
