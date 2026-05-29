"""Generalized offline+verify grass shiny hunt (multiprocessing, fork-safe).

Configure the CONFIG block for any target (species, slots, natures, mandatory
IVs, gen-offsets — get slots/offsets from gba_grass_calibrate.py). Enumerates
the 2^32 gen-seed space (parallel numpy) for shiny + target-slot + allowed-
nature, then verifies candidates on real mGBA cores (one per worker), reading
true IVs. Ranks by #perfect-IVs (with the mandatory IVs required), nature
preference, then the IV priority order.
"""
import os, time, json
from concurrent.futures import ProcessPoolExecutor

# ===== CONFIG =====
STATE = "roms/Pokemon - LeafGreen Version (USA).ss3"   # Viridian Forest tile
ROM = "roms/Pokemon - LeafGreen Version (USA).gba"
TID, SID = 51376, 36462
TARGET_SPECIES = 25                 # Pikachu
SPECIES_SLOTS = (9, 11)             # Pikachu slots on this tile (calibrated)
GEN_OFFSETS = (110, 92, 128)        # ss3 gen-offset cluster (calibrated)
# offensive special-attacker natures (boost SpA or Spe; none lower SpA/Spe) + neutrals
ALLOWED_NATURES = (15, 16, 19, 10, 11, 14, 0, 6, 12, 18, 24)
NATURE_RANK = {15: 0, 10: 1, 16: 2, 19: 3, 11: 4, 14: 5}  # Modest>Timid>Mild>Rash>Hasty>Naive; others=9
MANDATORY = (4, 3)                  # IV indices that MUST be 31: SpA(4), Spe(3)
IV_PRIORITY = (0, 5, 2)             # tiebreak after #31: HP, SpD, Def
OUT_JSONL = "pikachu_results.jsonl"
ENEMY = 0x0202402C; RNG = 0x03005000
NAT = ["Hardy","Lonely","Brave","Adamant","Naughty","Bold","Docile","Relaxed","Impish","Lax",
       "Timid","Hasty","Serious","Jolly","Naive","Modest","Mild","Quiet","Bashful","Rash",
       "Calm","Gentle","Sassy","Careful","Quirky"]
# ==================


def enum_range(args):
    import numpy as np
    start, end, chunk = args
    A = np.uint64(0x41C64E6D); C = np.uint64(0x6073); M = np.uint64(0xFFFFFFFF); SIX = np.uint64(16)
    def stp(s): return (s * A + C) & M
    xb = np.uint64((TID ^ SID) & 0xFFFF); cums = np.cumsum([20, 20, 10, 10, 10, 10, 5, 5, 4, 4, 1, 1])
    slots = np.array(SPECIES_SLOTS); nats = np.array(ALLOWED_NATURES)
    out = []; b = start
    while b < end:
        n = min(chunk, end - b); G = np.arange(b, b + n, dtype=np.uint64); b += n
        s = stp(G); slot = np.searchsorted(cums, (s >> SIX) % np.uint64(100), side='right')
        s = stp(s); s = stp(s); nat = (s >> SIX) % np.uint64(25)
        gi = np.nonzero(np.isin(slot, slots) & np.isin(nat, nats))[0]
        if gi.size:
            Gs = G[gi]; tgt = nat[gi].astype(np.uint64); cur = s[gi].copy()
            matched = np.zeros(gi.size, bool); pid = np.zeros(gi.size, np.uint64)
            for _ in range(200):
                s1 = stp(cur); lo = s1 >> SIX; s2 = stp(s1); hi = s2 >> SIX
                p = ((hi << SIX) | lo) & M
                nm = (~matched) & ((p % np.uint64(25)) == tgt); pid[nm] = p[nm]; matched |= nm; cur = s2
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
        for off in GEN_OFFSETS:
            sp, pid, iv = _emulate(rewind(G, off))
            if pid == P and sp == TARGET_SPECIES: finds.append((int(rewind(G, off)), iv, P % 25)); break
    return finds


def main():
    NW = os.cpu_count(); print("workers:", NW, "target:", NAT, flush=True)
    t0 = time.time(); span = (1 << 32) // NW
    ranges = [(i * span, (i + 1) * span if i < NW - 1 else (1 << 32), 1 << 22) for i in range(NW)]
    cands = []
    with ProcessPoolExecutor(NW) as ex:
        for r in ex.map(enum_range, ranges): cands.extend(r)
    print("ENUM: %d candidates in %.1fs" % (len(cands), time.time() - t0), flush=True)
    t1 = time.time(); sl = [cands[i::NW] for i in range(NW)]; finds = []
    with ProcessPoolExecutor(NW) as ex:
        for r in ex.map(verify_chunk, sl): finds.extend(r)
    print("VERIFY: %d verified in %.1fs" % (len(finds), time.time() - t1), flush=True)
    n31 = lambda iv: sum(1 for x in iv if x == 31)
    good = [(V, iv, nat) for V, iv, nat in finds if all(iv[k] == 31 for k in MANDATORY)]
    def rank(t):
        V, iv, nat = t
        npref = NATURE_RANK.get(nat, 9)
        return (n31(iv), -npref) + tuple(iv[k] for k in IV_PRIORITY)
    good.sort(key=rank, reverse=True)
    with open(OUT_JSONL, "w") as f:
        for V, iv, nat in good:
            f.write(json.dumps({"write": "0x%08X" % V, "nature": NAT[nat], "ivs": list(iv), "n31": n31(iv)}) + "\n")
    print("SpA31&Spe31 shiny Pikachu found: %d" % len(good), flush=True)
    for V, iv, nat in good[:20]:
        print("  write=0x%08X %-7s IVs(H,A,D,Sp,SpA,SpD)=%s #31=%d" % (V, NAT[nat], iv, n31(iv)), flush=True)
    mod = [g for g in good if g[2] == 15]
    if mod:
        V, iv, nat = mod[0]
        print("BEST MODEST: write=0x%08X IVs=%s #31=%d" % (V, iv, n31(iv)), flush=True)
    print("TOTAL %.1fs" % (time.time() - t0), flush=True)


if __name__ == "__main__":
    main()
