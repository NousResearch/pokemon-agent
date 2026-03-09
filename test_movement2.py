"""
Test movement - load the saved state and try to actually move.
Debug dialog state and try clearing it first.
"""

import sys
sys.path.insert(0, ".")

from pokemon_agent.emulator import create_emulator
from pokemon_agent.memory.red import (
    PokemonRedReader, ADDR_MAP_X, ADDR_MAP_Y, ADDR_MAP_ID,
    ADDR_JOY_IGNORE, ADDR_TEXT_BOX_ID, ADDR_FACING
)

def read_pos(emu):
    x = emu.read_u8(ADDR_MAP_X)
    y = emu.read_u8(ADDR_MAP_Y)
    map_id = emu.read_u8(ADDR_MAP_ID)
    facing = emu.read_u8(ADDR_FACING)
    joy_ignore = emu.read_u8(ADDR_JOY_IGNORE)
    text_box = emu.read_u8(ADDR_TEXT_BOX_ID)
    return {
        'x': x, 'y': y, 'map': map_id, 
        'facing': facing, 'joy_ignore': joy_ignore, 'text_box': text_box
    }

def main():
    print("Loading ROM + saved state...")
    emu = create_emulator("roms/pokemon_red.gb")
    emu.load_state("roms/test_state.sav")
    emu.tick(1)

    reader = PokemonRedReader(emu)
    
    # Check current state
    pos = read_pos(emu)
    dialog = reader.read_dialog()
    print(f"Position: ({pos['x']}, {pos['y']}) map={pos['map']}")
    print(f"Facing: 0x{pos['facing']:02X}")
    print(f"Joy Ignore: 0x{pos['joy_ignore']:02X} (bit5={bool(pos['joy_ignore'] & 0x20)})")
    print(f"Text Box: 0x{pos['text_box']:02X}")
    print(f"Dialog active: {dialog['active']}")

    # Step 1: Clear any remaining dialog by pressing B and A
    print("\n=== Clearing dialog ===")
    for i in range(30):
        emu.press("b", 4)
        emu.tick(16)
    
    for i in range(10):
        emu.press("a", 4)
        emu.tick(16)

    for i in range(10):
        emu.press("b", 4)
        emu.tick(16)

    pos = read_pos(emu)
    dialog = reader.read_dialog()
    print(f"Position: ({pos['x']}, {pos['y']}) map={pos['map']}")
    print(f"Joy Ignore: 0x{pos['joy_ignore']:02X} (bit5={bool(pos['joy_ignore'] & 0x20)})")
    print(f"Dialog active: {dialog['active']}")
    
    # Step 2: Try walking in all 4 directions
    print("\n=== Movement test (all directions) ===")
    
    for direction in ["down", "left", "right", "up"]:
        sx = emu.read_u8(ADDR_MAP_X)
        sy = emu.read_u8(ADDR_MAP_Y)
        
        # Press direction for 8 frames, then wait 16
        emu.press(direction, 8)
        emu.tick(16)
        
        ex = emu.read_u8(ADDR_MAP_X)
        ey = emu.read_u8(ADDR_MAP_Y)
        moved = (ex != sx or ey != sy)
        facing = emu.read_u8(ADDR_FACING)
        joy_ignore = emu.read_u8(ADDR_JOY_IGNORE)
        print(f"  {direction:5s}: ({sx},{sy})->({ex},{ey}) moved={moved} "
              f"facing=0x{facing:02X} joy_ignore=0x{joy_ignore:02X}")

    # Step 3: Try with longer timing
    print("\n=== Movement test (longer timing) ===")
    for direction in ["down", "left", "right", "up"]:
        sx = emu.read_u8(ADDR_MAP_X)
        sy = emu.read_u8(ADDR_MAP_Y)
        
        # Use button_press/release directly for full control
        pb = emu._pyboy
        pb.button_press(direction)
        for f in range(32):
            pb.tick()
            if f == 7:  # release after 8 frames
                pb.button_release(direction)
        
        ex = emu.read_u8(ADDR_MAP_X)
        ey = emu.read_u8(ADDR_MAP_Y)
        moved = (ex != sx or ey != sy)
        facing = emu.read_u8(ADDR_FACING)
        print(f"  {direction:5s}: ({sx},{sy})->({ex},{ey}) moved={moved} facing=0x{facing:02X}")

    # Step 4: Try with PyBoy's button() convenience method (delay param)
    print("\n=== Movement test (pyboy button() with delay) ===")
    pb = emu._pyboy
    for direction in ["down", "left", "right", "up"]:
        sx = emu.read_u8(ADDR_MAP_X)
        sy = emu.read_u8(ADDR_MAP_Y)
        
        # button(direction, delay=N) presses and auto-releases after N ticks
        pb.button(direction, delay=8)
        for _ in range(24):
            pb.tick()
        
        ex = emu.read_u8(ADDR_MAP_X)
        ey = emu.read_u8(ADDR_MAP_Y)
        moved = (ex != sx or ey != sy)
        facing = emu.read_u8(ADDR_FACING)
        print(f"  {direction:5s}: ({sx},{sy})->({ex},{ey}) moved={moved} facing=0x{facing:02X}")

    # Step 5: Maybe we need to let the game run some frames first before inputs register
    print("\n=== Let game run 120 frames, then try ===")
    emu.tick(120)
    
    pos = read_pos(emu)
    print(f"After idle: ({pos['x']},{pos['y']}) joy_ignore=0x{pos['joy_ignore']:02X} dialog={reader.read_dialog()['active']}")
    
    for direction in ["down", "left", "right", "up"]:
        sx = emu.read_u8(ADDR_MAP_X)
        sy = emu.read_u8(ADDR_MAP_Y)
        
        emu.press(direction, 8)
        emu.tick(16)
        
        ex = emu.read_u8(ADDR_MAP_X)
        ey = emu.read_u8(ADDR_MAP_Y)
        moved = (ex != sx or ey != sy)
        print(f"  {direction:5s}: ({sx},{sy})->({ex},{ey}) moved={moved}")

    # Step 6: Try with even longer total frames  
    print("\n=== Try 8-frame hold + 40-frame wait ===")
    for direction in ["down", "left", "right", "up"]:
        sx = emu.read_u8(ADDR_MAP_X)
        sy = emu.read_u8(ADDR_MAP_Y)
        
        emu.press(direction, 8)
        emu.tick(40)
        
        ex = emu.read_u8(ADDR_MAP_X)
        ey = emu.read_u8(ADDR_MAP_Y)
        moved = (ex != sx or ey != sy)
        print(f"  {direction:5s}: ({sx},{sy})->({ex},{ey}) moved={moved}")

    # Check wWalkCounter address (0xCFC5)
    walk_counter = emu.read_u8(0xCFC5)
    print(f"\nwWalkCounter: {walk_counter}")
    
    # Check wWalkBikeSurfState (0xD700)
    wbs_state = emu.read_u8(0xD700)
    print(f"wWalkBikeSurfState: {wbs_state}")

    # Read some surrounding bytes for debug  
    print("\nDebug RAM dump around key addresses:")
    for name, addr in [("wJoyIgnore", 0xD730), ("wStatusFlags5", 0xD736), 
                       ("wWalkCounter", 0xCFC5), ("wStatusFlags3", 0xD72E)]:
        val = emu.read_u8(addr)
        print(f"  {name} (0x{addr:04X}) = 0x{val:02X} = {val}")

    emu.close()
    print("\nDone!")


if __name__ == "__main__":
    main()
