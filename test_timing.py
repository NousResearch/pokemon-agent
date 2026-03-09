"""
Precise timing test: Find the minimum frames needed to walk one tile.

The first test script failed because the game was still in Oak's introductory
dialog (text_box_id=0x01 was leftover). After clearing dialog, movement works.

Now let's find the MINIMUM total frames needed for a reliable one-tile walk.
"""

import sys
sys.path.insert(0, ".")

from pokemon_agent.emulator import create_emulator
from pokemon_agent.memory.red import ADDR_MAP_X, ADDR_MAP_Y, ADDR_MAP_ID

def main():
    print("Loading ROM + saved state...")
    emu = create_emulator("roms/pokemon_red.gb")
    emu.load_state("roms/test_state.sav")
    emu.tick(60)  # Let game settle

    # Clear any remaining dialog
    for _ in range(30):
        emu.press("b", 4)
        emu.tick(16)

    print("\n=== Minimum frame test: hold=1 frame, vary wait ===")
    # For each test: save state, walk down, check, restore
    emu.save_state("roms/timing_test.sav")

    for total_frames in range(1, 25):
        emu.load_state("roms/timing_test.sav")
        emu.tick(1)  # Let state settle

        sx = emu.read_u8(ADDR_MAP_X)
        sy = emu.read_u8(ADDR_MAP_Y)

        hold = 1
        wait = max(0, total_frames - hold)
        emu.press("down", hold)
        emu.tick(wait)

        ex = emu.read_u8(ADDR_MAP_X)
        ey = emu.read_u8(ADDR_MAP_Y)
        moved = (ex != sx or ey != sy)
        status = "MOVED" if moved else "     "
        print(f"  total={total_frames:2d} (hold={hold}+wait={wait:2d}): "
              f"({sx},{sy})->({ex},{ey}) {status}")

    print("\n=== Minimum frame test: hold=4 frames, vary wait ===")
    for total_frames in range(4, 25):
        emu.load_state("roms/timing_test.sav")
        emu.tick(1)

        sx = emu.read_u8(ADDR_MAP_X)
        sy = emu.read_u8(ADDR_MAP_Y)

        hold = 4
        wait = total_frames - hold
        emu.press("down", hold)
        emu.tick(wait)

        ex = emu.read_u8(ADDR_MAP_X)
        ey = emu.read_u8(ADDR_MAP_Y)
        moved = (ex != sx or ey != sy)
        status = "MOVED" if moved else "     "
        print(f"  total={total_frames:2d} (hold={hold}+wait={wait:2d}): "
              f"({sx},{sy})->({ex},{ey}) {status}")

    print("\n=== Minimum frame test: hold=8 frames, vary wait ===")
    for total_frames in range(8, 25):
        emu.load_state("roms/timing_test.sav")
        emu.tick(1)

        sx = emu.read_u8(ADDR_MAP_X)
        sy = emu.read_u8(ADDR_MAP_Y)

        hold = 8
        wait = total_frames - hold
        emu.press("down", hold)
        emu.tick(wait)

        ex = emu.read_u8(ADDR_MAP_X)
        ey = emu.read_u8(ADDR_MAP_Y)
        moved = (ex != sx or ey != sy)
        status = "MOVED" if moved else "     "
        print(f"  total={total_frames:2d} (hold={hold}+wait={wait:2d}): "
              f"({sx},{sy})->({ex},{ey}) {status}")

    print("\n=== Double-step test: does holding longer cause 2 tiles? ===")
    for hold_frames in [8, 16, 20, 24, 32]:
        emu.load_state("roms/timing_test.sav")
        emu.tick(1)

        sx = emu.read_u8(ADDR_MAP_X)
        sy = emu.read_u8(ADDR_MAP_Y)

        emu.press("down", hold_frames)
        emu.tick(16)  # extra settle time

        ex = emu.read_u8(ADDR_MAP_X)
        ey = emu.read_u8(ADDR_MAP_Y)
        delta_y = ey - sy
        print(f"  hold={hold_frames:2d}: ({sx},{sy})->({ex},{ey}) delta_y={delta_y}")

    # Test walking to a warp (the stairs in Red's House 2F)
    print("\n=== Warp test: Walk to stairs ===")
    emu.load_state("roms/timing_test.sav")
    emu.tick(1)

    pos = f"({emu.read_u8(ADDR_MAP_X)},{emu.read_u8(ADDR_MAP_Y)})"
    map_id = emu.read_u8(ADDR_MAP_ID)
    print(f"  Start: {pos} map={map_id}")

    # In Red's House 2F, stairs are at approximately (7,1)
    # The player starts at (3,6). Let's try walking around.
    # First let's map out the room by trying all directions
    for step in range(20):
        sx = emu.read_u8(ADDR_MAP_X)
        sy = emu.read_u8(ADDR_MAP_Y)
        mid = emu.read_u8(ADDR_MAP_ID)
        
        # Try to walk right toward stairs
        direction = "right" if step < 5 else "up" if step < 15 else "right"
        emu.press(direction, 8)
        emu.tick(16)
        
        ex = emu.read_u8(ADDR_MAP_X)
        ey = emu.read_u8(ADDR_MAP_Y)
        new_mid = emu.read_u8(ADDR_MAP_ID)
        moved = (ex != sx or ey != sy or new_mid != mid)
        warp = new_mid != mid
        
        print(f"  Step {step:2d}: {direction:5s} ({sx},{sy})->({ex},{ey}) "
              f"map={mid}->{new_mid} {'WARP!' if warp else ''}")
        
        if warp:
            print(f"  *** Warped to a new map! ***")
            break

    emu.close()
    print("\nDone!")


if __name__ == "__main__":
    main()
