"""Validate the offline IV model (pokemon_agent/gen3_rng.wild_outcome) against
emulator ground truth, and calibrate the per-offset iv1 threshold T.

Checks the decoded invariants — iv2 == o3 (3rd post-PID output) ALWAYS, and
iv1 in {o1, o2} ALWAYS — then per realized offset calibrates T and verifies
wild_outcome(G, T) reproduces all 6 IVs exactly (outside the thin ambiguous
band, where both variants are accepted).

    distrobox enter devbox -- .venv-gba/bin/python validate_iv_prediction.py [state] [n]
"""
import sys, random, collections
import mgba.core, mgba.image, mgba.log
from pokemon_agent.gba_state import load_state_file
from pokemon_agent.shiny_gen3 import lcg_next, decrypt_block, ivs_from_decrypted
from pokemon_agent.gen3_rng import calibrate_iv_threshold, wild_outcome

ROM = "roms/Pokemon - LeafGreen Version (USA).gba"
STATE = sys.argv[1] if len(sys.argv) > 1 else "roms/Pokemon - LeafGreen Version (USA).ss5"
NSAMP = int(sys.argv[2]) if len(sys.argv) > 2 else 200
ENEMY = 0x0202402C; RNG = 0x03005000


def advance(s, n):
    for _ in range(n):
        s = lcg_next(s)
    return s


def gen_o(G, max_loop=2000):
    """(pid, loop_iters, o1, o2, o3) — the three post-PID 15-bit outputs."""
    s = lcg_next(G); s = lcg_next(s); s = lcg_next(s); nature = (s >> 16) % 25
    pid = 0; iters = 0
    for iters in range(1, max_loop + 1):
        s = lcg_next(s); lo = (s >> 16) & 0xFFFF
        s = lcg_next(s); hi = (s >> 16) & 0xFFFF
        pid = ((hi << 16) | lo) & 0xFFFFFFFF
        if pid % 25 == nature:
            break
    s = lcg_next(s); o1 = (s >> 16) & 0x7FFF
    s = lcg_next(s); o2 = (s >> 16) & 0x7FFF
    s = lcg_next(s); o3 = (s >> 16) & 0x7FFF
    return pid, iters, o1, o2, o3


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


rng = random.Random(2024)
# per offset: list of (G, loop_iters, ivs_true, iv1_uses_o2)
by_off = collections.defaultdict(list)
iv2_ok = iv2_bad = iv1_ok = iv1_bad = 0; nfail = 0
for _ in range(NSAMP):
    V = rng.getrandbits(32); r = emulate(V)
    if not r:
        continue
    pid, ivs = r
    off = next((o for o in range(0, 240) if gen_o(advance(V, o))[0] == pid), None)
    if off is None:
        nfail += 1; continue
    G = advance(V, off); _pid, iters, o1, o2, o3 = gen_o(G)
    hp, atk, df, spe, spa, spd = ivs
    iv1_true = hp | (atk << 5) | (df << 10); iv2_true = spe | (spa << 5) | (spd << 10)
    if iv2_true == o3:
        iv2_ok += 1
    else:
        iv2_bad += 1
    if iv1_true == o1 or iv1_true == o2:
        iv1_ok += 1
    else:
        iv1_bad += 1
    by_off[off].append((G, iters, ivs, iv1_true == o2 and iv1_true != o1))

ntot = iv2_ok + iv2_bad
print("samples=%d fails=%d" % (ntot, nfail))
print("INVARIANT iv2==o3 : %d/%d  (%s)" % (iv2_ok, ntot, "OK" if iv2_bad == 0 else "VIOLATED x%d" % iv2_bad))
print("INVARIANT iv1 in {o1,o2}: %d/%d  (%s)" % (iv1_ok, ntot, "OK" if iv1_bad == 0 else "VIOLATED x%d" % iv1_bad))

print("\nper-offset threshold calibration + full prediction check:")
overall_exact = overall_n = 0
for off in sorted(by_off, key=lambda o: -len(by_off[o])):
    rows = by_off[off]
    if len(rows) < 4:
        continue
    T, band = calibrate_iv_threshold([(it, u2) for _G, it, _ivs, u2 in rows])
    exact = 0; banded = 0
    for G, it, ivs_true, _u2 in rows:
        pred = wild_outcome(G, T).ivs.as_tuple()
        if pred == ivs_true:
            exact += 1
        elif band and band[0] <= it <= band[1]:
            banded += 1  # ambiguous band: would emit both variants + confirm
    overall_exact += exact; overall_n += len(rows)
    print("  off=%-3d n=%-3d T=%s band=%s  exact=%d/%d  band-deferred=%d"
          % (off, len(rows), T if T < (1 << 29) else "none", band, exact, len(rows), banded))

print("\nTOTAL exact offline IV prediction: %d/%d (%.1f%%)"
      % (overall_exact, overall_n, 100 * overall_exact / max(overall_n, 1)))
