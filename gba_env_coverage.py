"""STEP 0 — validate the multi-environment premise and pick the knob.

Question 1 (premise): does the SAME gen-seed G (same PID) receive DIFFERENT IVs
across different timing environments?
Question 2 (knob): which way of making environments gives wider, more-independent
IV coverage — same-tile INPUT-pattern variation, or WALKED-TILE variation?

Method: from a base in-grass state, build several envs:
  * INPUT envs  = same state, different jiggle patterns (axis/hold/rel).
  * TILE envs   = walk one step in a direction, then the default pattern.
Each env gets its dominant trigger-offset calibrated. For a fixed panel of target
gen-seeds G, reproduce each G in each env (write rewind(G, off), jiggle, confirm
realized PID == generate_wild(G).pid) and read true IVs. Report, per G, how many
DISTINCT IV-tuples appear across INPUT envs vs across TILE envs, and the rate at
which the IV actually changes relative to the base env.

    distrobox enter devbox -- .venv-gba/bin/python gba_env_coverage.py
"""
import random
import mgba.core, mgba.image, mgba.log
from pokemon_agent.gba_state import load_state_file
from pokemon_agent.shiny_gen3 import decrypt_block, ivs_from_decrypted, lcg_next, rewind
from pokemon_agent.gen3_rng import generate_wild

ROM = "roms/Pokemon - LeafGreen Version (USA).gba"
BASE_STATE = "roms/Pokemon - LeafGreen Version (USA).ss5"
ENEMY = 0x0202402C; RNG = 0x03005000


def advance(s, n):
    for _ in range(n):
        s = lcg_next(s)
    return s


def make_core():
    mgba.log.silence()
    core = mgba.core.load_path(ROM)
    fb = mgba.image.Image(*core.desired_video_dimensions())
    core.set_video_buffer(fb); core.reset()
    return core, fb


def decode_enemy(core):
    mem = core.memory
    mon = b"".join(mem.u32[ENEMY + 4 * k].to_bytes(4, "little") for k in range(25))
    pid = int.from_bytes(mon[0:4], "little"); otid = int.from_bytes(mon[4:8], "little")
    try:
        dec = decrypt_block(mon[0x20:0x20 + 48], pid, otid)
    except Exception:
        return None
    return pid, ivs_from_decrypted(dec).as_tuple()


def trigger(core, env_raw, V, axis, hold, rel, cap=460):
    core.load_raw_state(env_raw); core.memory.u32[RNG] = V & 0xFFFFFFFF
    bp = core.memory.u32[ENEMY]
    k1, k2 = (core.KEY_LEFT, core.KEY_RIGHT) if axis == "LR" else (core.KEY_UP, core.KEY_DOWN)
    frames = 0; i = 0; period = hold + rel; hit = False
    while frames < cap:
        btn = k1 if i % 2 == 0 else k2
        for ph in range(period):
            core.set_keys(btn) if ph < hold else core.set_keys()
            core.run_frame(); frames += 1
            if core.memory.u32[ENEMY] != bp:
                hit = True; break
        if hit:
            break
        i += 1
    if not hit:
        return None
    for _ in range(20):
        core.run_frame()
    return decode_enemy(core)


def walk(core, key, frames=16, settle=10):
    for _ in range(frames):
        core.set_keys(key); core.run_frame()
    core.set_keys()
    for _ in range(settle):
        core.run_frame()


def find_offset(core, env_raw, axis, hold, rel, n=12):
    rng = random.Random(1234); cnt = {}; got = 0
    for _ in range(n):
        V = rng.getrandbits(32)
        r = trigger(core, env_raw, V, axis, hold, rel)
        if not r:
            continue
        pid, _iv = r
        for off in range(0, 140):
            if generate_wild(advance(V, off)).pid == pid:
                cnt[off] = cnt.get(off, 0) + 1; got += 1; break
    if not cnt:
        return None, 0
    return max(cnt, key=cnt.get), got


