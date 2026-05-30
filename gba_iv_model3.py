"""Deterministic-IV model RE (step 3) — PID-anchored gap analyzer.

The disassembly (pret/pokefirered) shows IVs are `iv1=Random(); iv2=Random()`
right after the nature-lock PID loop, and `VBlankIntr()` calls `Random()` once
per frame. So on the gRngValue chain the IV reads are displaced only by VBlank
calls. We anchor on the 32-bit PID (reliable) and find iv1 at pid_end+g1 and iv2
at iv1+1+g2 — allowing a VBlank between iv1 and iv2 (which the earlier consecutive
search missed). Correlate (g1,g2) with the nature-loop length and trigger offset
to derive the offline gap rule.

    distrobox enter devbox -- .venv-gba/bin/python gba_iv_model3.py [state] [n]
"""
import sys, random, collections
import mgba.core, mgba.image, mgba.log
from pokemon_agent.gba_state import load_state_file
from pokemon_agent.shiny_gen3 import lcg_next, decrypt_block, ivs_from_decrypted
from pokemon_agent.gen3_rng import generate_wild

ROM = "roms/Pokemon - LeafGreen Version (USA).gba"
STATE = sys.argv[1] if len(sys.argv) > 1 else "roms/Pokemon - LeafGreen Version (USA).ss5"
NSAMP = int(sys.argv[2]) if len(sys.argv) > 2 else 60
ENEMY = 0x0202402C; RNG = 0x03005000
SCAN = 6000


def advance(s, n):
    for _ in range(n):
        s = lcg_next(s)
    return s


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


def chain_outputs(V, n):
    outs = []; s = V
    for _ in range(n):
        s = lcg_next(s); outs.append((s >> 16) & 0xFFFF)
    return outs


def find_pid_pos(outs, pid):
    lo, hi = pid & 0xFFFF, (pid >> 16) & 0xFFFF
    for m in range(len(outs) - 1):
        if outs[m] == lo and outs[m + 1] == hi:
            return m
    return None


def find_at(outs, start, val15, window=10):
    for k in range(window):
        if start + k < len(outs) and (outs[start + k] & 0x7FFF) == val15:
            return k
    return None


rng = random.Random(13)
rows = []; offc = collections.Counter(); g1c = collections.Counter(); g2c = collections.Counter()
fail = 0
for _ in range(NSAMP):
    V = rng.getrandbits(32); r = emulate(V)
    if not r:
        continue
    pid, ivs = r
    off = next((o for o in range(0, 240) if generate_wild(advance(V, o)).pid == pid), None)
    if off is None:
        fail += 1; continue
    loop_iters = generate_wild(advance(V, off)).loop_iters
    outs = chain_outputs(V, SCAN)
    pp = find_pid_pos(outs, pid)
    if pp is None:
        fail += 1; continue
    hp, atk, df, spe, spa, spd = ivs
    iv1 = hp | (atk << 5) | (df << 10); iv2 = spe | (spa << 5) | (spd << 10)
    g1 = find_at(outs, pp + 2, iv1)
    g2 = find_at(outs, pp + 2 + g1 + 1, iv2) if g1 is not None else None
    rows.append((off, loop_iters, g1, g2))
    offc[off] += 1; g1c[g1] += 1; g2c[g2] += 1
    print("off=%-4d loop=%-4d g1=%-4s g2=%-4s ivs=%s" % (off, loop_iters, g1, g2, ivs), flush=True)

print("\nN=%d fails=%d" % (len(rows), fail))
print("offset histogram:", dict(sorted(offc.items())))
print("g1 histogram:", dict(sorted(g1c.items(), key=lambda kv: (kv[0] is None, kv[0]))))
print("g2 histogram:", dict(sorted(g2c.items(), key=lambda kv: (kv[0] is None, kv[0]))))

dom = offc.most_common(1)[0][0] if offc else None
print("\n--- dominant offset %s only: (g1,g2) vs loop_iters ---" % dom)
by = collections.defaultdict(list)
for off, it, g1, g2 in rows:
    if off == dom:
        by[(g1, g2)].append(it)
for key in sorted(by, key=lambda k: (k[0] is None, k[0], k[1] is None, k[1])):
    its = sorted(by[key])
    print("  (g1,g2)=%s : n=%d  loop_iters=%s" % (key, len(its), its))
