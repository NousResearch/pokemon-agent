"""Auto-calibrate per-state constants for a grass shiny hunt (clean-chain method).

Given a save state of the player standing in grass (clear left/right tiles to
jiggle), determine the constants the hunt needs for THIS state:
  * target-species encounter SLOT indices (e.g. Mankey)
  * the GEN OFFSET cluster: gen-seed = advance(written_seed, offset)

These differ per tile (sprite/RNG environment) and per route (encounter table);
the generation logic, TID/SID and addresses are location-independent. Uses the
reliable clean-chain count (RNG calls to the generation burst) + a small delta
search, NOT a wide brute-force PID match (which was noisy).

    distrobox enter devbox -- .venv-gba/bin/python gba_grass_calibrate.py <state.ssN> [species_id]
"""
import sys, collections, random
import mgba.core, mgba.image, mgba.log
from pokemon_agent.gba_state import load_state_file
from pokemon_agent.shiny_gen3 import lcg_next, decrypt_block
from pokemon_agent.gen3_rng import generate_wild

ROM = "roms/Pokemon - LeafGreen Version (USA).gba"
ENEMY = 0x0202402C; RNG = 0x03005000
SPN = {19: "Rattata", 20: "Raticate", 21: "Spearow", 22: "Fearow", 29: "NidoranF",
       32: "NidoranM", 56: "Mankey", 16: "Pidgey", 27: "Sandshrew"}


def _calls_between(a, b, cap=700):
    s = a
    for n in range(cap):
        if s == b:
            return n
        s = lcg_next(s)
    return None


def _advance(s, n):
    for _ in range(n):
        s = lcg_next(s)
    return s


def calibrate(state_path, n_samples=24):
    mgba.log.silence()
    core = mgba.core.load_path(ROM); fb = mgba.image.Image(*core.desired_video_dimensions())
    core.set_video_buffer(fb); core.reset(); load_state_file(core, state_path)
    base = bytes(core.save_raw_state()); mem = core.memory; L, R = core.KEY_LEFT, core.KEY_RIGHT

    def emulate(V):
        core.load_raw_state(base); mem.u32[RNG] = V; bp = mem.u32[ENEMY]
        prev = mem.u32[RNG]; total = 0; i = 0; N = None
        while i < 80 and N is None:
            btn = L if i % 2 == 0 else R
            for ph in range(3):
                core.set_keys(btn) if ph < 2 else core.set_keys(); core.run_frame()
                cur = mem.u32[RNG]; c = _calls_between(prev, cur); prev = cur
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
        return N, pid, otid, int.from_bytes(dec[0:2], "little")

    rng = random.Random(7); offs = collections.Counter(); slot_species = {}; tid = sid = None
    for _ in range(n_samples):
        V = rng.getrandbits(32); r = emulate(V)
        if not r:
            continue
        N, pid, otid, sp = r
        if tid is None:
            tid, sid = otid & 0xFFFF, otid >> 16
        d = next((d for d in range(8) if generate_wild(_advance(V, N + d)).pid == pid), None)
        if d is None:
            continue
        offs[N + d] += 1
        slot = generate_wild(_advance(V, N + d)).slot
        slot_species.setdefault(slot, collections.Counter())[sp] += 1
    return tid, sid, offs, slot_species


def main():
    state = sys.argv[1] if len(sys.argv) > 1 else "roms/Pokemon - LeafGreen Version (USA).ss2"
    target = int(sys.argv[2]) if len(sys.argv) > 2 else 56
    tid, sid, offs, ss = calibrate(state)
    print("STATE=%s  TID=%d SID=%d" % (state, tid, sid))
    print("gen-offset distribution:", dict(sorted(offs.items())))
    tslots = []
    print("slot -> species:")
    for slot, c in sorted(ss.items()):
        print("  slot %d: %s" % (slot, {SPN.get(k, k): v for k, v in c.items()}))
        if target in c and len(c) == 1:
            tslots.append(slot)
    print("MANKEY_SLOTS = %s" % (tuple(tslots),))
    print("GEN_OFFSETS (top) = %s" % ([k for k, _ in offs.most_common(4)],))


if __name__ == "__main__":
    main()
