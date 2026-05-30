"""Reproduce a chosen shiny Spearow encounter from its write-seed and save a
clean mGBA save state at the battle.  Verifies species/shiny/IVs match.

    distrobox enter devbox -- .venv-gba/bin/python reproduce_spearow.py 0x55FF2959
"""
import sys
import mgba.core, mgba.image, mgba.log
from pokemon_agent.gba_state import load_state_file, save_state_file
from pokemon_agent.shiny_gen3 import decrypt_block, ivs_from_decrypted

ROM = "roms/Pokemon - LeafGreen Version (USA).gba"
STATE = "roms/leafgreen_route3_grass.ss1"
OUT = "roms/leafgreen_shiny_spearow.ss1"
ENEMY = 0x0202402C; RNG = 0x03005000
TID, SID = 51376, 36462
NAT = ["Hardy","Lonely","Brave","Adamant","Naughty","Bold","Docile","Relaxed","Impish","Lax",
       "Timid","Hasty","Serious","Jolly","Naive","Modest","Mild","Quiet","Bashful","Rash",
       "Calm","Gentle","Sassy","Careful","Quirky"]

V = int(sys.argv[1], 0) if len(sys.argv) > 1 else 0x55FF2959
mgba.log.silence()
core = mgba.core.load_path(ROM); fb = mgba.image.Image(*core.desired_video_dimensions())
core.set_video_buffer(fb); core.reset(); load_state_file(core, STATE)
mem = core.memory; L, R = core.KEY_LEFT, core.KEY_RIGHT
mem.u32[RNG] = V; bp = mem.u32[ENEMY]; i = 0
while i < 70:
    btn = L if i % 2 == 0 else R
    for ph in range(3):
        core.set_keys(btn) if ph < 2 else core.set_keys(); core.run_frame()
        if mem.u32[ENEMY] != bp: i = 999; break
    if i == 999: break
    i += 1
for _ in range(40):  # let the battle intro settle so it's a clean state to load
    core.run_frame()
mon = b"".join(mem.u32[ENEMY + 4 * k].to_bytes(4, "little") for k in range(25))
pid = int.from_bytes(mon[0:4], "little"); otid = int.from_bytes(mon[4:8], "little")
dec = decrypt_block(mon[0x20:0x20 + 48], pid, otid)
sp = int.from_bytes(dec[0:2], "little"); ivs = ivs_from_decrypted(dec).as_tuple()
shiny = ((TID ^ SID ^ (pid >> 16) ^ (pid & 0xFFFF)) & 0xFFFF) < 8
print("write=0x%08X species=%d shiny=%s nature=%s" % (V, sp, shiny, NAT[pid % 25]))
print("IVs(HP,Atk,Def,Spe,SpA,SpD)=%s  #31=%d" % (ivs, sum(1 for x in ivs if x == 31)))
if sp == 21 and shiny:
    save_state_file(core, OUT)
    print("saved encounter state ->", OUT)
else:
    print("MISMATCH — not saving", file=sys.stderr); sys.exit(1)
