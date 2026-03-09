"""
Test script: Get through the intro and test walking movement timing.

Goal: Boot the game, skip past the title screen, get through Oak's intro,
get to the overworld, and verify walk_* commands move exactly one tile.
"""

import sys
import time

sys.path.insert(0, ".")

from pokemon_agent.emulator import create_emulator
from pokemon_agent.memory.red import PokemonRedReader, ADDR_MAP_X, ADDR_MAP_Y, ADDR_MAP_ID

def main():
    print("Loading ROM...")
    emu = create_emulator("roms/pokemon_red.gb")
    reader = PokemonRedReader(emu)

    # -----------------------------------------------------------------------
    # Phase 1: Skip the title screen
    # -----------------------------------------------------------------------
    print("\n=== Phase 1: Title screen ===")
    # The game starts with the Game Freak logo, then the title screen.
    # We need to press Start/A to get through. Let's tick a lot first.

    # Let the intro animation play for a few seconds
    print("  Waiting for title screen (180 frames = 3 sec)...")
    emu.tick(180)

    # Press Start to get past title
    print("  Pressing Start...")
    emu.press("start", 8)
    emu.tick(30)

    # Press A a few times to advance through "New Game" selection
    for i in range(10):
        emu.press("a", 8)
        emu.tick(30)

    # Check where we are
    map_id = emu.read_u8(ADDR_MAP_ID)
    print(f"  Current map ID: {map_id}")

    # We might need more button presses to get through Oak's intro
    # The intro has Oak talking, choosing a name, etc.
    # Let's spam A for a while
    print("  Pressing A through Oak's intro...")
    for i in range(80):
        emu.press("a", 4)
        emu.tick(20)
        if i % 20 == 0:
            map_id = emu.read_u8(ADDR_MAP_ID)
            x = emu.read_u8(ADDR_MAP_X)
            y = emu.read_u8(ADDR_MAP_Y)
            print(f"    Frame batch {i}: map={map_id} pos=({x},{y})")

    # Select DOWN for name selection and A to confirm
    print("  Trying name selection...")
    emu.press("a", 4)
    emu.tick(20)

    # Continue pressing through dialog
    for i in range(100):
        emu.press("a", 4)
        emu.tick(20)
        if i % 25 == 0:
            map_id = emu.read_u8(ADDR_MAP_ID)
            x = emu.read_u8(ADDR_MAP_X)
            y = emu.read_u8(ADDR_MAP_Y)
            print(f"    Frame batch {i}: map={map_id} pos=({x},{y})")

    # -----------------------------------------------------------------------
    # Phase 2: Check if we're on a playable map
    # -----------------------------------------------------------------------
    print("\n=== Phase 2: Check location ===")
    map_id = emu.read_u8(ADDR_MAP_ID)
    x = emu.read_u8(ADDR_MAP_X)
    y = emu.read_u8(ADDR_MAP_Y)
    player_info = reader.read_player()
    map_info = reader.read_map_info()
    print(f"  Map: {map_info['map_name']} (id={map_id})")
    print(f"  Position: ({x}, {y})")
    print(f"  Player name: {player_info['name']}")
    print(f"  Facing: {player_info['facing']}")

    # If we're still at map 0 pos 0,0 we're not in-game yet
    if map_id == 0 and x == 0 and y == 0:
        print("\n  Still at title/intro. Pressing more...")
        for i in range(200):
            emu.press("a", 4)
            emu.tick(16)
        
        map_id = emu.read_u8(ADDR_MAP_ID)
        x = emu.read_u8(ADDR_MAP_X)
        y = emu.read_u8(ADDR_MAP_Y)
        map_info = reader.read_map_info()
        print(f"  Now at: {map_info['map_name']} (id={map_id}) pos=({x},{y})")

    # -----------------------------------------------------------------------
    # Phase 3: Movement timing test (if we're in-game)
    # -----------------------------------------------------------------------
    if x > 0 or y > 0 or map_id > 10:
        print("\n=== Phase 3: Movement Test ===")
        
        # Record starting position
        start_x = emu.read_u8(ADDR_MAP_X)
        start_y = emu.read_u8(ADDR_MAP_Y)
        print(f"  Start position: ({start_x}, {start_y})")

        # Test 1: Walk down with current timing (press 8 frames, wait 16)
        print("\n  --- Test 1: press 8 + wait 16 (total 24 frames after press) ---")
        emu.press("down", 8)
        emu.tick(16)
        x_after = emu.read_u8(ADDR_MAP_X)
        y_after = emu.read_u8(ADDR_MAP_Y)
        moved = (x_after != start_x or y_after != start_y)
        print(f"  After: ({x_after}, {y_after}) - moved={moved}")

        # Test 2: Try a shorter hold (4 frames) + longer wait
        start_x2, start_y2 = x_after, y_after
        print("\n  --- Test 2: press 4 + wait 20 (total 24 frames after press) ---")
        emu.press("down", 4)
        emu.tick(20)
        x_after2 = emu.read_u8(ADDR_MAP_X)
        y_after2 = emu.read_u8(ADDR_MAP_Y)
        moved2 = (x_after2 != start_x2 or y_after2 != start_y2)
        print(f"  After: ({x_after2}, {y_after2}) - moved={moved2}")

        # Test 3: Try 1 frame press + 15 frame wait = 16 total
        start_x3, start_y3 = x_after2, y_after2
        print("\n  --- Test 3: press 1 + wait 15 (total 16 frames) ---")
        emu.press("down", 1)
        emu.tick(15)
        x_after3 = emu.read_u8(ADDR_MAP_X)
        y_after3 = emu.read_u8(ADDR_MAP_Y)
        moved3 = (x_after3 != start_x3 or y_after3 != start_y3)
        print(f"  After: ({x_after3}, {y_after3}) - moved={moved3}")

        # Test 4: Systematic -- try different total frame counts
        print("\n  --- Test 4: Systematic frame count test ---")
        for total_frames in [8, 12, 16, 20, 24]:
            # Reset - walk up first to make room
            emu.press("up", 8)
            emu.tick(16)
            
            sx = emu.read_u8(ADDR_MAP_X)
            sy = emu.read_u8(ADDR_MAP_Y)
            
            # Now walk down with specific timing
            hold_frames = 4
            wait_frames = total_frames - hold_frames
            if wait_frames < 0:
                wait_frames = 0
            emu.press("down", hold_frames)
            emu.tick(wait_frames)
            
            ex = emu.read_u8(ADDR_MAP_X)
            ey = emu.read_u8(ADDR_MAP_Y)
            moved_t = (ex != sx or ey != sy)
            print(f"    hold={hold_frames} + wait={wait_frames} (total={total_frames}): "
                  f"({sx},{sy})->({ex},{ey}) moved={moved_t}")
    else:
        print("\n  NOT in-game yet. Need to handle the intro differently.")
        print(f"  map={map_id} x={x} y={y}")

    # Save state for future use
    print("\n=== Saving state ===")
    try:
        emu.save_state("/home/teknium/pokemon-agent/roms/test_state.sav")
        print("  Saved to roms/test_state.sav")
    except Exception as e:
        print(f"  Save failed: {e}")

    from pokemon_agent.state.builder import build_game_state, build_state_summary
    state = build_game_state(reader)
    print("\n" + build_state_summary(state))

    emu.close()
    print("\nDone!")


if __name__ == "__main__":
    main()