def main():
    core, _fb = make_core()
    core.reset(); load_state_file(core, BASE_STATE)
    base_raw = bytes(core.save_raw_state())

    # TILE envs: one step in a direction from base, then settle.
    def stepped(key):
        core.load_raw_state(base_raw); walk(core, key)
        return bytes(core.save_raw_state())
    tile_up = stepped(core.KEY_UP)
    tile_down = stepped(core.KEY_DOWN)

    # env = (label, method, env_raw, axis, hold, rel)
    envs = [
        ("IN_LR2:1(base)", "input", base_raw, "LR", 2, 1),
        ("IN_LR1:1",       "input", base_raw, "LR", 1, 1),
        ("IN_LR3:1",       "input", base_raw, "LR", 3, 1),
        ("IN_UD2:1",       "input", base_raw, "UD", 2, 1),
        ("TILE_up",        "tile",  tile_up,  "LR", 2, 1),
        ("TILE_down",      "tile",  tile_down, "LR", 2, 1),
    ]

    print("calibrating env offsets...", flush=True)
    valid = []
    for label, method, raw, axis, hold, rel in envs:
        off, got = find_offset(core, raw, axis, hold, rel)
        print("  %-16s method=%-5s offset=%s (got=%d/12)" % (label, method, off, got), flush=True)
        if off is not None and got >= 4:
            valid.append((label, method, raw, axis, hold, rel, off))
    if len(valid) < 2:
        print("not enough valid envs"); return

    # Panel of target gen-seeds.
    prng = random.Random(20260530)
    panel = [prng.getrandbits(32) for _ in range(24)]
    # results[G][label] = iv
    results = {}
    for G in panel:
        tgt = generate_wild(G).pid
        row = {}
        for label, method, raw, axis, hold, rel, off in valid:
            r = trigger(core, raw, rewind(G, off), axis, hold, rel)
            if r and r[0] == tgt:
                row[label] = r[1]
        if len(row) >= 2:
            results[G] = row

    in_labels = [v[0] for v in valid if v[1] == "input"]
    tile_labels = [v[0] for v in valid if v[1] == "tile"]
    base_label = "IN_LR2:1(base)"

    print("\nreproduced G in >=2 envs: %d / %d panel" % (len(results), len(panel)), flush=True)

    def avg_distinct(labels):
        tot = 0; cnt = 0
        for G, row in results.items():
            ivs = [row[l] for l in labels if l in row]
            if len(ivs) >= 2:
                tot += len(set(ivs)); cnt += 1
        return (tot / cnt) if cnt else 0.0, cnt

    di_in, n_in = avg_distinct(in_labels)
    di_tile, n_tile = avg_distinct(tile_labels)
    di_all, n_all = avg_distinct([v[0] for v in valid])
    print("\nAvg DISTINCT IVs per G (higher = wider coverage):")
    print("  across INPUT envs (%d): %.2f distinct  (n=%d, max possible %d)"
          % (len(in_labels), di_in, n_in, len(in_labels)))
    print("  across TILE envs  (%d): %.2f distinct  (n=%d, max possible %d)"
          % (len(tile_labels), di_tile, n_tile, n_tile and len(tile_labels)))
    print("  across ALL envs   (%d): %.2f distinct  (n=%d, max possible %d)"
          % (len(valid), di_all, n_all, len(valid)))

    print("\nIV-change rate vs base (%s): fraction of shared G with a DIFFERENT IV" % base_label)
    for label, method, raw, axis, hold, rel, off in valid:
        if label == base_label:
            continue
        shared = diff = 0
        for G, row in results.items():
            if base_label in row and label in row:
                shared += 1
                if row[base_label] != row[label]:
                    diff += 1
        rate = (diff / shared) if shared else 0.0
        print("  %-16s (%s): %d/%d changed (%.0f%%)" % (label, method, diff, shared, 100 * rate))


if __name__ == "__main__":
    main()
