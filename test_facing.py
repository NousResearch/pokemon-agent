"""Quick test: verify facing direction address works correctly."""
import sys
sys.path.insert(0, ".")

from pokemon_agent.emulator import create_emulator
from pokemon_agent.memory.red import (
    PokemonRedReader, ADDR_MAP_X, ADDR_MAP_Y, ADDR_FACING, FACING_NAMES
)

emu = create_emulator("roms/pokemon_red.gb")
emu.load_state("roms/test_state.sav")
emu.tick(30)

# Clear dialog
for _ in range(20):
    emu.press("b", 4)
    emu.tick(16)

reader = PokemonRedReader(emu)

# Test facing in each direction
for direction in ["down", "up", "left", "right"]:
    emu.press(direction, 8)
    emu.tick(12)
    
    facing_byte = emu.read_u8(ADDR_FACING)
    facing_name = FACING_NAMES.get(facing_byte, f"unknown(0x{facing_byte:02X})")
    x = emu.read_u8(ADDR_MAP_X)
    y = emu.read_u8(ADDR_MAP_Y)
    
    # Also check the sprite state data for facing
    # wSpritePlayerStateData1FacingDirection is at C109
    sprite_facing = emu.read_u8(0xC109)
    
    print(f"Pressed {direction:5s}: ADDR_FACING=0x{facing_byte:02X}({facing_name}) "
          f"sprite=0x{sprite_facing:02X} pos=({x},{y})")

# Check which address actually tracks facing
print("\nScanning for facing direction byte...")
# wPlayerDirection is at 0xD367 according to some sources
# wSpritePlayerStateData1FacingDirection is at 0xC109  
# Let's check a range

# Walk down and check various candidates
emu.press("down", 8)
emu.tick(12)
print(f"After walk_down:")
for name, addr in [
    ("0xD367 (wPlayerDirection)", 0xD367),
    ("0xC109 (sprite facing)", 0xC109),
    ("0xC100 (sprite data 1 start)", 0xC100),
    ("0xC102", 0xC102),
    ("0xC103", 0xC103),
    ("0xC104", 0xC104),
    ("0xC105", 0xC105),
    ("0xC106", 0xC106),
    ("0xC107", 0xC107),
    ("0xC108", 0xC108),
    ("0xC109", 0xC109),
    ("0xC10A", 0xC10A),
]:
    val = emu.read_u8(addr)
    print(f"  {name} = 0x{val:02X} ({val})")

# Walk up and compare
emu.press("up", 8)
emu.tick(12)
print(f"\nAfter walk_up:")
for name, addr in [
    ("0xD367 (wPlayerDirection)", 0xD367),
    ("0xC109 (sprite facing)", 0xC109),
]:
    val = emu.read_u8(addr)
    print(f"  {name} = 0x{val:02X} ({val})")

# Walk left and compare
emu.press("left", 8)
emu.tick(12)
print(f"\nAfter walk_left:")
for name, addr in [
    ("0xD367 (wPlayerDirection)", 0xD367),
    ("0xC109 (sprite facing)", 0xC109),
]:
    val = emu.read_u8(addr)
    print(f"  {name} = 0x{val:02X} ({val})")

# Walk right and compare
emu.press("right", 8)
emu.tick(12)
print(f"\nAfter walk_right:")
for name, addr in [
    ("0xD367 (wPlayerDirection)", 0xD367),
    ("0xC109 (sprite facing)", 0xC109),
]:
    val = emu.read_u8(addr)
    print(f"  {name} = 0x{val:02X} ({val})")

emu.close()
