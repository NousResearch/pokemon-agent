"""Boot the LeafGreen battery save (.sav) to the in-overworld position where it
was last saved (Route 3 grass) and write a native mGBA save state the grass-hunt
tools can load.

Loads the ROM with its adjacent .sav auto-loaded, mashes START/A through the
title + CONTINUE menu, settles, then saves the state.  Verifies the save loaded
by reading gPlayerParty[0] (PID nonzero, OT id == known TID/SID).

    distrobox enter devbox -- .venv-gba/bin/python boot_grass_state.py [out.ssN]
"""
import sys
import mgba.core, mgba.image, mgba.log
from pokemon_agent.gba_state import save_state_file

mgba.log.silence()
ROM = "roms/Pokemon - LeafGreen Version (USA).gba"
OUT = sys.argv[1] if len(sys.argv) > 1 else "roms/leafgreen_route3_grass.ss1"

PARTY = 0x02024284   # gPlayerParty[0] (PID @ +0, OTID @ +4)
RNG = 0x03005000     # gRngValue
TID, SID = 51376, 36462

core = mgba.core.load_path(ROM)
fb = mgba.image.Image(*core.desired_video_dimensions())
core.set_video_buffer(fb)
core.autoload_save()
core.reset()
A, START = core.KEY_A, core.KEY_START

# Mash through Game Freak logo -> title ("press start") -> main menu (CONTINUE is
# pre-highlighted) -> load.  START early to skip logos/title; then A to confirm.
for i in range(900):
    if i < 160 and (i // 4) % 2 == 0:
        core.set_keys(START)
    elif (i // 2) % 2 == 0:
        core.set_keys(A)
    else:
        core.set_keys()
    core.run_frame()

# Release and let the fade-in / control hand-off finish; stand still.
core.set_keys()
for _ in range(220):
    core.run_frame()

pid = core.memory.u32[PARTY]
otid = core.memory.u32[PARTY + 4]
gtid, gsid = otid & 0xFFFF, otid >> 16
print("party0 PID=0x%08X OTID=0x%08X -> TID=%d SID=%d" % (pid, otid, gtid, gsid))
print("save-loaded:", pid != 0 and gtid == TID and gsid == SID)

# RNG should be advancing in the overworld; sample idle delta over a few frames.
a = core.memory.u32[RNG]
for _ in range(5):
    core.run_frame()
b = core.memory.u32[RNG]
print("RNG idle 5-frame: 0x%08X -> 0x%08X (delta %s)" % (a, b, "moved" if a != b else "STATIC"))

save_state_file(core, OUT)
print("saved state ->", OUT)
