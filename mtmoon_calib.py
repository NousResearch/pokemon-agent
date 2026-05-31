"""Move the Mt. Moon character one tile, save a fresh state, and run a HEAVY
calibration to map Clefairy's slot + the (wide, low-rate) trigger-offset spread.
"""
import sys

import mgba.core
import mgba.image
import mgba.log

from pokemon_agent.gba_state import load_state_file, save_state_file

mgba.log.silence()
ROM = "roms/Pokemon - LeafGreen Version (USA).gba"
SRC = "roms/leafgreen_mtmoon.ss1"
DST = "roms/leafgreen_mtmoon2.ss1"
DIR = sys.argv[1] if len(sys.argv) > 1 else "U"
N = int(sys.argv[2]) if len(sys.argv) > 2 else 100

core = mgba.core.load_path(ROM)
fb = mgba.image.Image(*core.desired_video_dimensions())
core.set_video_buffer(fb); core.reset(); load_state_file(core, SRC)
key = {"U": core.KEY_UP, "D": core.KEY_DOWN, "L": core.KEY_LEFT, "R": core.KEY_RIGHT}[DIR]
for _ in range(18):
    core.set_keys(key); core.run_frame()
core.set_keys()
for _ in range(10):
    core.run_frame()
save_state_file(core, DST)
print("moved %s, saved %s" % (DIR, DST), flush=True)

from gba_grass_calibrate import calibrate  # noqa: E402
tid, sid, offs, ss = calibrate(DST, n_samples=N)
print("TID=%d SID=%d  samples-with-offset=%d" % (tid, sid, sum(offs.values())))
print("offset distribution:", dict(sorted(offs.items())))
print("slot -> species:", {k: dict(v) for k, v in sorted(ss.items())})
clef = [s for s, c in ss.items() if 35 in c]
print("Clefairy(35) slots:", clef)
