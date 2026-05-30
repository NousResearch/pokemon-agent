"""Generate a battery of in-grass timing/offset environments for coverage.

Per step-0b: tiles don't widen IVs (deterministic), but each tile has a
DIFFERENT trigger-offset cluster, so unioning a few tiles reproduces nearly the
whole fixed candidate universe. Here we walk a validated random path from a base
in-grass state, save each in-grass tile as a native state file, calibrate its
offset cluster, and write a manifest the multi-env driver consumes.

    distrobox enter devbox -- .venv-gba/bin/python gba_make_envs.py [n] [base.ssN]
"""
import json, os, sys
from pokemon_agent.gba_state import load_state_file, save_state_file
from gba_env_coverage import make_core, trigger, walk, BASE_STATE
import random

OUT_DIR = "roms/envs"
MANIFEST = "envs_route3.json"


def main():
    n_target = int(sys.argv[1]) if len(sys.argv) > 1 else 6
    base_state = sys.argv[2] if len(sys.argv) > 2 else BASE_STATE
    os.makedirs(OUT_DIR, exist_ok=True)
    core, _ = make_core(); core.reset(); load_state_file(core, base_state)
    base_raw = bytes(core.save_raw_state())
    dirs = [core.KEY_UP, core.KEY_DOWN, core.KEY_LEFT, core.KEY_RIGHT]
    rng = random.Random(99)

    paths = []
    p0 = "%s/route3_env00.ss1" % OUT_DIR
    core.load_raw_state(base_raw); save_state_file(core, p0); paths.append(p0)
    current = base_raw; attempts = 0
    while len(paths) < n_target and attempts < n_target * 10:
        attempts += 1
        core.load_raw_state(current); walk(core, rng.choice(dirs)); cand = bytes(core.save_raw_state())
        if any(trigger(core, cand, rng.getrandbits(32), "LR", 2, 1) for _ in range(3)):
            p = "%s/route3_env%02d.ss1" % (OUT_DIR, len(paths))
            core.load_raw_state(cand); save_state_file(core, p); paths.append(p); current = cand

    from gba_grass_calibrate import calibrate
    manifest = []
    for i, p in enumerate(paths):
        tid, sid, offs, ss = calibrate(p)
        top = [k for k, _ in offs.most_common(6)]
        manifest.append({"env_id": "env%02d" % i, "state": p, "axis": "LR", "hold": 2, "rel": 1,
                         "offsets": top, "tid": tid, "sid": sid})
        print("env%02d %s offsets=%s" % (i, p, top), flush=True)
    json.dump({"base": base_state, "envs": manifest}, open(MANIFEST, "w"), indent=2)
    print("wrote %s with %d envs" % (MANIFEST, len(manifest)), flush=True)


if __name__ == "__main__":
    main()
