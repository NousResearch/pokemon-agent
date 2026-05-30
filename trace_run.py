"""Cycle/scanline tracer for one wild generation. Replays the jiggle with
run_frame up to one frame before the encounter commits, then single-steps
CONTINUOUSLY (holding the commit-frame input) until gEnemyParty changes, logging
every gRngValue change with PC + VCOUNT — so we see the slot/level/nature/PID/iv
calls and exactly where the per-frame VBlank Random() lands.

    distrobox enter devbox -- .venv-gba/bin/python trace_run.py [V_hex] [state]
"""
import sys

import mgba.core
import mgba.image
import mgba.log

from pokemon_agent.gba_state import load_state_file
from pokemon_agent.shiny_gen3 import decrypt_block, ivs_from_decrypted

mgba.log.silence()
ROM = "roms/Pokemon - LeafGreen Version (USA).gba"
V = int(sys.argv[1], 0) if len(sys.argv) > 1 else 0x55FF2959
STATE = sys.argv[2] if len(sys.argv) > 2 else "roms/leafgreen_route3_grass.ss1"
ENEMY = 0x0202402C
RNG = 0x03005000
VC = 0x04000006
VBLANK_PC = 0x08044ED8   # the per-frame VBlank Random() call site (from first trace)

core = mgba.core.load_path(ROM)
fb = mgba.image.Image(*core.desired_video_dimensions())
core.set_video_buffer(fb); core.reset(); load_state_file(core, STATE)
base = bytes(core.save_raw_state()); mem = core.memory
L, R = core.KEY_LEFT, core.KEY_RIGHT


def jiggle_inputs(n):
    """The standard hold2/rel1 LR jiggle as a flat per-frame key list."""
    out = []
    i = 0
    while len(out) < n:
        btn = L if (i % 2 == 0) else R
        out += [btn, btn, 0]
        i += 1
    return out[:n]


# Phase 1: find the commit frame F.
core.load_raw_state(base); mem.u32[RNG] = V & 0xFFFFFFFF
bp = mem.u32[ENEMY]
keys = jiggle_inputs(500)
F = None
for f, key in enumerate(keys):
    core.set_keys(key); core.run_frame()
    if mem.u32[ENEMY] != bp:
        F = f; break
if F is None:
    print("no encounter"); sys.exit(1)

# Phase 2: replay run_frame up to frame F-1, then single-step continuously.
core.load_raw_state(base); mem.u32[RNG] = V & 0xFFFFFFFF
for key in keys[:F]:
    core.set_keys(key); core.run_frame()
core.set_keys(keys[F])
prev = mem.u32[RNG]
log = []
committed = False; post = 0
for step in range(3_000_000):
    core.step()
    r = mem.u32[RNG]
    if r != prev:
        log.append((mem.u16[VC], core.cpu.pc, (r >> 16) & 0xFFFF, r))
        prev = r
        if committed:
            post += 1
    if not committed and mem.u32[ENEMY] != bp:
        committed = True
    if committed and post >= 80:
        break

for _ in range(20):
    core.run_frame()
mon = b"".join(mem.u32[ENEMY + 4 * k].to_bytes(4, "little") for k in range(25))
pid = int.from_bytes(mon[0:4], "little"); otid = int.from_bytes(mon[4:8], "little")
dec = decrypt_block(mon[0x20:0x20 + 48], pid, otid)
sp = int.from_bytes(dec[0:2], "little"); ivs = ivs_from_decrypted(dec).as_tuple()
iv1w = (ivs[0] | (ivs[1] << 5) | (ivs[2] << 10)) & 0x7FFF
iv2w = (ivs[3] | (ivs[4] << 5) | (ivs[5] << 10)) & 0x7FFF
print("commit frame F=%d; species=%d pid=%08X ivs=%s iv1=%04X iv2=%04X; rng calls in step phase=%d"
      % (F, sp, pid, ivs, iv1w, iv2w, len(log)))
print("idx vcount pc        out16 note")
for k, (vc, pc, out16, r) in enumerate(log):
    note = "VBLANK" if pc == VBLANK_PC else ""
    if (out16 & 0x7FFF) == iv1w:
        note += " <== iv1?"
    if (out16 & 0x7FFF) == iv2w:
        note += " <== iv2?"
    print("%3d  %3d  %08X  %04X  %s" % (k, vc, pc, out16, note))
