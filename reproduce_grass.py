"""Reproduce a specific wild encounter by gen-seed G in a given env and save its
battle-start state (mGBA-app loadable).

    reproduce_grass.py <state.ss> <out.ss> <G_hex> <off1,off2,...> [species]
"""
import sys
import shiny_grass_core as C
from pokemon_agent.shiny_gen3 import rewind
from pokemon_agent.gba_state import save_state_file

TID, SID = 51376, 36462


def main():
    state, out, Ghex, offs = sys.argv[1:5]
    G = int(Ghex, 0); offsets = [int(x) for x in offs.split(",")]
    species = int(sys.argv[5]) if len(sys.argv) > 5 else None
    B = C._bundle(state)
    for off in offsets:
        res = C._emulate(B, rewind(G, off), "LR", 2, 1)
        if res and (species is None or res[2] == species):
            pid, iv, sp = res
            shiny = ((TID ^ SID ^ (pid >> 16) ^ (pid & 0xFFFF)) & 0xFFFF) < 8
            print("G=0x%08X off=%d species=%d pid=0x%08X nature=%s shiny=%s IVs=%s"
                  % (G, off, sp, pid, C.NAT[pid % 25], shiny, iv))
            save_state_file(B["core"], out); print("saved ->", out); return 0
    print("no reproduction at offsets", offsets, file=sys.stderr); return 1


if __name__ == "__main__":
    sys.exit(main())
