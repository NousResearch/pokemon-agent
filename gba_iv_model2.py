"""Deterministic-IV model RE (step 2) — assumption-free. For each encounter,
locate BOTH the PID calls and the IV calls directly on the written-seed LCG
chain (no post-PID reconstruction), and report the gap between them. Decides
whether short-loop IVs are on the clean chain (model fixable) or diverge.

    distrobox enter devbox -- .venv-gba/bin/python gba_iv_model2.py [state] [n]
"""
import sys, random, collections
import mgba.core, mgba.image, mgba.log
from pokemon_agent.gba_state import load_state_file
from pokemon_agent.shiny_gen3 import lcg_next, decrypt_block, ivs_from_decrypted

ROM = "roms/Pokemon - LeafGreen Version (USA).gba"
STATE = sys.argv[1] if len(sys.argv) > 1 else "roms/Pokemon - LeafGreen Version (USA).ss5"
NSAMP = int(sys.argv[2]) if len(sys.argv) > 2 else 25
ENEMY = 0x0202402C; RNG = 0x03005000
SCAN = 3000

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
    """Return the list of Random() outputs (>>16) for the first n calls from V."""
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


def find_iv_pos(outs, ivs):
    hp, atk, df, spe, spa, spd = ivs
    iv1 = hp | (atk << 5) | (df << 10); iv2 = spe | (spa << 5) | (spd << 10)
    for m in range(len(outs) - 1):
        if (outs[m] & 0x7FFF) == iv1 and (outs[m + 1] & 0x7FFF) == iv2:
            return m
    return None


rng = random.Random(11); gapc = collections.Counter(); rows = []
for _ in range(NSAMP):
    V = rng.getrandbits(32); r = emulate(V)
    if not r:
        continue
    pid, ivs = r; outs = chain_outputs(V, SCAN)
    pp = find_pid_pos(outs, pid); ip = find_iv_pos(outs, ivs)
    gap = (ip - (pp + 2)) if (pp is not None and ip is not None) else None
    gapc[gap] += 1
    if pp is not None:
        rows.append((pp, gap))
    print("pid=%08X pid_pos=%s iv_pos=%s gap=%s" % (pid, pp, ip, gap), flush=True)

print("\ngap (iv_pos - pid_end) histogram=%s" % dict(sorted(gapc.items(), key=lambda kv: (kv[0] is None, kv[0]))))
print("gap vs pid_pos:")
by = collections.defaultdict(list)
for pp, g in rows:
    by[g].append(pp)
for g in sorted(by, key=lambda x: (x is None, x)):
    ps = by[g]
    print("  gap=%-5s : n=%d  pid_pos range [%d..%d]" % (g, len(ps), min(ps), max(ps)))
