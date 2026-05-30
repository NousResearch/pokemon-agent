"""Deterministic-IV model RE (step 1). For many real encounters, find the TRUE
iv-read gap by a WIDE search (not just 0-15) from the post-PID LCG state, and
correlate it with the nature-loop length. If gap is a clean function of loop
length (and a per-state constant), IVs become offline-predictable -> instant,
exact hunts. See docs/CANDIDATE_GEN_PLAN.md task 4.

    distrobox enter devbox -- .venv-gba/bin/python gba_iv_model.py [state.ssN] [n]
"""
import sys, random, collections
import mgba.core, mgba.image, mgba.log
from pokemon_agent.gba_state import load_state_file
from pokemon_agent.shiny_gen3 import lcg_next, decrypt_block, ivs_from_decrypted
from pokemon_agent.gen3_rng import slot_index

ROM = "roms/Pokemon - LeafGreen Version (USA).gba"
STATE = sys.argv[1] if len(sys.argv) > 1 else "roms/Pokemon - LeafGreen Version (USA).ss5"
NSAMP = int(sys.argv[2]) if len(sys.argv) > 2 else 40
ENEMY = 0x0202402C; RNG = 0x03005000


def advance(s, n):
    for _ in range(n):
        s = lcg_next(s)
    return s


def calls_between(a, b, cap=1400):
    s = a
    for k in range(cap):
        if s == b:
            return k
        s = lcg_next(s)
    return None


def gen_internal(G):
    """Replicate generate_wild's stepping; return (pid, loop_iters, s_postpid)."""
    s = lcg_next(G)            # slot
    s = lcg_next(s)            # level
    s = lcg_next(s); nature = (s >> 16) % 25
    iters = 0; pid = 0
    while iters < 2000:
        iters += 1
        s = lcg_next(s); lo = (s >> 16) & 0xFFFF
        s = lcg_next(s); hi = (s >> 16) & 0xFFFF
        pid = ((hi << 16) | lo) & 0xFFFFFFFF
        if pid % 25 == nature:
            break
    return pid, iters, s


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
    return N, V, pid, ivs_from_decrypted(dec).as_tuple()


def find_gap(s_post, ivs, cap=800):
    hp, atk, df, spe, spa, spd = ivs
    iv1 = hp | (atk << 5) | (df << 10)
    iv2 = spe | (spa << 5) | (spd << 10)
    s = s_post
    for g in range(cap):
        a = lcg_next(s); b = lcg_next(a)
        if ((a >> 16) & 0x7FFF) == iv1 and ((b >> 16) & 0x7FFF) == iv2:
            return g
        s = lcg_next(s)
    return None


rng = random.Random(7); pairs = []; gapc = collections.Counter(); nomatch = 0
for _ in range(NSAMP):
    r = emulate(rng.getrandbits(32))
    if not r:
        continue
    N, V, pid, ivs = r
    d = next((d for d in range(8) if gen_internal(advance(V, N + d))[0] == pid), None)
    if d is None:
        continue
    G = advance(V, N + d); _pid, iters, s_post = gen_internal(G)
    g = find_gap(s_post, ivs)
    gapc[g] += 1
    if g is None:
        nomatch += 1
    else:
        pairs.append((iters, g))
    print("pid=%08X loop_iters=%-4d gap=%s ivs=%s" % (pid, iters, g, ivs), flush=True)

print("\nN=%d  gap histogram=%s  (None=%d)" % (len(pairs), dict(sorted(gapc.items(), key=lambda kv: (kv[0] is None, kv[0]))), nomatch))
if pairs:
    import statistics
    by_iter = collections.defaultdict(list)
    for it, g in pairs:
        by_iter[it].append(g)
    print("gap as function of loop_iters (iters: gaps):")
    for it in sorted(by_iter):
        print("  iters=%-4d -> gaps=%s" % (it, sorted(set(by_iter[it]))))
    # crude linear check
    xs = [it for it, g in pairs]; ys = [g for it, g in pairs]
    if len(set(xs)) > 1:
        mx, my = statistics.mean(xs), statistics.mean(ys)
        cov = sum((x - mx) * (y - my) for x, y in pairs); var = sum((x - mx) ** 2 for x in xs)
        slope = cov / var; inter = my - slope * mx
        print("linear fit gap ~= %.4f*iters + %.2f" % (slope, inter))
