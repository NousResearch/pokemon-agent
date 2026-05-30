"""Measure the true IV VBlank-gap for a grass state: for many real encounters,
find the PID gen-offset (clean-chain) then which iv_gap makes generate_wild's IVs
match the emulator's true IVs.  Tells us how to pre-filter IVs offline.

    distrobox enter devbox -- .venv-gba/bin/python gba_iv_gap_probe.py [state.ssN]
"""
import sys, collections, random
import mgba.core, mgba.image, mgba.log
from pokemon_agent.gba_state import load_state_file
from pokemon_agent.shiny_gen3 import lcg_next, decrypt_block, ivs_from_decrypted
from pokemon_agent.gen3_rng import generate_wild

ROM = "roms/Pokemon - LeafGreen Version (USA).gba"
STATE = sys.argv[1] if len(sys.argv) > 1 else "roms/leafgreen_route3_grass.ss1"
ENEMY = 0x0202402C; RNG = 0x03005000


def advance(s, n):
    for _ in range(n):
        s = lcg_next(s)
    return s


def calls_between(a, b, cap=900):
    s = a
    for k in range(cap):
        if s == b:
            return k
        s = lcg_next(s)
    return None


mgba.log.silence()
core = mgba.core.load_path(ROM); fb = mgba.image.Image(*core.desired_video_dimensions())
core.set_video_buffer(fb); core.reset(); load_state_file(core, STATE)
base = bytes(core.save_raw_state()); mem = core.memory; L, R = core.KEY_LEFT, core.KEY_RIGHT


def emulate(V):
    core.load_raw_state(base); mem.u32[RNG] = V; bp = mem.u32[ENEMY]
    prev = mem.u32[RNG]; total = 0; i = 0; N = None
    while i < 80 and N is None:
        btn = L if i % 2 == 0 else R
        for ph in range(3):
            core.set_keys(btn) if ph < 2 else core.set_keys(); core.run_frame()
            cur = mem.u32[RNG]; c = calls_between(prev, cur); prev = cur
            if c is None:
                continue
            if c > 5:
                N = total; break
            total += c
        i += 1
    if N is None:
        return None
    for _ in range(22):
        core.run_frame()
    mon = b"".join(mem.u32[ENEMY + 4 * k].to_bytes(4, "little") for k in range(25))
    pid = int.from_bytes(mon[0:4], "little"); otid = int.from_bytes(mon[4:8], "little")
    dec = decrypt_block(mon[0x20:0x20 + 48], pid, otid)
    sp = int.from_bytes(dec[0:2], "little")
    ivs = ivs_from_decrypted(dec).as_tuple()
    return N, V, pid, sp, ivs


rng = random.Random(7); gapcount = collections.Counter(); pidoff = collections.Counter(); n = 0
for _ in range(40):
    r = emulate(rng.getrandbits(32))
    if not r:
        continue
    N, V, pid, sp, ivs = r
    d = next((d for d in range(8) if generate_wild(advance(V, N + d)).pid == pid), None)
    if d is None:
        print("no PID match pid=%08X" % pid); continue
    gen = advance(V, N + d); pidoff[N + d] += 1
    g = next((g for g in range(0, 16) if generate_wild(gen, iv_gap=g).ivs.as_tuple() == ivs), None)
    gapcount[g] += 1; n += 1
    print("sp=%-3d pid=%08X pidoff=%d ivgap=%s ivs=%s" % (sp, pid, N + d, g, ivs))
print("\nn=%d  pid-offsets=%s  iv-gaps=%s" % (n, dict(pidoff), dict(gapcount)))
