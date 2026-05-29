"""Exhaustive Adamant shiny-Mankey IV hunt — multiprocessing (fork-safe)."""
import os, time, json
from concurrent.futures import ProcessPoolExecutor

ROM = "roms/Pokemon - LeafGreen Version (USA).gba"
STATE = "roms/Pokemon - LeafGreen Version (USA).ss4"  # new tile (calibrated)
ENEMY = 0x0202402C; RNG = 0x03005000; TID, SID = 51376, 36462
ADAMANT = 3; OFFSETS = (199, 181, 217)  # ss4 gen-offset cluster
MANKEY_SLOTS = (1, 3, 5, 9)  # ss4 Route-22 Mankey slots


def enum_range(args):
    import numpy as np
    start, end, chunk = args
    A = np.uint64(0x41C64E6D); C = np.uint64(0x6073); M = np.uint64(0xFFFFFFFF); SIX = np.uint64(16)
    def stp(s): return (s * A + C) & M
    xb = np.uint64((TID ^ SID) & 0xFFFF); cums = np.cumsum([20, 20, 10, 10, 10, 10, 5, 5, 4, 4, 1, 1])
    out = []; b = start
    while b < end:
        n = min(chunk, end - b); G = np.arange(b, b + n, dtype=np.uint64); b += n
        s = stp(G); slot = np.searchsorted(cums, (s >> SIX) % np.uint64(100), side='right')
        s = stp(s); s = stp(s); nat = (s >> SIX) % np.uint64(25)
        gi = np.nonzero(np.isin(slot, MANKEY_SLOTS) & (nat == ADAMANT))[0]
        if gi.size:
            Gs = G[gi]; cur = s[gi].copy(); matched = np.zeros(gi.size, bool); pid = np.zeros(gi.size, np.uint64)
            for _ in range(200):
                s1 = stp(cur); lo = s1 >> SIX; s2 = stp(s1); hi = s2 >> SIX
                p = ((hi << SIX) | lo) & M
                nm = (~matched) & ((p % np.uint64(25)) == ADAMANT); pid[nm] = p[nm]; matched |= nm; cur = s2
                if matched.all(): break
            pl = pid & np.uint64(0xFFFF); ph = pid >> SIX
            sh = matched & (((xb ^ ph ^ pl) & np.uint64(0xFFFF)) < np.uint64(8))
            for e in np.nonzero(sh)[0]: out.append((int(Gs[e]), int(pid[e])))
    return out


_W = {}
def _emulate(V):
    from pokemon_agent.shiny_gen3 import decrypt_block, ivs_from_decrypted
    if not _W:
        import mgba.core, mgba.image, mgba.log
        from pokemon_agent.gba_state import load_state_file
        mgba.log.silence()
        core = mgba.core.load_path(ROM); fb = mgba.image.Image(*core.desired_video_dimensions())
        core.set_video_buffer(fb); core.reset(); load_state_file(core, STATE)
        _W.update(core=core, base=bytes(core.save_raw_state()), mem=core.memory, L=core.KEY_LEFT, R=core.KEY_RIGHT)
    core = _W["core"]; mem = _W["mem"]; L, R = _W["L"], _W["R"]
    core.load_raw_state(_W["base"]); mem.u32[RNG] = V; bp = mem.u32[ENEMY]; i = 0
    while i < 70:
        btn = L if i % 2 == 0 else R
        for ph in range(3):
            core.set_keys(btn) if ph < 2 else core.set_keys(); core.run_frame()
            if mem.u32[ENEMY] != bp: i = 999; break
        if i == 999: break
        i += 1
    for _ in range(20): core.run_frame()
    mon = b"".join(mem.u32[ENEMY + 4 * k].to_bytes(4, "little") for k in range(25))
    pid = int.from_bytes(mon[0:4], "little"); otid = int.from_bytes(mon[4:8], "little")
    dec = decrypt_block(mon[0x20:0x20 + 48], pid, otid)
    return int.from_bytes(dec[0:2], "little"), pid, ivs_from_decrypted(dec).as_tuple()


def verify_chunk(cands):
    from pokemon_agent.gen3_rng import rewind
    finds = []
    for G, P in cands:
        for off in OFFSETS:
            sp, pid, iv = _emulate(rewind(G, off))
            if pid == P and sp == 56:
                finds.append((int(rewind(G, off)), iv)); break
    return finds


def main():
    NW = os.cpu_count(); print("workers:", NW, flush=True)
    t0 = time.time(); span = (1 << 32) // NW
    ranges = [(i * span, (i + 1) * span if i < NW - 1 else (1 << 32), 1 << 22) for i in range(NW)]
    cands = []
    with ProcessPoolExecutor(NW) as ex:
        for r in ex.map(enum_range, ranges):
            cands.extend(r)
    t_enum = time.time() - t0
    print("ENUM: %d Adamant candidates in %.1fs (%.2fM seeds/s)" % (len(cands), t_enum, (1 << 32) / t_enum / 1e6), flush=True)
    t1 = time.time(); sl = [cands[i::NW] for i in range(NW)]; finds = []
    with ProcessPoolExecutor(NW) as ex:
        for r in ex.map(verify_chunk, sl):
            finds.extend(r)
    t_ver = time.time() - t1
    print("VERIFY: %d verified shiny Mankeys in %.1fs" % (len(finds), t_ver), flush=True)
    n31 = lambda iv: sum(1 for x in iv if x == 31)
    a = [(V, iv) for V, iv in finds if iv[1] == 31 and iv[3] == 31]
    a.sort(key=lambda x: (n31(x[1]), x[1][0], x[1][2], sum(x[1])), reverse=True)
    with open("adamant_a31s31_ss4.jsonl", "w") as f:
        for V, iv in a:
            f.write(json.dumps({"write": "0x%08X" % V, "ivs": list(iv), "n31": n31(iv)}) + "\n")
    print("Atk31&Spe31 Adamant found: %d" % len(a), flush=True)
    for V, iv in a:
        print("  write=0x%08X IVs(H,A,D,Sp,SpA,SpD)=%s #31=%d" % (V, iv, n31(iv)), flush=True)
    print("TOTAL: enum %.1fs + verify %.1fs = %.1fs" % (t_enum, t_ver, t_enum + t_ver), flush=True)


if __name__ == "__main__":
    main()
