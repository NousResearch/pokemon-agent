"""STEP 0b — tile-env saturation curve. How fast does distinct-IV coverage grow
as we stack valid TILE environments, and are longer-nature-loop seeds (our real
shiny targets) more env-sensitive than short-loop ones?

Generates several in-grass tile envs by a validated random walk from the base
state, calibrates each offset, then for a panel of target gen-seeds measures the
cumulative distinct-IV coverage as envs are added, plus the IV-change rate split
by nature-loop length.

    distrobox enter devbox -- .venv-gba/bin/python gba_env_coverage2.py
"""
import random
import mgba.core, mgba.image, mgba.log
from pokemon_agent.gba_state import load_state_file
from pokemon_agent.shiny_gen3 import rewind
from pokemon_agent.gen3_rng import generate_wild
from gba_env_coverage import (make_core, decode_enemy, trigger, walk, find_offset,
                              advance, BASE_STATE)


def gen_tile_envs(core, base_raw, n_target=8, max_attempts=50):
    rng = random.Random(2024)
    dirs = [core.KEY_UP, core.KEY_DOWN, core.KEY_LEFT, core.KEY_RIGHT]
    envs = [("base", base_raw)]; current = base_raw; attempts = 0
    while len(envs) <= n_target and attempts < max_attempts:
        attempts += 1
        core.load_raw_state(current); walk(core, rng.choice(dirs))
        cand = bytes(core.save_raw_state())
        ok = any(trigger(core, cand, rng.getrandbits(32), "LR", 2, 1) for _ in range(3))
        if ok:
            envs.append(("tile%d" % len(envs), cand)); current = cand
    return envs


def main():
    core, _fb = make_core()
    core.reset(); load_state_file(core, BASE_STATE)
    base_raw = bytes(core.save_raw_state())

    envs = gen_tile_envs(core, base_raw, n_target=8)
    print("generated %d in-grass envs (incl base)" % len(envs), flush=True)
    env_off = []
    for label, raw in envs:
        off, got = find_offset(core, raw, "LR", 2, 1)
        print("  %-7s offset=%s (got=%d/12)" % (label, off, got), flush=True)
        env_off.append((label, raw, off, got))
    env_off = [e for e in env_off if e[2] is not None and e[3] >= 4]

    prng = random.Random(20260530)
    panel = [prng.getrandbits(32) for _ in range(40)]
    loop_len = {G: generate_wild(G).loop_iters for G in panel}

    # results[G] = {label: iv}
    results = {}
    for G in panel:
        tgt = generate_wild(G).pid; row = {}
        for label, raw, off, _ in env_off:
            r = trigger(core, raw, rewind(G, off), "LR", 2, 1)
            if r and r[0] == tgt:
                row[label] = r[1]
        results[G] = row

    labels = [e[0] for e in env_off]
    print("\nCumulative distinct-IV coverage as tiles are added (order: %s):" % ", ".join(labels))
    for k in range(1, len(labels) + 1):
        sub = labels[:k]; tot = 0; cnt = 0
        for G, row in results.items():
            ivs = [row[l] for l in sub if l in row]
            if len(ivs) >= 2:
                tot += len(set(ivs)); cnt += 1
        print("  first %d envs: %.2f distinct IVs/G  (n=%d with >=2 reproductions)"
              % (k, (tot / cnt) if cnt else 0.0, cnt), flush=True)

    # Change-rate vs base, split by nature-loop length.
    base_l = labels[0]
    med = sorted(loop_len.values())[len(loop_len) // 2]
    for grp, pred in (("short-loop (<=%d)" % med, lambda L: L <= med),
                      ("long-loop  (> %d)" % med, lambda L: L > med)):
        shared = diff = 0
        for G, row in results.items():
            if not pred(loop_len[G]) or base_l not in row:
                continue
            for l in labels[1:]:
                if l in row:
                    shared += 1
                    if row[l] != row[base_l]:
                        diff += 1
        print("change vs base, %s: %d/%d changed (%.0f%%)"
              % (grp, diff, shared, 100 * diff / shared if shared else 0), flush=True)


if __name__ == "__main__":
    main()
